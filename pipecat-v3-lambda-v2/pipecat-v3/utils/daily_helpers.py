"""Helper functions for interacting with the Daily API."""

import os
from typing import Dict, Optional

import aiohttp
from dotenv import load_dotenv

from pipecat.transports.services.helpers.daily_rest import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
    DailyRoomSipParams,
)

load_dotenv()


# Initialize Daily API helper
async def get_daily_helper(session: Optional[aiohttp.ClientSession] = None) -> DailyRESTHelper:
    """Get a Daily REST helper with the configured API key."""
    if session is None:
        session = aiohttp.ClientSession()

    api_key = os.getenv("DAILY_API_KEY", "")
    api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
    
    # Debug output
    print(f"DEBUG: Daily API Key length: {len(api_key)}")
    print(f"DEBUG: Daily API Key starts with: {api_key[:10]}..." if api_key else "NOT SET")
    print(f"DEBUG: Daily API URL: {api_url}")
    
    if not api_key:
        raise ValueError("DAILY_API_KEY environment variable is not set")
    
    return DailyRESTHelper(
        daily_api_key=api_key,
        daily_api_url=api_url,
        aiohttp_session=session,  # Add this back for the newer version
    )


async def create_sip_room(
    session: Optional[aiohttp.ClientSession] = None, caller_phone: str = "unknown-caller"
) -> Dict[str, str]:
    """Create a Daily room with SIP capabilities for phone calls.

    Args:
        session: Optional aiohttp session to use for API calls
        caller_phone: The phone number of the caller to use in display name

    Returns:
        Dictionary with room URL, token, and SIP endpoint
    """
    daily_helper = await get_daily_helper(session)

    # Configure SIP parameters
    sip_params = DailyRoomSipParams(
        display_name=caller_phone,
        video=False,
        sip_mode="dial-in",
        num_endpoints=1,
    )

    # Create room properties with SIP enabled
    properties = DailyRoomProperties(
        sip=sip_params,
        enable_dialout=False,  # Changed from True to False
        enable_chat=False,  # No need for chat in a voice bot
        start_video_off=True,  # Voice only
    )

    # Create room parameters
    params = DailyRoomParams(properties=properties)

    # Create the room
    try:
        room = await daily_helper.create_room(params=params)
        print(f"Created room: {room.url} with SIP endpoint: {room.config.sip_endpoint}")

        # Get token for the bot to join
        token = await daily_helper.get_token(room.url, 24 * 60 * 60)  # 24 hours validity

        return {"room_url": room.url, "token": token, "sip_endpoint": room.config.sip_endpoint}
    except Exception as e:
        print(f"Error creating room: {e}")
        raise