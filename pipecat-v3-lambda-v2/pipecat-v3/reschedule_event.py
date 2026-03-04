import logging
from datetime import datetime, timedelta, time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
import dateutil.parser
import pytz
import os
import json

from google_apis import create_calendar_service
from sms_service import sms_service
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

def get_oauth_token():
    """Get OAuth token from environment variable"""
    oauth_token_json = os.getenv('GOOGLE_OAUTH_TOKEN')
    if not oauth_token_json:
        return None
    
    try:
        return json.loads(oauth_token_json)
    except json.JSONDecodeError:
        return None

class RescheduleEventInput(BaseModel):
    event_id: str = Field(..., description="The unique ID of the event to reschedule")
    patient_birthday: Optional[str] = Field(None, description="Patient birthday for verification")
    new_start_time_str: str = Field(..., description="The new start date and time")
    new_end_time_str: Optional[str] = Field(None, description="The new end date and time")
    new_duration_minutes: Optional[int] = Field(None, description="The new duration in minutes")
    new_location: Optional[str] = Field(None, description="The new location")
    new_summary: Optional[str] = Field(None, description="The new event summary")
    new_description: Optional[str] = Field(None, description="The new event description")
    
    @validator('new_duration_minutes', pre=True)
    def validate_duration_minutes(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                return int(v) if v.strip() else None
            except ValueError:
                return None
        return v

def parse_datetime_for_api(datetime_str: str, default_time: Optional[time] = None) -> Optional[str]:
    """Parse datetime string into timezone-aware ISO 8601 string"""
    chicago_tz = pytz.timezone('America/Chicago')
    now_local = datetime.now(chicago_tz)
    today_local_date = now_local.date()

    def _combine_dt(date_part, time_part):
        return datetime.combine(date_part, time_part, tzinfo=chicago_tz)

    # Handlers for relative date strings
    relative_date_handlers = {
        "now": lambda: now_local,
        "today": lambda: _combine_dt(today_local_date, time.min),
        "start of today": lambda: _combine_dt(today_local_date, time.min),
        "beginning of today": lambda: _combine_dt(today_local_date, time.min),
        "end of today": lambda: _combine_dt(today_local_date, time.max),
        "tonight": lambda: _combine_dt(today_local_date, time.max),
        "tomorrow": lambda: _combine_dt(today_local_date + timedelta(days=1), time.min),
        "start of tomorrow": lambda: _combine_dt(today_local_date + timedelta(days=1), time.min),
        "beginning of tomorrow": lambda: _combine_dt(today_local_date + timedelta(days=1), time.min),
        "end of tomorrow": lambda: _combine_dt(today_local_date + timedelta(days=1), time.max),
        "yesterday": lambda: _combine_dt(today_local_date - timedelta(days=1), time.min),
        "start of yesterday": lambda: _combine_dt(today_local_date - timedelta(days=1), time.min),
        "beginning of yesterday": lambda: _combine_dt(today_local_date - timedelta(days=1), time.min),
        "end of yesterday": lambda: _combine_dt(today_local_date - timedelta(days=1), time.max),
    }

    normalized_datetime_str = datetime_str.lower().strip().replace("_", " ")
    dt_obj: Optional[datetime] = None

    handler = relative_date_handlers.get(normalized_datetime_str)
    if handler:
        dt_obj = handler()
    
    if dt_obj:
        if dt_obj.time() == time.min and default_time:
            dt_obj = datetime.combine(dt_obj.date(), default_time, tzinfo=dt_obj.tzinfo)
        return dt_obj.isoformat()

    # Try parsing with dateutil.parser
    try:
        # First try parsing with timezone awareness
        dt_parsed = dateutil.parser.parse(datetime_str, tzinfos={"local": chicago_tz})

        # If no timezone info, assume it's Chicago time
        if dt_parsed.tzinfo is None or dt_parsed.tzinfo.utcoffset(dt_parsed) is None:
            # For naive datetime objects, treat them as Chicago timezone
            dt_parsed = chicago_tz.localize(dt_parsed)
        
        # Apply default time if needed
        if dt_parsed.time() == time.min and default_time:
            dt_parsed = datetime.combine(dt_parsed.date(), default_time, tzinfo=dt_parsed.tzinfo)

        return dt_parsed.isoformat()
    except (ValueError, TypeError, OverflowError) as e:
        logger.error(f"Error parsing date string '{datetime_str}': {e}")
        return None

def handle_reschedule_event(body: Dict[str, Any], oauth_token: Optional[str]) -> Dict[str, Any]:
    """Handle calendar event rescheduling request"""
    logger.info("Processing reschedule event request")
    logger.info(f"OAuth token present: {bool(oauth_token)}")
    logger.info(f"Request body: {body}")
    
    try:
        # Validate input
        reschedule_input = RescheduleEventInput(**body)
        logger.info(f"Validated input: event_id={reschedule_input.event_id}")
        
        # Create calendar service
        calendar_service = create_calendar_service(oauth_token)
        if not calendar_service or not calendar_service.is_initialized():
            logger.error("Failed to create or initialize calendar service")
            logger.error(f"OAuth token type: {type(oauth_token)}")
            logger.error(f"OAuth token length: {len(oauth_token) if oauth_token else 'None'}")
            return {
                'success': False,
                'error': 'CALENDAR_SERVICE_ERROR',
                'message': 'Failed to connect to Google Calendar service. Please check authentication.'
            }
        
        service = calendar_service.get_service()
        
        # Get the existing event
        try:
            event_to_update = service.events().get(calendarId='primary', eventId=reschedule_input.event_id).execute()
            logger.info(f"Found event to reschedule: {event_to_update.get('summary', 'Untitled')}")
        except HttpError as e:
            if e.resp.status == 404:
                return {
                    'success': False,
                    'error': 'EVENT_NOT_FOUND',
                    'message': f"Event with ID '{reschedule_input.event_id}' not found."
                }
            else:
                raise e
        
        # Verify patient birthday if provided
        if reschedule_input.patient_birthday:
            event_description = event_to_update.get('description', '')
            # Extract birthday from event description (format: "Birthday: MM/DD/YYYY" or "Birthday: Month DD, YYYY")
            import re
            birthday_match = re.search(r'Birthday:\s*(.+?)(?:\n|$)', event_description)
            if birthday_match:
                stored_birthday = birthday_match.group(1).strip()
                provided_birthday = reschedule_input.patient_birthday.strip()
                
                # Normalize both birthdays for comparison
                def normalize_birthday(birthday_str):
                    import dateutil.parser
                    try:
                        parsed_date = dateutil.parser.parse(birthday_str)
                        return parsed_date.strftime('%m/%d/%Y')
                    except:
                        return birthday_str.lower().replace(' ', '').replace(',', '')
                
                normalized_stored = normalize_birthday(stored_birthday)
                normalized_provided = normalize_birthday(provided_birthday)
                
                if normalized_stored != normalized_provided:
                    return {
                        'success': False,
                        'error': 'BIRTHDAY_MISMATCH',
                        'message': 'The provided birthday does not match our records. Cannot reschedule appointment for security reasons.'
                    }
            else:
                return {
                    'success': False,
                    'error': 'NO_BIRTHDAY_ON_FILE',
                    'message': 'No birthday found in appointment records. Cannot verify identity.'
                }

        # Store original event details for SMS notification
        original_event_details = {
            'summary': event_to_update.get('summary', 'Appointment'),
            'description': event_to_update.get('description', ''),
            'location': event_to_update.get('location', ''),
            'start': event_to_update.get('start', {}),
            'end': event_to_update.get('end', {})
        }
        
        # Parse new start time
        new_start_iso = parse_datetime_for_api(reschedule_input.new_start_time_str)
        if not new_start_iso:
            return {
                'success': False,
                'error': 'INVALID_START_TIME',
                'message': f"Could not parse new start time: '{reschedule_input.new_start_time_str}'"
            }
        
        new_start_dt = dateutil.parser.isoparse(new_start_iso)
        
        # Determine new end time
        if reschedule_input.new_end_time_str:
            new_end_iso = parse_datetime_for_api(reschedule_input.new_end_time_str)
            if not new_end_iso:
                return {
                    'success': False,
                    'error': 'INVALID_END_TIME',
                    'message': f"Could not parse new end time: '{reschedule_input.new_end_time_str}'"
                }
        elif reschedule_input.new_duration_minutes:
            if reschedule_input.new_duration_minutes <= 0:
                return {
                    'success': False,
                    'error': 'INVALID_DURATION',
                    'message': 'New duration must be positive'
                }
            new_end_dt = new_start_dt + timedelta(minutes=reschedule_input.new_duration_minutes)
            new_end_iso = new_end_dt.isoformat()
        else:
            # Keep original duration
            current_start_dt = dateutil.parser.isoparse(event_to_update['start'].get('dateTime', event_to_update['start'].get('date')))
            current_end_dt = dateutil.parser.isoparse(event_to_update['end'].get('dateTime', event_to_update['end'].get('date')))
            original_duration = current_end_dt - current_start_dt
            new_end_dt = new_start_dt + original_duration
            new_end_iso = new_end_dt.isoformat()
        
        # Validate time range
        if dateutil.parser.isoparse(new_end_iso) <= new_start_dt:
            return {
                'success': False,
                'error': 'INVALID_TIME_RANGE',
                'message': 'The event\'s new end time must be after its new start time'
            }
        
        # Prepare update body
        update_body = {
            'start': {'dateTime': new_start_iso},
            'end': {'dateTime': new_end_iso}
        }
        
        # Update optional fields if provided
        if reschedule_input.new_summary is not None:
            update_body['summary'] = reschedule_input.new_summary
        if reschedule_input.new_description is not None:
            update_body['description'] = reschedule_input.new_description
        if reschedule_input.new_location is not None:
            update_body['location'] = reschedule_input.new_location
        
        # Update the event
        updated_event = service.events().patch(
            calendarId='primary', 
            eventId=reschedule_input.event_id, 
            body=update_body, 
            sendUpdates='all'
        ).execute()
        
        logger.info(f"Event {reschedule_input.event_id} rescheduled successfully")
        
        # Prepare new event details for SMS notification
        new_event_details = {
            'summary': updated_event.get('summary', 'Appointment'),
            'description': updated_event.get('description', ''),
            'location': updated_event.get('location', ''),
            'start': updated_event.get('start', {}),
            'end': updated_event.get('end', {})
        }
        
        # Send SMS notification
        sms_result = sms_service.send_rescheduling_sms(original_event_details, new_event_details)
        
        success_message = f"Event '{new_event_details['summary']}' rescheduled successfully."
        
        if sms_result.get('success'):
            success_message += " SMS rescheduling notification sent."
        else:
            success_message += " (SMS notification failed, but appointment is rescheduled)"
        
        return {
            'success': True,
            'message': success_message,
            'event_id': reschedule_input.event_id,
            'event_summary': new_event_details['summary'],
            'sms_sent': sms_result.get('success', False),
            'original_start': original_event_details['start'],
            'new_start': new_event_details['start']
        }
        
    except Exception as e:
        if isinstance(e, HttpError):
            error_message = f"Google Calendar API error: {e.resp.reason}"
            logger.error(f"Calendar API error: {e}")
        else:
            error_message = f"An unexpected error occurred: {str(e)}"
            logger.error(f"Unexpected error in reschedule_event: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': 'RESCHEDULE_EVENT_ERROR',
            'message': error_message
        }
        
        # Add this at the end of the file
def reschedule_event(details: RescheduleEventInput, session_id: str = "calendar-tools") -> Dict[str, Any]:
    """Wrapper function to match the expected interface"""
    oauth_token = get_oauth_token()
    body = details.dict()
    return handle_reschedule_event(body, oauth_token)