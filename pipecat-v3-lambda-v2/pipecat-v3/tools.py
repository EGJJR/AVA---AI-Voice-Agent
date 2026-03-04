"""
Tools Module - Calendar Management Function Exports

This module serves as a centralized import hub for all calendar management
functions and their associated data models. It provides a clean interface
for importing calendar tools without having to import from individual files.

The module re-exports all the calendar management functions and their
corresponding Pydantic models, making it easy to import everything needed
for calendar operations from a single location.

Functions Exported:
    - create_event: Schedule new appointments
    - list_event: Check calendar availability and find appointments
    - cancel_event: Cancel existing appointments
    - reschedule_event: Reschedule existing appointments
    - send_sms: Send SMS confirmations and notifications

Data Models Exported:
    - CalendarEventInput: Input model for creating appointments
    - ListEventsInput: Input model for listing/searching appointments
    - CancelEventInput: Input model for canceling appointments
    - RescheduleEventInput: Input model for rescheduling appointments
    - SendSMSInput: Input model for sending SMS messages

Usage Examples:
    # Import all functions and models
    from tools import (
        create_event, list_event, cancel_event, reschedule_event, send_sms,
        CalendarEventInput, ListEventsInput, CancelEventInput, 
        RescheduleEventInput, SendSMSInput
    )
    
    # Use functions directly
    result = create_event(CalendarEventInput(...), "session-id")
    events = list_event(ListEventsInput(...), "session-id")

Author: Munster Primary Care Development Team
Version: 3.0
Last Updated: 2024-06-30
"""

# Import all the functions from their individual files
from create_event import create_event, CalendarEventInput
from list_event import list_event, ListEventsInput
from cancel_event import cancel_event, CancelEventInput
from reschedule_event import reschedule_event, RescheduleEventInput
from send_sms import send_sms, SendSMSInput

# Re-export them so they can be imported from tools
__all__ = [
    'create_event',  # Schedule new appointments
    'list_event',    # Check availability and find appointments
    'cancel_event',   # Cancel existing appointments
    'reschedule_event', # Reschedule existing appointments
    'send_sms',         # Send SMS notifications
    
    # Pydantic input models
    'CalendarEventInput',   # Input model for creating appointments
    'ListEventsInput',       # Input model for listing appointments
    'CancelEventInput',       # Input model for canceling appointments
    'RescheduleEventInput',     # Input model for rescheduling appointments
    'SendSMSInput'               # Input model for sending SMS
]

"""
Calendar Management Tools Module

This module provides a unified interface for all calendar management operations
in the AVA voice bot system. It exports functions and data models for:

Calendar Operations:
    - create_event: Create new appointments with patient verification
    - list_event: Search and list appointments with filtering options
    - cancel_event: Cancel appointments with birthday verification
    - reschedule_event: Reschedule appointments with security checks
    - send_sms: Send automated SMS notifications

Security Features:
    - Birthday verification for sensitive operations
    - HIPAA-compliant data handling
    - Input validation and sanitization
    - Error handling and logging

Integration:
    - Google Calendar API integration
    - Twilio SMS service integration
    - Session-based operation tracking
    - Comprehensive error reporting

All functions are designed to work with the AVA voice bot system and provide
consistent error handling and response formats.
"""