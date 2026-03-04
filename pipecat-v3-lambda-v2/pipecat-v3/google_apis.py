import json
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from typing import Optional, Union, Dict, Any

logger = logging.getLogger(__name__)

class GoogleCalendarService:
    """Google Calendar service that uses OAuth token from VAPI headers"""
    
    def __init__(self, oauth_token_json: Union[str, Dict[str, Any]]):
        """
        Initialize Google Calendar service with OAuth token from VAPI.
        
        Args:
            oauth_token_json: JSON string or dict containing OAuth token from VAPI headers
        """
        self.service = None
        self._initialize_service(oauth_token_json)
    
    def _initialize_service(self, oauth_token_json: Union[str, Dict[str, Any]]):
        """Initialize the Google Calendar service using provided OAuth token"""
        try:
            if not oauth_token_json:
                logger.error("OAuth token is missing")
                raise ValueError("OAuth token is required")
            
            logger.info(f"OAuth token type: {type(oauth_token_json)}")
            
            # Parse the OAuth token JSON
            if isinstance(oauth_token_json, str):
                try:
                    token_data = json.loads(oauth_token_json)
                    logger.info("Successfully parsed OAuth token from JSON string")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse OAuth token JSON: {e}")
                    raise ValueError(f"Invalid OAuth token JSON format: {e}")
            else:
                token_data = oauth_token_json
                logger.info("Using OAuth token as dictionary")
            
            logger.info("Initializing Google Calendar service with provided OAuth token")
            logger.info(f"Token data keys: {list(token_data.keys()) if isinstance(token_data, dict) else 'Not a dict'}")
            
            # Create credentials from the token data
            credentials = Credentials(
                token=token_data.get('token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes', ['https://www.googleapis.com/auth/calendar'])
            )
            
            # Build the service
            self.service = build('calendar', 'v3', credentials=credentials, static_discovery=False)
            logger.info("Google Calendar service initialized successfully")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OAuth token JSON: {e}")
            raise ValueError(f"Invalid OAuth token format: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar service: {e}")
            raise ValueError(f"Failed to initialize Google Calendar service: {e}")
    
    def get_service(self):
        """Get the Google Calendar service instance"""
        if not self.service:
            raise ValueError("Google Calendar service not initialized")
        return self.service
    
    def is_initialized(self) -> bool:
        """Check if the service is properly initialized"""
        return self.service is not None

def create_calendar_service(oauth_token: Optional[Union[str, Dict[str, Any]]]) -> Optional[GoogleCalendarService]:
    """
    Create a Google Calendar service instance from OAuth token.
    
    Args:
        oauth_token: OAuth token JSON string from VAPI headers
        
    Returns:
        GoogleCalendarService instance or None if token is invalid
    """
    if not oauth_token:
        logger.error("No OAuth token provided")
        return None
    
    try:
        return GoogleCalendarService(oauth_token)
    except Exception as e:
        logger.error(f"Failed to create calendar service: {e}")
        return None