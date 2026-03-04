# Pipecat – AVA Voice Receptionist

AVA is an AI voice receptionist for Munster Primary Care, built with [Pipecat](https://github.com/pipecat-ai/pipecat). It handles incoming calls via Twilio, runs the conversation in Daily.co rooms, and can schedule, reschedule, and cancel calendar events (Google Calendar) and send SMS/WhatsApp confirmations. Backend uses Supabase; LLM can be OpenAI or AWS Bedrock.

## Project layout

- **`pipecat-v3-lambda-v2/pipecat-v3/`** – Main app: FastAPI webhook server (`server.py`), voice bot (`bot.py`), calendar/SMS tools, and optional Lambda entrypoint (`index.py`).
- **`google-calendar-agent/`** – Google Calendar OAuth and config (e.g. `client_secret.json`, token storage).
- **`pipecat-deployment/`** – Deployment-related config (e.g. Daily/Twilio SIP).

## Requirements

- Python 3.11+
- Twilio account (voice + optional WhatsApp)
- Daily.co account
- Google Cloud project with Calendar API and OAuth client
- Supabase project
- LLM: OpenAI API key and/or AWS Bedrock
- Cartesia API key (TTS/STT)

## Setup

1. **Clone and enter the app directory**
   ```bash
   cd pipecat-v3-lambda-v2/pipecat-v3
   ```

2. **Create a virtualenv and install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   ```

3. **Configure environment**
   - Copy `pipecat-v3-lambda-v2/pipecat-v3/.env.example` to `.env`.
   - Fill in all required keys (Twilio, Daily, Supabase, Cartesia, OpenAI or AWS Bedrock, optional Langfuse).
   - For Google Calendar: place your OAuth client secret as `client_secret.json` in the same directory (or path set by `GOOGLE_CLIENT_SECRET_FILE`), then run the OAuth flow (e.g. `generate_oauth_token.py`) once to obtain tokens.

4. **Google Calendar OAuth (first time)**
   - Ensure `client_secret.json` is in the app directory.
   - Run the token generation script and complete the browser flow so that tokens are stored for the bot.

## Running locally

- **Webhook server (for Twilio callbacks)**  
  From `pipecat-v3-lambda-v2/pipecat-v3/`:
  ```bash
  python server.py
  ```
  Set Twilio voice webhook URL to `https://<your-host>/start` (use ngrok or similar for local dev).

- **Bot only (e.g. for testing with a Daily room URL)**  
  ```bash
  python bot.py -u <daily_room_url> -t <daily_token> -i <call_sid> -s <sip_endpoint>
  ```

## Environment variables

See `pipecat-v3-lambda-v2/pipecat-v3/.env.example` for the full list. Main ones:

| Variable | Purpose |
|----------|---------|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio voice (and optional WhatsApp) |
| `DAILY_API_KEY`, `DAILY_API_URL` | Daily.co rooms and SIP |
| `OPENAI_API_KEY` or AWS Bedrock vars | LLM |
| `CARTESIA_API_KEY` | TTS/STT |
| `SUPABASE_URL`, `SUPABASE_KEY` | Database |
| `GOOGLE_CLIENT_SECRET_FILE` | Path to Google OAuth client secret JSON |
| `LANGFUSE_*` | Optional tracing (Langfuse) |

**Do not commit `.env` or `client_secret.json` or token files.** Use `.env.example` as a template.

## License

Use and modify as needed for your organization. Check dependencies (Pipecat, Twilio, Daily, etc.) for their respective terms.
