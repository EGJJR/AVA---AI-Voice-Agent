import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
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

class CancelEventInput(BaseModel):
    event_id: str = Field(..., description="The unique ID of the event to cancel")
    patient_birthday: Optional[str] = Field(None, description="Patient birthday for verification")
    send_notifications: bool = Field(True, description="Whether to send notifications to attendees")

def handle_cancel_event(body: Dict[str, Any], oauth_token: Optional[str]) -> Dict[str, Any]:
    """Handle calendar event cancellation request"""
    logger.info("Processing cancel event request")
    
    try:
        # Validate input
        cancel_input = CancelEventInput(**body)
        
        # Create calendar service
        calendar_service = create_calendar_service(oauth_token)
        if not calendar_service or not calendar_service.is_initialized():
            return {
                'success': False,
                'error': 'CALENDAR_SERVICE_ERROR',
                'message': 'Failed to connect to Google Calendar service. Please check authentication.'
            }
        
        service = calendar_service.get_service()
        
        # Get event details before deleting (for SMS notification)
        try:
            event_to_cancel = service.events().get(calendarId='primary', eventId=cancel_input.event_id).execute()
            logger.info(f"Found event to cancel: {event_to_cancel.get('summary', 'Untitled')}")
        except HttpError as e:
            if e.resp.status == 404:
                return {
                    'success': False,
                    'error': 'EVENT_NOT_FOUND',
                    'message': f"Event with ID '{cancel_input.event_id}' not found. Cannot cancel."
                }
            else:
                raise e
        
        # Verify patient birthday if provided
        if cancel_input.patient_birthday:
            event_description = event_to_cancel.get('description', '')
            # Extract birthday from event description (format: "Birthday: MM/DD/YYYY" or "Birthday: Month DD, YYYY")
            import re
            birthday_match = re.search(r'Birthday:\s*(.+?)(?:\n|$)', event_description)
            if birthday_match:
                stored_birthday = birthday_match.group(1).strip()
                provided_birthday = cancel_input.patient_birthday.strip()
                
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
                        'message': 'The provided birthday does not match our records. Cannot cancel appointment for security reasons.'
                    }
            else:
                return {
                    'success': False,
                    'error': 'NO_BIRTHDAY_ON_FILE',
                    'message': 'No birthday found in appointment records. Cannot verify identity.'
                }

        # Store event details for SMS notification
        event_details = {
            'summary': event_to_cancel.get('summary', 'Appointment'),
            'description': event_to_cancel.get('description', ''),
            'location': event_to_cancel.get('location', ''),
            'start': event_to_cancel.get('start', {}),
            'end': event_to_cancel.get('end', {})
        }
        
        # Cancel the event
        send_updates_option = 'all' if cancel_input.send_notifications else 'none'
        service.events().delete(
            calendarId='primary', 
            eventId=cancel_input.event_id, 
            sendUpdates=send_updates_option
        ).execute()
        
        logger.info(f"Event {cancel_input.event_id} cancelled successfully")
        
        # Send SMS notification
        sms_result = sms_service.send_cancellation_sms(event_details)
        
        success_message = f"Event '{event_details['summary']}' cancelled successfully."
        
        if sms_result.get('success'):
            success_message += " SMS cancellation notification sent."
        else:
            success_message += " (SMS notification failed, but appointment is cancelled)"
        
        return {
            'success': True,
            'message': success_message,
            'event_id': cancel_input.event_id,
            'event_summary': event_details['summary'],
            'sms_sent': sms_result.get('success', False)
        }
        
    except Exception as e:
        if isinstance(e, HttpError):
            if e.resp.status == 404:
                error_message = f"Event with ID '{cancel_input.event_id}' not found. Cannot cancel."
            else:
                error_message = f"Google Calendar API error: {e.resp.reason}"
            logger.error(f"Calendar API error: {e}")
        else:
            error_message = f"An unexpected error occurred: {str(e)}"
            logger.error(f"Unexpected error in cancel_event: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': 'CANCEL_EVENT_ERROR',
            'message': error_message
        }
        
        # Add this at the end of the file
def cancel_event(details: CancelEventInput, session_id: str = "calendar-tools") -> Dict[str, Any]:
    """Wrapper function to match the expected interface"""
    oauth_token = get_oauth_token()
    body = details.dict()
    return handle_cancel_event(body, oauth_token)