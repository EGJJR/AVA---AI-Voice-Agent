import os
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from datetime import datetime
from typing import Optional, Dict, Any
import pytz

logger = logging.getLogger(__name__)

class SMSService:
    """SMS service for sending appointment notifications via Twilio/WhatsApp"""
    
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.twilio_phone_number = os.getenv("TWILIO_PHONE_NUMBER", "whatsapp:+14155238886")
        self.user_phone_number = os.getenv("USER_PHONE_NUMBER", "whatsapp:+18478679962")
        
        if not all([self.account_sid, self.auth_token]):
            logger.error("Twilio credentials not configured. SMS notifications will be disabled.")
            self.client = None
        else:
            try:
                self.client = Client(self.account_sid, self.auth_token)
                logger.info("Twilio client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.client = None
    
    def format_appointment_confirmation(self, event_details: Dict[str, Any]) -> str:
        """Format event details into appointment confirmation message"""
        summary = event_details.get('summary', 'Appointment')
        start_time = event_details.get('start', {}).get('dateTime', '')
        location = event_details.get('location', 'Location TBD')
        
        # Parse and format datetime
        try:
            if start_time:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                # Convert to Chicago timezone for display
                chicago_tz = pytz.timezone('America/Chicago')
                dt_chicago = dt.astimezone(chicago_tz)
                formatted_date = dt_chicago.strftime("%A, %B %d, %Y")
                formatted_time = dt_chicago.strftime("%I:%M %p %Z")
            else:
                formatted_date = "Date TBD"
                formatted_time = "Time TBD"
        except:
            formatted_date = "Date TBD"
            formatted_time = "Time TBD"
        
        # Calculate duration if available
        duration_text = ""
        if 'end' in event_details and event_details['end'].get('dateTime'):
            try:
                end_time = event_details['end']['dateTime']
                chicago_tz = pytz.timezone('America/Chicago')
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(chicago_tz)
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00')).astimezone(chicago_tz)
                duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                duration_text = f" Duration: {duration_minutes} minutes."
            except:
                pass
        
        message = f"""📅 APPOINTMENT CONFIRMED

{summary}
Date: {formatted_date}
Time: {formatted_time}{duration_text}
Location: {location}

Thank you for scheduling with us. If you need to make any changes, please contact us as soon as possible.

Have a great day!"""
        
        return message
    
    def format_appointment_cancellation(self, event_details: Dict[str, Any]) -> str:
        """Format event details into appointment cancellation message"""
        summary = event_details.get('summary', 'Appointment')
        start_time = event_details.get('start', {}).get('dateTime', '')
        location = event_details.get('location', 'Location TBD')
        
        # Parse and format datetime
        try:
            if start_time:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                # Convert to Chicago timezone for display
                chicago_tz = pytz.timezone('America/Chicago')
                dt_chicago = dt.astimezone(chicago_tz)
                formatted_date = dt_chicago.strftime("%A, %B %d, %Y")
                formatted_time = dt_chicago.strftime("%I:%M %p %Z")
            else:
                formatted_date = "Date TBD"
                formatted_time = "Time TBD"
        except:
            formatted_date = "Date TBD"
            formatted_time = "Time TBD"
        
        message = f"""❌ APPOINTMENT CANCELED

Your appointment has been canceled:

{summary}
Date: {formatted_date}
Time: {formatted_time}
Location: {location}

If you need to reschedule, please contact us. We're here to help!

Thank you for notifying us in advance."""
        
        return message
    
    def format_appointment_rescheduling(self, old_event_details: Dict[str, Any], new_event_details: Dict[str, Any]) -> str:
        """Format event details into appointment rescheduling message"""
        summary = new_event_details.get('summary', 'Appointment')
        
        # Format old appointment details
        chicago_tz = pytz.timezone('America/Chicago')
        old_start_time = old_event_details.get('start', {}).get('dateTime', '')
        try:
            if old_start_time:
                old_dt = datetime.fromisoformat(old_start_time.replace('Z', '+00:00'))
                old_dt_chicago = old_dt.astimezone(chicago_tz)
                old_formatted_date = old_dt_chicago.strftime("%A, %B %d, %Y")
                old_formatted_time = old_dt_chicago.strftime("%I:%M %p %Z")
            else:
                old_formatted_date = "Date TBD"
                old_formatted_time = "Time TBD"
        except:
            old_formatted_date = "Date TBD"
            old_formatted_time = "Time TBD"
        
        # Format new appointment details
        new_start_time = new_event_details.get('start', {}).get('dateTime', '')
        new_location = new_event_details.get('location', 'Location TBD')
        try:
            if new_start_time:
                new_dt = datetime.fromisoformat(new_start_time.replace('Z', '+00:00'))
                new_dt_chicago = new_dt.astimezone(chicago_tz)
                new_formatted_date = new_dt_chicago.strftime("%A, %B %d, %Y")
                new_formatted_time = new_dt_chicago.strftime("%I:%M %p %Z")
            else:
                new_formatted_date = "Date TBD"
                new_formatted_time = "Time TBD"
        except:
            new_formatted_date = "Date TBD"
            new_formatted_time = "Time TBD"
        
        # Calculate duration if available
        duration_text = ""
        if 'end' in new_event_details and new_event_details['end'].get('dateTime'):
            try:
                end_time = new_event_details['end']['dateTime']
                start_dt = datetime.fromisoformat(new_start_time.replace('Z', '+00:00')).astimezone(chicago_tz)
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00')).astimezone(chicago_tz)
                duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                duration_text = f" Duration: {duration_minutes} minutes."
            except:
                pass
        
        message = f"""🔄 APPOINTMENT RESCHEDULED

{summary}

PREVIOUS TIME:
Date: {old_formatted_date}
Time: {old_formatted_time}

NEW TIME:
Date: {new_formatted_date}
Time: {new_formatted_time}{duration_text}
Location: {new_location}

Your appointment has been successfully rescheduled. Thank you for the advance notice!"""
        
        return message
    
    def send_sms(self, message: str) -> Dict[str, Any]:
        """Send SMS message and return result"""
        if not self.client:
            return {
                'success': False,
                'error': 'SMS_SERVICE_UNAVAILABLE',
                'message': 'SMS service not available - check Twilio credentials'
            }
        
        try:
            # Ensure message isn't too long for WhatsApp (1600 char limit)
            if len(message) > 1600:
                message = message[:1597] + "..."
            
            sms_message = self.client.messages.create(
                to=self.user_phone_number,
                from_=self.twilio_phone_number,
                body=message
            )
            
            logger.info(f"SMS sent successfully to {self.user_phone_number}")
            return {
                'success': True,
                'message': 'SMS sent successfully',
                'message_sid': sms_message.sid
            }
            
        except TwilioRestException as e:
            error_message = f"Twilio error {e.code}: {e.msg}"
            logger.error(error_message)
            return {
                'success': False,
                'error': 'TWILIO_ERROR',
                'message': error_message,
                'code': e.code
            }
        except Exception as e:
            error_message = f"Failed to send SMS: {str(e)}"
            logger.error(error_message)
            return {
                'success': False,
                'error': 'SMS_SEND_ERROR',
                'message': error_message
            }
    
    def send_confirmation_sms(self, event_details: Dict[str, Any]) -> Dict[str, Any]:
        """Send appointment confirmation SMS"""
        message = self.format_appointment_confirmation(event_details)
        return self.send_sms(message)
    
    def send_cancellation_sms(self, event_details: Dict[str, Any]) -> Dict[str, Any]:
        """Send appointment cancellation SMS"""
        message = self.format_appointment_cancellation(event_details)
        return self.send_sms(message)
    
    def send_rescheduling_sms(self, old_event_details: Dict[str, Any], new_event_details: Dict[str, Any]) -> Dict[str, Any]:
        """Send appointment rescheduling SMS"""
        message = self.format_appointment_rescheduling(old_event_details, new_event_details)
        return self.send_sms(message)
    
    def send_custom_sms(self, custom_message: str) -> Dict[str, Any]:
        """Send custom SMS message"""
        return self.send_sms(custom_message)

# Global SMS service instance
sms_service = SMSService()
