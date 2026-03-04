import logging
from datetime import datetime, time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
import dateutil.parser
import pytz
import os
import json

from google_apis import create_calendar_service
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

class ListEventsInput(BaseModel):
    time_min_str: Optional[str] = Field(None, description="Start of date/time range to search")
    time_max_str: Optional[str] = Field(None, description="End of date/time range to search")
    search_query: Optional[str] = Field(None, description="Text query to search events")
    max_results: int = Field(10, description="Maximum number of events to return")
    patient_birthday: Optional[str] = Field(None, description="Patient birthday (for filtering if needed)")
    
    @validator('time_min_str', 'time_max_str', pre=True)
    def convert_time_objects_to_strings(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            # Handle empty object {} - return None to use defaults
            if not v:
                return None
            # Handle object format like {"date": "2025-12-31", "time": "23:59"}
            if 'date' in v:
                date_part = v.get('date', '')
                time_part = v.get('time', '00:00')
                if date_part:
                    return f"{date_part} {time_part}"
            # Handle object format like {"year": 2025, "month": 8, "day": 30}
            elif 'year' in v and 'month' in v and 'day' in v:
                year = v.get('year')
                month = v.get('month')
                day = v.get('day')
                hour = v.get('hour', 0)
                minute = v.get('minute', 0)
                return f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
            # If it's a dict but doesn't match expected formats, return None
            return None
        return str(v) if v is not None else None

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
        "tomorrow": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day + 1), time.min),
        "start of tomorrow": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day + 1), time.min),
        "beginning of tomorrow": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day + 1), time.min),
        "end of tomorrow": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day + 1), time.max),
        "yesterday": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day - 1), time.min),
        "start of yesterday": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day - 1), time.min),
        "beginning of yesterday": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day - 1), time.min),
        "end of yesterday": lambda: _combine_dt(today_local_date.replace(day=today_local_date.day - 1), time.max),
    }

    normalized_datetime_str = datetime_str.lower().strip().replace("_", " ")
    dt_obj: Optional[datetime] = None

    handler = relative_date_handlers.get(normalized_datetime_str)
    if handler:
        try:
            dt_obj = handler()
        except ValueError:
            # Handle month/day overflow issues, use timedelta instead
            from datetime import timedelta
            if "tomorrow" in normalized_datetime_str:
                dt_obj = _combine_dt(today_local_date + timedelta(days=1), time.min if "start" in normalized_datetime_str or "beginning" in normalized_datetime_str else time.max if "end" in normalized_datetime_str else time.min)
            elif "yesterday" in normalized_datetime_str:
                dt_obj = _combine_dt(today_local_date - timedelta(days=1), time.min if "start" in normalized_datetime_str or "beginning" in normalized_datetime_str else time.max if "end" in normalized_datetime_str else time.min)
    
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

def handle_list_event(body: Dict[str, Any], oauth_token: Optional[str]) -> Dict[str, Any]:
    """Handle list calendar events request"""
    logger.info("Processing list events request")
    
    try:
        # Validate input
        list_input = ListEventsInput(**body)
        
        # Create calendar service
        calendar_service = create_calendar_service(oauth_token)
        if not calendar_service or not calendar_service.is_initialized():
            return {
                'success': False,
                'error': 'CALENDAR_SERVICE_ERROR',
                'message': 'Failed to connect to Google Calendar service. Please check authentication.'
            }
        
        service = calendar_service.get_service()
        
        # Parse time range
        time_min_iso = None
        if list_input.time_min_str:
            time_min_iso = parse_datetime_for_api(list_input.time_min_str, default_time=time.min) 
        else:
            time_min_iso = datetime.now(pytz.timezone('America/Chicago')).isoformat()

        time_max_iso = None
        if list_input.time_max_str:
            time_max_iso = parse_datetime_for_api(list_input.time_max_str, default_time=time.max) 
        
        if not time_min_iso:
            return {
                'success': False,
                'error': 'INVALID_TIME_RANGE',
                'message': 'Could not parse time_min_str. Please provide a valid start date/time.'
            }
        
        # Query calendar events
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            q=list_input.search_query,
            maxResults=min(list_input.max_results, 250), 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        items = events_result.get('items', [])
        if not items:
            return {
                'success': True,
                'message': 'No events found matching your criteria.',
                'events': [],
                'count': 0
            }

        # Format events for response
        formatted_events = []
        event_list_str = "Found events:\n"
        
        for item in items:
            start = item['start'].get('dateTime', item['start'].get('date')) 
            try:
                start_dt = dateutil.parser.isoparse(start)
                formatted_start = start_dt.strftime('%Y-%m-%d %I:%M %p %Z') if start_dt.time() != time.min else start_dt.strftime('%Y-%m-%d (All-day)')
            except:
                formatted_start = start
            
            event_info = {
                'id': item['id'],
                'summary': item.get('summary', 'No Title'),
                'start': start,
                'formatted_start': formatted_start,
                'location': item.get('location', ''),
                'description': item.get('description', '')
            }
            formatted_events.append(event_info)
            
            event_list_str += f"- '{event_info['summary']}' on {formatted_start} (ID: {item['id']})\n"
        
        if events_result.get('nextPageToken'):
            event_list_str += "\nNote: There may be more events than shown. You can refine your search or increase max_results."
        
        return {
            'success': True,
            'message': event_list_str.strip(),
            'events': formatted_events,
            'count': len(formatted_events),
            'has_more': bool(events_result.get('nextPageToken'))
        }
        
    except Exception as e:
        if isinstance(e, HttpError):
            error_message = f"Google Calendar API error: {e.resp.reason}"
            logger.error(f"Calendar API error: {e}")
        else:
            error_message = f"An unexpected error occurred: {str(e)}"
            logger.error(f"Unexpected error in list_event: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': 'LIST_EVENTS_ERROR',
            'message': error_message
        }
        
        # Add this at the end of the file
def list_event(details: ListEventsInput, session_id: str = "calendar-tools") -> str:
    """Wrapper function to match the expected interface"""
    oauth_token = get_oauth_token()
    body = details.dict()
    result = handle_list_event(body, oauth_token)
    
    if result.get('success'):
        return result.get('message', 'Events listed successfully')
    else:
        return f"Error: {result.get('message', 'Unknown error')}"