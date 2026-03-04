"""AVA - AI Receptionist for Munster Primary Care with Google Calendar Integration."""

import argparse
import asyncio
import os
import sys
from datetime import datetime
import pytz

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from twilio.rest import Client

# Pipecat imports for voice processing pipeline
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.cartesia.stt import CartesiaSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.aws.llm import AWSBedrockLLMService, AWSBedrockLLMContext
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.transports.services.daily import DailyParams, DailyTransport

# Initialize Langfuse for tracing (optional; set LANGFUSE_SECRET_KEY to enable)
from langfuse import Langfuse

class _LangfuseNoop:
    def log(self, *args, **kwargs): pass

_langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY")
langfuse = (
    Langfuse(
        secret_key=_langfuse_secret,
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        host=os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
    )
    if _langfuse_secret
    else _LangfuseNoop()
)

# Import calendar management tools
from create_event import create_event, CalendarEventInput
from list_event import list_event, ListEventsInput
from cancel_event import cancel_event, CancelEventInput
from reschedule_event import reschedule_event, RescheduleEventInput
from send_sms import send_sms, SendSMSInput

# Configure logging
logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


def get_twilio_client():
    """Get a Twilio client with current environment variables"""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    
    logger.info(f"SID repr: {repr(account_sid)} (len={len(account_sid)})")
    logger.info(f"Token repr: {repr(auth_token)} (len={len(auth_token)})")
    if not account_sid or not auth_token:
        logger.error(f"Missing Twilio credentials: SID={account_sid}, Token={'SET' if auth_token else 'NOT SET'}")
        raise ValueError("Missing Twilio credentials")
    
    logger.info(f"Creating Twilio client with SID: {account_sid}, Token: {auth_token[:10]}... (len={len(auth_token)})")
    return Client(account_sid, auth_token)

# Load AVA system prompt
def load_ava_prompt():
    """Load the Munster assistant system prompt from file."""
    possible_paths = [
        "munster-assistant-prompt.txt",
        os.path.join(os.path.dirname(__file__), "munster-assistant-prompt.txt"),
        "/Users/egj/Desktop/pipecat/examples/phone-chatbot/daily-twilio-sip-dial-in/munster-assistant-prompt.txt",
    ]
    
    for file_path in possible_paths:
        try:
            logger.info(f"Trying to load prompt from: {file_path}")
            with open(file_path, "r") as f:
                prompt = f.read()
                logger.info(f"Successfully loaded Munster prompt from {file_path}, length: {len(prompt)}")
                return prompt
        except FileNotFoundError:
            logger.warning(f"File not found: {file_path}")
            continue
        except Exception as e:
            logger.error(f"Error loading prompt from {file_path}: {e}")
            continue
    
    logger.error("munster-assistant-prompt.txt not found in any expected location")
    logger.error(f"Current working directory: {os.getcwd()}")
    logger.error(f"Script directory: {os.path.dirname(__file__)}")
    
    return "You are the AI receptionist for Munster Primary Care PC. You help patients schedule, reschedule, and cancel appointments. You are professional, compassionate, and HIPAA compliant."

# Define function schemas for AVA
def create_ava_function_schemas():
    """Create function schemas for AVA's calendar management tools."""
    # ... existing schema definitions ...
    list_event_schema = FunctionSchema(
        name="list_event",
        description="Find existing appointments or check for general availability",
        properties={
            "search_query": {
                "type": "string",
                "description": "Patient's full name to find their existing appointments."
            },
            "patient_birthday": {
                "type": "string",
                "description": "Patient's date of birth (YYYY-MM-DD) for verification."
            },
            "time_min_str": {
                "type": "string",
                "description": "The start of the time window to check (ISO 8601 format)."
            },
            "time_max_str": {
                "type": "string",
                "description": "The end of the time window to check (ISO 8601 format)."
            }
        },
        required=["time_min_str", "time_max_str"]
    )

    create_new_event_schema = FunctionSchema(
        name="create_event",
        description="Schedule a new appointment",
        properties={
            "patient_name": {"type": "string"},
            "patient_birthday": {"type": "string"},
            "appointment_reason": {"type": "string"},
            "start_time_str": {"type": "string"},
            "end_time_str": {"type": "string"},
            "conversation_summary": {"type": "string"}
        },
        required=["patient_name", "patient_birthday", "appointment_reason", "start_time_str", "end_time_str", "conversation_summary"]
    )

    cancel_event_schema = FunctionSchema(
        name="cancel_event",
        description="Cancel an existing appointment",
        properties={
            "event_id": {"type": "string"},
            "patient_birthday": {"type": "string"}
        },
        required=["event_id", "patient_birthday"]
    )

    reschedule_event_schema = FunctionSchema(
        name="reschedule_event",
        description="Reschedule an existing appointment",
        properties={
            "event_id": {"type": "string"},
            "patient_birthday": {"type": "string"},
            "new_start_time_str": {"type": "string"},
            "new_duration_minutes": {"type": "integer"}
        },
        required=["event_id", "patient_birthday", "new_start_time_str"]
    )

    check_insurance_schema = FunctionSchema(
        name="check_insurance",
        description="Check if a specific insurance plan is accepted",
        properties={
            "insurance_provider_name": {
                "type": "string",
                "description": "The name of the insurance provider to check."
            }
        },
        required=["insurance_provider_name"]
    )

    send_sms_schema = FunctionSchema(
        name="send_sms",
        description="Send an SMS confirmation or notification",
        properties={
            "patient_birthday": {
                "type": "string",
                "description": "Patient's date of birth (YYYY-MM-DD) for verification."
            },
            "event_id": {
                "type": "string",
                "description": "The unique ID of the relevant appointment for the message."
            },
            "message_type": {
                "type": "string",
                "enum": ["confirmation", "cancellation", "reschedule_confirmation"],
                "description": "The type of message to send."
            }
        },
        required=["patient_birthday", "event_id", "message_type"]
    )

    return ToolsSchema(standard_tools=[
        list_event_schema,
        create_new_event_schema,
        cancel_event_schema,
        reschedule_event_schema,
        check_insurance_schema,
        send_sms_schema
    ])

# Function implementations for AVA
async def ava_list_event(params: FunctionCallParams):
    """AVA's list_event function implementation."""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "list_event",
                "params": params.arguments
            }
        )
        
        list_input = ListEventsInput(
            time_min_str=params.arguments.get("time_min_str"),
            time_max_str=params.arguments.get("time_max_str"),
            search_query=params.arguments.get("search_query"),
            patient_birthday=params.arguments.get("patient_birthday")
        )
        
        result = list_event(list_input, "ava-session")
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "list_event",
                "result": result
            }
        )
        
        await params.result_callback(result)
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "list_event",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error checking calendar: {str(e)}")

async def ava_create_new_event(params: FunctionCallParams):
    """AVA's create_new_event function implementation."""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "create_event",
                "params": params.arguments
            }
        )
        
        event_input = CalendarEventInput(
            patient_name=params.arguments["patient_name"],
            appointment_reason=params.arguments["appointment_reason"],
            start_time_str=params.arguments["start_time_str"],
            end_time_str=params.arguments["end_time_str"],
            patient_birthday=params.arguments["patient_birthday"],
            conversation_summary=params.arguments["conversation_summary"]
        )
        
        result = create_event(event_input, "ava-session")
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "create_event",
                "result": result
            }
        )
        
        await params.result_callback(result["message"])
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "create_event",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error creating appointment: {str(e)}")

async def ava_cancel_event(params: FunctionCallParams):
    """AVA's cancel_event function implementation."""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "cancel_event",
                "params": params.arguments
            }
        )
        
        cancel_input = CancelEventInput(
            event_id=params.arguments["event_id"],
            patient_birthday=params.arguments["patient_birthday"]
        )
        
        result = cancel_event(cancel_input, "ava-session")
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "cancel_event",
                "result": result
            }
        )
        
        await params.result_callback(result["message"])
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "cancel_event",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error canceling appointment: {str(e)}")

async def ava_reschedule_event(params: FunctionCallParams):
    """AVA's reschedule_event function implementation."""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "reschedule_event",
                "params": params.arguments
            }
        )
        
        reschedule_input = RescheduleEventInput(
            event_id=params.arguments["event_id"],
            patient_birthday=params.arguments["patient_birthday"],
            new_start_time_str=params.arguments["new_start_time_str"],
            new_duration_minutes=params.arguments.get("new_duration_minutes", 30)
        )
        
        result = reschedule_event(reschedule_input, "ava-session")
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "reschedule_event",
                "result": result
            }
        )
        
        await params.result_callback(result["message"])
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "reschedule_event",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error rescheduling appointment: {str(e)}")

async def ava_check_insurance(params: FunctionCallParams):
    """AVA's check_insurance function implementation"""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "check_insurance",
                "params": params.arguments
            }
        )
        
        provider = params.arguments["insurance_provider_name"].lower()
        
        # Hardcoded insurance list (you can expand this)
        accepted_insurances = [
            "blue cross", "blue shield", "aetna", "cigna", "unitedhealth", 
            "medicare", "medicaid", "humana", "kaiser"
        ]
        
        is_accepted = any(accepted in provider for accepted in accepted_insurances)
        result = {
            "insurance_provider": params.arguments["insurance_provider_name"],
            "is_accepted": is_accepted
        }
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "check_insurance",
                "result": result
            }
        )
        
        await params.result_callback(result)
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "check_insurance",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error checking insurance: {str(e)}")

async def ava_send_sms(params: FunctionCallParams):
    """AVA's send_sms function implementation."""
    try:
        # Log function call start
        langfuse.log(
            name="function_call_start",
            level="info",
            metadata={
                "function": "send_sms",
                "params": params.arguments
            }
        )
        
        sms_input = SendSMSInput(
            message_type=params.arguments["message_type"],
            event_details={"event_id": params.arguments["event_id"]},
            custom_message="Your appointment has been confirmed."
        )
        
        result = send_sms(sms_input, "ava-session")
        
        # Log function call success
        langfuse.log(
            name="function_call_success",
            level="info",
            metadata={
                "function": "send_sms",
                "result": result
            }
        )
        
        await params.result_callback(result["message"])
    except Exception as e:
        # Log function call error
        langfuse.log(
            name="function_call_error",
            level="error",
            metadata={
                "function": "send_sms",
                "error": str(e),
                "params": params.arguments
            }
        )
        await params.result_callback(f"Error sending SMS: {str(e)}")

async def run_ava_bot(room_url: str, token: str, call_id: str, sip_uri: str) -> None:
    """Run the AVA voice bot with the given parameters."""
    
    # Log the start of the bot session
    langfuse.log(
        name="bot_session_start",
        level="info",
        metadata={
            "call_id": call_id,
            "room_url": room_url,
            "sip_uri": sip_uri
        }
    )
    
    logger.info(f"Starting AVA bot with room: {room_url}")
    logger.info(f"SIP endpoint: {sip_uri}")

    call_already_forwarded = False

    # Setup the Daily transport
    transport = DailyTransport(
        room_url,
        token,
        "AVA - Munster Primary Care",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # Setup STT service (Cartesia)
    stt = CartesiaSTTService(
        api_key=os.getenv("CARTESIA_API_KEY"),
    )

    # Setup TTS service (Cartesia)
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="1242fb95-7ddd-44ac-8a05-9e8a22a6137d",  # RECEPTIONIST
    )
    
    # Setup LLM service (OPENAI)
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    # Register AVA's functions
    llm.register_function("list_event", ava_list_event)
    llm.register_function("create_event", ava_create_new_event)
    llm.register_function("cancel_event", ava_cancel_event)
    llm.register_function("reschedule_event", ava_reschedule_event)
    llm.register_function("check_insurance", ava_check_insurance)
    llm.register_function("send_sms", ava_send_sms)

    # Load AVA system prompt and add current date
    ava_prompt = load_ava_prompt()
    central_tz = pytz.timezone('America/Chicago')
    current_time = datetime.now(central_tz)
    current_date_str = current_time.strftime("%A, %B %d, %Y, %I:%M %p")
    
    # Replace the date placeholder in the prompt
    ava_prompt = ava_prompt.replace('`{{"now" | date: "%A, %B %d, %Y, %I:%M %p", "America/Chicago"}}`', current_date_str)
    
    logger.info(f"Final AVA prompt length: {len(ava_prompt)}")
    logger.info(f"AVA prompt starts with: {ava_prompt[:200]}...")
    logger.info(f"AVA prompt contains 'Munster Primary Care': {'Munster Primary Care' in ava_prompt}")
    logger.info(f"AVA prompt contains 'Dr. Asif Farooqui': {'Dr. Asif Farooqui' in ava_prompt}")

    # Create function schemas
    tools = create_ava_function_schemas()

    # Initialize LLM context with AVA system prompt and tools
    messages = [
    {
        "role": "system",
        "content": ava_prompt,
    },
    {
        "role": "assistant",
        "content": "Hello! I'm Ava, your medical receptionist at Munster Primary Care. How can I help you today?"
    },
]

    # Setup the conversational context with tools
    context = OpenAILLMContext(messages, tools=tools)
    context_aggregator = llm.create_context_aggregator(context)

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,  # Cartesia STT
            context_aggregator.user(),
            llm,  # OPENAI LLM
            tts,  # Cartesia TTS
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # Create the pipeline task
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # Handle participant joining
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info(f"First participant joined: {participant['id']}")
        
        # Log participant joined event
        langfuse.log(
            name="participant_joined",
            level="info",
            metadata={
                "participant_id": participant["id"],
                "call_id": call_id
            }
        )
        
        await transport.capture_participant_transcription(participant["id"])
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    # Handle participant leaving
    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']}, reason: {reason}")
        
        # Log participant left event
        langfuse.log(
            name="participant_left",
            level="info",
            metadata={
                "participant_id": participant["id"],
                "reason": reason,
                "call_id": call_id
            }
        )
        
        await task.cancel()

    # Handle call ready to forward
    @transport.event_handler("on_dialin_ready")
    async def on_dialin_ready(transport, cdata):
        nonlocal call_already_forwarded

        if call_already_forwarded:
            logger.warning("Call already forwarded, ignoring this event.")
            return

        logger.info(f"Forwarding call {call_id} to {sip_uri}")

        try:
            twilio_client = get_twilio_client()
            twilio_client.calls(call_id).update(
                twiml=f"<Response><Dial><Sip>{sip_uri}</Sip></Dial></Response>"
            )
            logger.info("Call forwarded successfully")
            
            # Log successful call forwarding
            langfuse.log(
                name="call_forwarded",
                level="info",
                metadata={
                    "call_id": call_id,
                    "sip_uri": sip_uri
                }
            )
            
            call_already_forwarded = True
        except Exception as e:
            logger.error(f"Failed to forward call: {str(e)}")
            
            # Log call forwarding error
            langfuse.log(
                name="call_forward_error",
                level="error",
                metadata={
                    "call_id": call_id,
                    "sip_uri": sip_uri,
                    "error": str(e)
                }
            )
            
            raise

    @transport.event_handler("on_dialin_connected")
    async def on_dialin_connected(transport, data):
        """Handle dial-in connected event"""
        logger.debug(f"Dial-in connected: {data}")
        
        # Log dial-in connected event
        langfuse.log(
            name="dialin_connected",
            level="info",
            metadata={
                "call_id": call_id,
                "data": data
            }
        )

    @transport.event_handler("on_dialin_stopped")
    async def on_dialin_stopped(transport, data):
        """Handle dial-in stopped event"""
        logger.debug(f"Dial-in stopped: {data}")
        
        # Log dial-in stopped event
        langfuse.log(
            name="dialin_stopped",
            level="info",
            metadata={
                "call_id": call_id,
                "data": data
            }
        )

    @transport.event_handler("on_dialin_error")
    async def on_dialin_error(transport, data):
        """Handle dial-in error event"""
        logger.error(f"Dial-in error: {data}")
        
        # Log dial-in error event
        langfuse.log(
            name="dialin_error",
            level="error",
            metadata={
                "call_id": call_id,
                "data": data
            }
        )

    @transport.event_handler("on_dialin_warning")
    async def on_dialin_warning(transport, data):
        """Handle dial-in warning event"""
        logger.warning(f"Dial-in warning: {data}")
        
        # Log dial-in warning event
        langfuse.log(
            name="dialin_warning",
            level="warning",
            metadata={
                "call_id": call_id,
                "data": data
            }
        )

    # Run the pipeline
    runner = PipelineRunner()
    await runner.run(task)
    
    # Log the end of the bot session
    langfuse.log(
        name="bot_session_end",
        level="info",
        metadata={
            "call_id": call_id
        }
    )

async def main():
    """Main entry point for the AVA bot application."""
    
    # Log application start
    langfuse.log(
        name="application_start",
        level="info",
        metadata={
            "version": "1.0.0",
            "environment": os.getenv("ENVIRONMENT", "development")
        }
    )
    
    parser = argparse.ArgumentParser(description="AVA - Munster Primary Care Voice Bot")
    parser.add_argument("-u", type=str, required=True, help="Daily room URL")
    parser.add_argument("-t", type=str, required=True, help="Daily room token")
    parser.add_argument("-i", type=str, required=True, help="Twilio call ID")
    parser.add_argument("-s", type=str, required=True, help="Daily SIP URI")

    args = parser.parse_args()

    if not all([args.u, args.t, args.i, args.s]):
        logger.error("All arguments (-u, -t, -i, -s) are required")
        parser.print_help()
        sys.exit(1)

    await run_ava_bot(args.u, args.t, args.i, args.s)

if __name__ == "__main__":
    asyncio.run(main())