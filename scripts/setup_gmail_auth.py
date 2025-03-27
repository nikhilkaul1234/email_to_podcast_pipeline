import os.path
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# --- Configuration ---
# Define the scopes needed.
# readonly: To read emails from specified sources.
# send: To send the notification email with the podcast link.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]
# Path to the credentials file downloaded from Google Cloud Console.
# Assumes the script is run from the project root directory.
CREDENTIALS_PATH = 'src/credentials.json'
# Path where the generated token file will be stored.
# Assumes the script is run from the project root directory.
TOKEN_PATH = 'src/token.json'
# --- End Configuration ---

def main():
    """
    Runs the OAuth 2.0 flow to generate the token.json file for Gmail API access.
    """
    creds = None

    # Check if token.json already exists
    if os.path.exists(TOKEN_PATH):
        print(f"Token file already exists at '{TOKEN_PATH}'.")
        try:
            # Try loading existing credentials to see if they are valid/refreshable
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            # Check if credentials are valid and refresh if necessary
            if creds and creds.expired and creds.refresh_token:
                print("Credentials expired, attempting to refresh...")
                creds.refresh(Request())
                print("Credentials refreshed successfully.")
                 # Save the potentially updated credentials
                with open(TOKEN_PATH, 'w') as token_file:
                    token_file.write(creds.to_json())
                print(f"Refreshed token saved to '{TOKEN_PATH}'.")
                return # Exit if refresh was successful
            elif creds and creds.valid:
                 print("Existing token is still valid.")
                 # Optionally ask user if they want to re-authenticate anyway
                 reauth = input("Do you want to re-authenticate anyway? (yes/No): ").lower()
                 if reauth != 'yes':
                     print("Exiting without re-authentication.")
                     return

        except Exception as e:
            print(f"Error loading or refreshing existing token: {e}")
            print("Proceeding with re-authentication.")
            creds = None # Force re-authentication

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if not os.path.exists(CREDENTIALS_PATH):
            print(f"ERROR: Credentials file not found at '{CREDENTIALS_PATH}'")
            print("Please download your OAuth 2.0 Client ID credentials from")
            print("Google Cloud Console and save it as 'src/credentials.json'.")
            sys.exit(1)

        try:
            # Create the flow using the credentials file and defined scopes
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)

            # Run the authorization flow. This will open a browser window
            # for the user to grant permission.
            # port=0 means it will find an available port automatically.
            print("\nStarting authentication flow...")
            print("Your browser should open shortly to ask for authorization.")
            print("Please select the Gmail account you want this tool to access.")
            creds = flow.run_local_server(port=0)

        except Exception as e:
            print(f"\nError during authentication flow: {e}")
            print("Please ensure you have enabled the Gmail API in Google Cloud Console")
            print("and that the credentials.json file is correct.")
            sys.exit(1)

        # Save the credentials for the next run
        try:
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
            print(f"\nAuthentication successful! Token saved to '{TOKEN_PATH}'")
            print("\nIMPORTANT: Add 'src/token.json' to your .gitignore file if you haven't already!")
            print("NEVER commit this file to version control.")

        except Exception as e:
            print(f"Error saving token file to '{TOKEN_PATH}': {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()