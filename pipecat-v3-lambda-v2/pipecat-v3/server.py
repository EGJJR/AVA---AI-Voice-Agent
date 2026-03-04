"""
Webhook Server for Twilio Call Handling and Voice Bot Orchestration

This module implements a FastAPI web server that handles incoming Twilio voice calls
and orchestrates the AVA voice bot system. It serves as the entry point for all
incoming calls and manages the lifecycle of voice bot sessions.

Key Features:
- Handles Twilio webhook requests for incoming calls
- Creates Daily.co rooms with SIP capabilities for voice communication
- Starts AVA voice bot processes for each call
- Provides health check endpoints for monitoring
- Manages aiohttp sessions for Daily API interactions

Architecture:
1. Twilio sends webhook to /start endpoint when call is received
2. Server creates Daily.co room with SIP endpoint
3. Server starts AVA bot process with room details
4. Server returns TwiML to put caller on hold with music
5. AVA bot handles the actual conversation

Environment Variables Required:
    TWILIO_ACCOUNT_SID: Twilio account identifier
    TWILIO_AUTH_TOKEN: Twilio authentication token
    DAILY_API_KEY: Daily.co API key for room creation
    PORT: Server port (default: 7860)
    NGROK_DOMAIN: Domain for Twilio webhook configuration

"""

import os
import shlex
import subprocess
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse
from utils.daily_helpers import create_sip_room

# Load environment variables
load_dotenv()




# Initialize FastAPI app with aiohttp session
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager for aiohttp session lifecycle.
    
    This context manager creates and manages an aiohttp ClientSession
    that is used for making HTTP requests to the Daily.co API. The session
    is created when the FastAPI app starts and cleaned up when it shuts down.
    
    Args:
        app: FastAPI application instance
        
    Yields:
        None: Control is yielded back to FastAPI during normal operation
        
    Note:
        The aiohttp session is stored in app.state.session and can be accessed
        by request handlers to make HTTP requests to external APIs.
    """
    # Create aiohttp session to be used for Daily API calls
    app.state.session = aiohttp.ClientSession()
    yield
    # Close session when shutting down
    await app.state.session.close()


app = FastAPI(lifespan=lifespan)


@app.post("/start", response_class=PlainTextResponse)
async def handle_call(request: Request):
    """
    Handle incoming Twilio call webhook.
    
    This endpoint receives webhook requests from Twilio when a call is initiated.
    It processes the call data, creates a Daily.co room with SIP capabilities,
    starts the AVA voice bot process, and returns TwiML to put the caller on hold.
    
    Process Flow:
    1. Extract call details from Twilio webhook
    2. Create Daily.co room with SIP endpoint
    3. Start AVA bot process with room details
    4. Return TwiML for music on hold
    
    Args:
        request: FastAPI Request object containing Twilio webhook data
        
    Returns:
        str: TwiML response to put caller on hold with music
        
    Raises:
        HTTPException: If required data is missing or processing fails
        
    Twilio Webhook Parameters:
        CallSid: Unique identifier for the call (required)
        From: Caller's phone number
        To: Called number
        CallStatus: Current status of the call
    """
    print("Received call webhook from Twilio")

    try:
        # Get form data from Twilio webhook
        form_data = await request.form()
        data = dict(form_data)

        # Extract call ID (required to forward the call later)
        call_sid = data.get("CallSid")
        if not call_sid:
            raise HTTPException(status_code=400, detail="Missing CallSid in request")

        # Extract the caller's phone number
        caller_phone = str(data.get("From", "unknown-caller"))
        print(f"Processing call with ID: {call_sid} from {caller_phone}")

        # Create a Daily room with SIP capabilities
        try:
            room_details = await create_sip_room(request.app.state.session, caller_phone)
        except Exception as e:
            print(f"Error creating Daily room: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create Daily room: {str(e)}")

        # Extract necessary details
        room_url = room_details["room_url"]
        token = room_details["token"]
        sip_endpoint = room_details["sip_endpoint"]

        # Make sure we have a SIP endpoint
        if not sip_endpoint:
            raise HTTPException(status_code=500, detail="No SIP endpoint provided by Daily")

        # Start the bot process using virtual environment Python
        bot_cmd = f"./venv/bin/python bot.py -u {room_url} -t {token} -i {call_sid} -s {sip_endpoint}"
        try:
            # Use shlex to properly split the command for subprocess
            cmd_parts = shlex.split(bot_cmd)

            # Start the bot in the background but capture output
            subprocess.Popen(
                cmd_parts,
                env=os.environ.copy(),  # Pass all environment variables
                cwd=os.getcwd(),  # Run from current directory
                # Don't redirect output so we can see logs
                # stdout=subprocess.DEVNULL,
                # stderr=subprocess.DEVNULL
            )
            print(f"Started bot process with command: {bot_cmd}")
        except Exception as e:
            print(f"Error starting bot: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start bot: {str(e)}")


        # Generate TwiML response to put the caller on hold with music
        # You can replace the URL with your own music file
        # or use Twilio's built-in music on hold
        # https://www.twilio.com/docs/voice/twiml/play#music-on-hold
        resp = VoiceResponse()
        resp.play(
            url="https://therapeutic-crayon-2467.twil.io/assets/US_ringback_tone.mp3",
            loop=10, # Loop the music for up to 10 times
        )

        return str(resp)

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
         # Catch any unexpected errors and return 500
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@app.get("/health")
async def health_check():
    """
    Simple health check endpoint for monitoring and load balancers.
    
    This endpoint returns a simple JSON response indicating that the server
    is running and healthy. It's commonly used by monitoring systems,
    load balancers, and container orchestration platforms to verify
    service availability.
    
    Returns:
        Dict[str, str]: JSON response with status information
        
    Example Response:
        {"status": "healthy"}
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    # Run the server
    port = int(os.getenv("PORT", "7860"))
    print(f"Starting server on port {port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
