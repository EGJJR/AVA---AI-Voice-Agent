import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

# --- Configuration ---
CLIENT_SECRETS_FILE = 'client_secret.json'
# This scope allows read/write access to calendars.
# Ensure it matches the scopes required by your application.
SCOPES = ['https://www.googleapis.com/auth/calendar']

def generate_token():
    """
    Runs an interactive OAuth 2.0 flow to generate and print user credentials.
    """
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"ERROR: Client secrets file not found at '{CLIENT_SECRETS_FILE}'")
        print("Please download your credentials from the Google Cloud Console and save them as 'client_secret.json' in the same directory as this script.")
        return

    try:
        # Creates a flow instance to manage the OAuth 2.0 Authorization Flow
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        
        # Run the local server to handle the authentication flow.
        # This will open a new browser window for the user to log in and authorize the app.
        print("Starting local server for Google OAuth flow...")
        print("Your browser should open automatically. If not, please open the URL provided in the console.")
        credentials = flow.run_local_server(port=0)
        
        # Convert the credentials to a JSON string
        creds_json = credentials.to_json()
        
        print("\n" + "="*80)
        print("✅ Authentication Successful!")
        print("="*80)
        print("\nCopy the following JSON and set it as the value for the")
        print("'GOOGLE_OAUTH_TOKEN' environment variable in your AWS Lambda function.\n")
        
        # Print the JSON credentials
        print(creds_json)
        
        print("\n" + "="*80)
        print("\nIMPORTANT: Treat this token like a password. Do not share it or commit it to version control.")
        print("="*80)

    except FileNotFoundError:
        print(f"Error: The client secrets file '{CLIENT_SECRETS_FILE}' was not found.")
    except Exception as e:
        print(f"\nAn error occurred during the authentication process: {e}")
        print("Please ensure your Google Cloud project is configured correctly for OAuth 2.0.")

if __name__ == '__main__':
    generate_token() 