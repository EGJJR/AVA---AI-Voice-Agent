import json
import os
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

# Import function modules
from create_event import handle_create_event
from list_event import handle_list_event
from cancel_event import handle_cancel_event
from reschedule_event import handle_reschedule_event
from send_sms import handle_send_sms

# Import Supabase for logging
from supabase import create_client, Client

# Configure logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Supabase client (initialized outside handler for connection reuse)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
else:
    logger.warning("Supabase credentials not found - database logging disabled")

def insert_to_db(session_id: str, user_input: str, agent_output: str, tool_call: Optional[Dict] = None):
    """Insert conversation to database - adapted from original lambda-deployment"""
    if not supabase:
        logger.warning("Database logging skipped - Supabase not available")
        return
    
    try:
        tool_call_json = json.dumps(tool_call) if tool_call else None
        
        supabase.table("chats").insert({
            "chat_id": session_id,  
            "message": user_input, 
            "response": agent_output,
            "tool_call": tool_call_json
        }).execute()
        logger.info("Successfully logged conversation to database")
    except Exception as e:
        logger.error(f"Error inserting to Supabase: {e}")

def parse_vapi_request(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse incoming VAPI request and extract relevant information"""
    try:
        # Handle both direct event and API Gateway event formats
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        logger.info(f"Parsed request body: {json.dumps(body, indent=2)}")
        
        # Extract headers for OAuth token
        headers = event.get('headers', {})
        oauth_token = headers.get('GOOGLE_OAUTH_TOKEN') or headers.get('google_oauth_token')
        
        # Generate session ID for tracking
        session_id = str(uuid.uuid4())
        
        return {
            'body': body,
            'oauth_token': oauth_token,
            'headers': headers,
            'session_id': session_id
        }
    except Exception as e:
        logger.error(f"Error parsing VAPI request: {e}")
        raise ValueError(f"Invalid request format: {e}")

def determine_action(body: Dict[str, Any]) -> str:
    """Determine which action to take based on request parameters"""
    
    # Check for explicit action parameter
    if 'action' in body:
        return body['action']
    
    # Auto-detect action based on parameters
    if 'message_type' in body:
        return 'send_sms'
    elif 'event_id' in body and 'new_start_time_str' in body:
        return 'reschedule_event'
    elif 'event_id' in body and any(key in body for key in ['new_summary', 'new_end_time_str', 'new_duration_minutes']):
        return 'change_event'  # Will route to reschedule_event
    elif 'event_id' in body:
        return 'cancel_event'
    elif any(key in body for key in ['time_min_str', 'time_max_str', 'search_query', 'max_results']):
        return 'list_event'
    elif any(key in body for key in ['patient_name', 'appointment_reason', 'start_time_str']):
        return 'create_event'
    
    # Default fallback
    return 'unknown'

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler function for VAPI calendar integration.
    Routes requests to appropriate function handlers.
    """
    logger.info(f"Lambda invoked with event: {json.dumps(event, default=str)}")
    
    try:
        # Parse the incoming VAPI request
        parsed_request = parse_vapi_request(event)
        body = parsed_request['body']
        oauth_token = parsed_request['oauth_token']
        session_id = parsed_request['session_id']
        
        logger.info(f"Processing request for session: {session_id}")
        
        # Determine which action to take
        action = determine_action(body)
        logger.info(f"Determined action: {action}")
        
        # Route to appropriate handler
        if action == 'create_event':
            result = handle_create_event(body, oauth_token)
        elif action == 'list_event':
            result = handle_list_event(body, oauth_token)
        elif action == 'cancel_event':
            result = handle_cancel_event(body, oauth_token)
        elif action == 'reschedule_event' or action == 'change_event':
            result = handle_reschedule_event(body, oauth_token)
        elif action == 'send_sms':
            result = handle_send_sms(body)
        else:
            result = {
                'success': False,
                'message': f"Unknown action: {action}",
                'error': 'UNKNOWN_ACTION'
            }
        
        # Log the interaction to database
        if action != 'unknown':
            tool_call_info = {
                'action': action,
                'parameters': body,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'oauth_present': bool(oauth_token),
                'result_success': result.get('success', False)
            }
            
            # Create user input description for logging
            user_input = f"VAPI Tool Call: {action}"
            
            # Create agent output for logging
            agent_output = result.get('message', 'No message returned') if isinstance(result, dict) else str(result)
            
            # Insert to database
            insert_to_db(session_id, user_input, agent_output, tool_call_info)
        
        # Return successful response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, GOOGLE_OAUTH_TOKEN'
            },
            'body': json.dumps(result)
        }
        
    except ValueError as e:
        logger.error(f"Request parsing error: {e}")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'success': False,
                'error': 'INVALID_REQUEST',
                'message': str(e)
            })
        }
    
    except Exception as e:
        logger.error(f"Unexpected error in handler: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'success': False,
                'error': 'INTERNAL_ERROR',
                'message': str(e)
            })
        }

# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        'headers': {
            'GOOGLE_OAUTH_TOKEN': '{"token": "test_token"}'
        },
        'body': {
            'action': 'list_event',
            'time_min_str': 'today'
        }
    }
    
    class MockContext:
        def __init__(self):
            self.function_name = "test-function"
            self.aws_request_id = "test-request-id"
    
    result = handler(test_event, MockContext())
    print(json.dumps(result, indent=2))