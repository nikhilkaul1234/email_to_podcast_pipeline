# src/email_client.py

import base64
import logging
import os.path
import re
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import config # Use relative import within the 'src' package

logger = logging.getLogger(__name__)

# Define the scopes needed (must match setup_gmail_auth.py)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]

def _get_gmail_service():
    """Authenticates and builds the Gmail service object."""
    creds = None
    # Adjust paths relative to the current file if needed, or rely on config resolution
    token_path = config.GMAIL_TOKEN_PATH
    creds_path = config.GMAIL_CREDENTIALS_PATH

    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logger.error(f"Failed to load token file from {token_path}: {e}")

    # If there are no (valid) credentials available, log in or refresh.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail credentials.")
            try:
                creds.refresh(Request())
                # Save the refreshed credentials
                with open(token_path, 'w') as token_file:
                    token_file.write(creds.to_json())
                logger.info(f"Refreshed token saved to {token_path}")
            except Exception as e:
                logger.error(f"Failed to refresh Gmail token: {e}")
                # If refresh fails, we probably need manual intervention
                # In Azure Func context, re-running setup_gmail_auth.py isn't feasible
                # Raising an error might be appropriate here
                raise ConnectionError("Failed to refresh Gmail credentials.") from e
        else:
            # This block should ideally not be reached in production/Azure Function
            # It requires user interaction. Log an error if token/creds are missing/invalid.
            logger.error(f"Missing or invalid Gmail credentials. Token Path: '{token_path}', Creds Path: '{creds_path}'.")
            logger.error("Run 'scripts/setup_gmail_auth.py' locally to generate/refresh token.json.")
            # For Azure Function, ensure token.json and credentials.json are deployed and paths are correct.
            raise ConnectionError("Gmail credentials are not valid and cannot be refreshed automatically.")

    try:
        service = build('gmail', 'v1', credentials=creds)
        logger.info("Gmail service built successfully.")
        return service
    except HttpError as error:
        logger.error(f"An error occurred building Gmail service: {error}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred building Gmail service: {e}")
        raise


def find_recent_emails(service, sources: List[str], days_ago: int = 1) -> List[Dict[str, Any]]:
    """Finds emails from specified sources within the last N days."""
    if not service:
        logger.error("Gmail service object is invalid.")
        return []

    # Calculate cutoff date
    cutoff_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y/%m/%d')

    # Construct the query
    # Combine sources with OR, group them, and add date condition
    source_query = " OR ".join([f"from:{source}" for source in sources])
    query = f"({source_query}) after:{cutoff_date}"
    logger.info(f"Searching Gmail with query: {query}")

    try:
        # Call the Gmail API to list messages matching the query
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])

        if not messages:
            logger.info("No messages found matching the criteria.")
            return []
        else:
            logger.info(f"Found {len(messages)} potential messages.")
            # Return message objects which just contain id and threadId
            return messages

    except HttpError as error:
        logger.error(f"An error occurred searching messages: {error}")
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred searching messages: {e}")
        return []


def get_email_details(service, message_id: str) -> Optional[Dict[str, Any]]:
     """Gets the full details of a single email message including payload."""
     if not service:
         logger.error("Gmail service object is invalid.")
         return None
     try:
         # Get the full message content ('full' format includes payload, headers, etc.)
         message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
         return message
     except HttpError as error:
         logger.error(f"An error occurred getting message {message_id}: {error}")
         return None
     except Exception as e:
         logger.error(f"An unexpected error occurred getting message {message_id}: {e}")
         return None


def extract_email_body(message: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts plain text and HTML body from a Gmail message object.
    Handles multipart messages. Prioritizes HTML if available.
    Returns (plain_body, html_body)
    """
    payload = message.get('payload', {})
    parts = payload.get('parts', [])
    mime_type = payload.get('mimeType', '')
    body_data = payload.get('body', {}).get('data')

    plain_body = None
    html_body = None

    if 'text/plain' in mime_type and body_data:
        plain_body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
    elif 'text/html' in mime_type and body_data:
        html_body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
    elif 'multipart' in mime_type:
        for part in parts:
            part_mime_type = part.get('mimeType', '')
            part_body_data = part.get('body', {}).get('data')
            if not part_body_data:
                # Handle nested multipart messages
                nested_parts = part.get('parts', [])
                for nested_part in nested_parts:
                     nested_mime_type = nested_part.get('mimeType', '')
                     nested_body_data = nested_part.get('body', {}).get('data')
                     if nested_body_data:
                         decoded_data = base64.urlsafe_b64decode(nested_body_data).decode('utf-8', errors='replace')
                         if 'text/plain' in nested_mime_type:
                             plain_body = decoded_data
                         elif 'text/html' in nested_mime_type:
                             html_body = decoded_data
                     if plain_body and html_body: break # Found both
                continue # Move to next main part

            # Process current part
            decoded_data = base64.urlsafe_b64decode(part_body_data).decode('utf-8', errors='replace')
            if 'text/plain' in part_mime_type:
                plain_body = decoded_data
            elif 'text/html' in part_mime_type:
                html_body = decoded_data

            # Stop if we found both (or prioritize based on need)
            if plain_body and html_body:
                break

    # Simple fallback if no parts but top-level body exists (less common for complex emails)
    if not plain_body and not html_body and body_data and 'text/' in mime_type:
         decoded_data = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
         if 'text/plain' in mime_type: plain_body = decoded_data
         if 'text/html' in mime_type: html_body = decoded_data


    # Log extraction results
    if html_body:
         logger.debug(f"Extracted HTML body (len: {len(html_body)}) for message {message.get('id')}")
    elif plain_body:
         logger.debug(f"Extracted Plain text body (len: {len(plain_body)}) for message {message.get('id')}")
    else:
         logger.warning(f"Could not extract text/html or text/plain body for message {message.get('id')}")

    return plain_body, html_body


def send_email(service, to: str, subject: str, message_text: str) -> bool:
    """Sends an email using the Gmail API."""
    if not service:
        logger.error("Gmail service object is invalid.")
        return False
    try:
        message = MIMEText(message_text)
        message['to'] = to
        message['from'] = 'me' # Special value for authenticated user
        message['subject'] = subject

        # Encode the message in base64url format
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'raw': encoded_message}

        # Call the API
        send_message = service.users().messages().send(userId='me', body=create_message).execute()
        logger.info(f"Email sent successfully to {to}. Message ID: {send_message.get('id')}")
        return True

    except HttpError as error:
        logger.error(f"An error occurred sending email: {error}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred sending email: {e}")
        return False


# --- Helper to get sender from headers ---
def get_sender(message: Dict[str, Any]) -> Optional[str]:
    """Extracts the sender's email address from message headers."""
    headers = message.get('payload', {}).get('headers', [])
    for header in headers:
        if header.get('name', '').lower() == 'from':
            # Simple parsing, might need refinement for complex 'From' headers
            sender_header = header.get('value', '')
            match = re.search(r'<(.+?)>', sender_header) # Look for email in <brackets>
            if match:
                return match.group(1)
            # If no brackets, maybe it's just the email address (less common for newsletters)
            if '@' in sender_header:
                 # Could be "Display Name email@domain.com" - try splitting? Be careful.
                 # For now, return the whole value if no brackets found
                 return sender_header.strip()
    return None