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
        # Parse the JSON string to a dict
        return json.loads(oauth_token_json)
    except json.JSONDecodeError:
        return None

class CalendarEventInput(BaseModel):
    patient_name: str = Field(..., description="The full name of the patient")
    appointment_reason: str = Field(..., description="The reason for the appointment")
    start_time_str: str = Field(..., description="The start date and time of the event")
    patient_birthday: str = Field(..., description="The patient's birthday")
    duration_minutes: Optional[int] = Field(None, description="Duration in minutes")
    end_time_str: Optional[str] = Field(None, description="The end date and time")
    conversation_summary: Optional[str] = Field(None, description="Summary of the conversation")
    location: Optional[str] = Field(None, description="The location of the event")
    
    @validator('duration_minutes', pre=True)
    def validate_duration_minutes(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                return int(v) if v.strip() else None
            except ValueError:
                return None
        return v

def parse_datetime_for_api(datetime_str: str, default_time: Optional[time] = None, prefer_future: bool = True) -> Optional[str]:
    """Parse datetime string into timezone-aware ISO 8601 string for Google Calendar API"""
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

def handle_create_event(body: Dict[str, Any], oauth_token: Optional[str]) -> Dict[str, Any]:
    """Handle calendar event creation request"""
    logger.info("Processing create event request")
    
    try:
        # Validate input
        event_input = CalendarEventInput(**body)
        
        # Create calendar service
        calendar_service = create_calendar_service(oauth_token)
        if not calendar_service or not calendar_service.is_initialized():
            return {
                'success': False,
                'error': 'CALENDAR_SERVICE_ERROR',
                'message': 'Failed to connect to Google Calendar service. Please check authentication.'
            }
        
        service = calendar_service.get_service()
        
        # Parse start time
        start_iso = parse_datetime_for_api(event_input.start_time_str)
        if not start_iso:
            return {
                'success': False,
                'error': 'INVALID_START_TIME',
                'message': f"Could not understand the start time: '{event_input.start_time_str}'. Please provide a clearer date and time."
            }
        
        start_dt = dateutil.parser.isoparse(start_iso)
        
        # Determine end time
        if event_input.end_time_str:
            end_iso = parse_datetime_for_api(event_input.end_time_str)
            if not end_iso:
                return {
                    'success': False,
                    'error': 'INVALID_END_TIME',
                    'message': f"Could not understand the end time: '{event_input.end_time_str}'"
                }
            end_dt = dateutil.parser.isoparse(end_iso)
        elif event_input.duration_minutes:
            if event_input.duration_minutes <= 0:
                return {
                    'success': False,
                    'error': 'INVALID_DURATION',
                    'message': 'Event duration must be positive'
                }
            end_dt = start_dt + timedelta(minutes=event_input.duration_minutes)
            end_iso = end_dt.isoformat()
        else:
            # Default to 60 minutes
            end_dt = start_dt + timedelta(minutes=60) 
            end_iso = end_dt.isoformat()
        
        if end_dt <= start_dt:
            return {
                'success': False,
                'error': 'INVALID_TIME_RANGE',
                'message': f"The event's end time must be after its start time"
            }
        
        # Create event summary
        summary = f"{event_input.appointment_reason} - {event_input.patient_name}"
        
        # Create description with patient details
        description_parts = []
        if event_input.patient_name:
            description_parts.append(f"Patient: {event_input.patient_name}")
        if event_input.patient_birthday:
            description_parts.append(f"Birthday: {event_input.patient_birthday}")
        if event_input.appointment_reason:
            description_parts.append(f"Reason: {event_input.appointment_reason}")
        if event_input.conversation_summary:
            description_parts.append(f"Notes: {event_input.conversation_summary}")
        
        description = "\n".join(description_parts)
        
        # Create event body
        event_body = {
            'summary': summary,
            'location': event_input.location or '',
            'description': description,
            'start': {'dateTime': start_iso},
            'end': {'dateTime': end_iso},
            'reminders': {'useDefault': True},
        }
        
        # Create the event
        created_event = service.events().insert(calendarId='primary', body=event_body).execute()
        event_url = created_event.get('htmlLink')
        
        logger.info(f"Event created successfully: {created_event.get('id')}")
        
        # Prepare event details for SMS
        event_details = {
            'summary': summary,
            'description': description,
            'location': event_input.location or '',
            'start': {'dateTime': start_iso},
            'end': {'dateTime': end_iso}
        }
        
        # Send SMS confirmation
        sms_result = sms_service.send_confirmation_sms(event_details)
        
        success_message = f"Event '{summary}' created successfully!"
        
        if sms_result.get('success'):
            success_message += " SMS confirmation sent."
        else:
            success_message += " (SMS notification failed, but appointment is scheduled)"
        
        return {
            'success': True,
            'message': success_message,
            'event_id': created_event.get('id'),
            'event_url': event_url,
            'sms_sent': sms_result.get('success', False)
        }
        
    except Exception as e:
        if isinstance(e, HttpError):
            error_message = f"Google Calendar API error: {e.resp.reason}"
            logger.error(f"Calendar API error: {e}")
        else:
            error_message = f"An unexpected error occurred: {str(e)}"
            logger.error(f"Unexpected error in create_event: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': 'CREATE_EVENT_ERROR',
            'message': error_message
        }
        
        # Add this wrapper function at the end of the file
def create_event(details: CalendarEventInput, session_id: str = "calendar-tools") -> Dict[str, Any]:
    """Wrapper function to match the expected interface"""
    # Get OAuth token from environment
    oauth_token = get_oauth_token()
    
    # Convert the CalendarEventInput to a dict for handle_create_event
    body = details.dict()
    return handle_create_event(body, oauth_token)