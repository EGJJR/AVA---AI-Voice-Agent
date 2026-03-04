import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import os
import json

from sms_service import sms_service

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

class SendSMSInput(BaseModel):
    message_type: str = Field(..., description="Type of SMS message: 'confirmation', 'cancellation', 'rescheduling', or 'custom'")
    event_details: Optional[Dict[str, Any]] = Field(None, description="Event details for confirmation/cancellation messages")
    old_event_details: Optional[Dict[str, Any]] = Field(None, description="Old event details for rescheduling messages")
    new_event_details: Optional[Dict[str, Any]] = Field(None, description="New event details for rescheduling messages")
    custom_message: Optional[str] = Field(None, description="Custom message text for 'custom' type")

def handle_send_sms(body: Dict[str, Any]) -> Dict[str, Any]:
    """Handle SMS sending request"""
    logger.info("Processing send SMS request")
    
    try:
        # Validate input
        sms_input = SendSMSInput(**body)
        
        # Route to appropriate SMS function based on message type
        if sms_input.message_type == 'confirmation':
            if not sms_input.event_details:
                return {
                    'success': False,
                    'error': 'MISSING_EVENT_DETAILS',
                    'message': 'Event details are required for confirmation SMS'
                }
            
            result = sms_service.send_confirmation_sms(sms_input.event_details)
            
        elif sms_input.message_type == 'cancellation':
            if not sms_input.event_details:
                return {
                    'success': False,
                    'error': 'MISSING_EVENT_DETAILS',
                    'message': 'Event details are required for cancellation SMS'
                }
            
            result = sms_service.send_cancellation_sms(sms_input.event_details)
            
        elif sms_input.message_type == 'rescheduling':
            if not sms_input.old_event_details or not sms_input.new_event_details:
                return {
                    'success': False,
                    'error': 'MISSING_EVENT_DETAILS',
                    'message': 'Both old and new event details are required for rescheduling SMS'
                }
            
            result = sms_service.send_rescheduling_sms(sms_input.old_event_details, sms_input.new_event_details)
            
        elif sms_input.message_type == 'custom':
            if not sms_input.custom_message:
                return {
                    'success': False,
                    'error': 'MISSING_CUSTOM_MESSAGE',
                    'message': 'Custom message text is required for custom SMS'
                }
            
            result = sms_service.send_custom_sms(sms_input.custom_message)
            
        else:
            return {
                'success': False,
                'error': 'INVALID_MESSAGE_TYPE',
                'message': f"Invalid message type: '{sms_input.message_type}'. Must be 'confirmation', 'cancellation', 'rescheduling', or 'custom'"
            }
        
        # Return the result from SMS service
        if result.get('success'):
            return {
                'success': True,
                'message': f"SMS {sms_input.message_type} sent successfully",
                'message_sid': result.get('message_sid')
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'SMS_SEND_ERROR'),
                'message': result.get('message', 'Failed to send SMS')
            }
        
    except Exception as e:
        error_message = f"An unexpected error occurred: {str(e)}"
        logger.error(f"Unexpected error in send_sms: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': 'SEND_SMS_ERROR',
            'message': error_message
        }
        
        # wrapper function
def send_sms(details: SendSMSInput, session_id: str = "sms-tool") -> Dict[str, Any]:
    """Wrapper function to match the expected interface"""
    oauth_token = get_oauth_token()
    body = details.dict()
    return handle_send_sms(body, oauth_token)