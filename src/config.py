# src/config.py
import os
import json
import logging
from typing import List, Optional

# --- Environment Loading ---
# Check if running in Azure Functions (indicated by WEBSITE_INSTANCE_ID)
# or locally (using local.settings.json)
IS_AZURE_ENVIRONMENT = os.environ.get('WEBSITE_INSTANCE_ID') is not None

_settings = {}
if not IS_AZURE_ENVIRONMENT:
    # Load local settings from JSON file relative to project root
    settings_path = os.path.join(os.path.dirname(__file__), '..', 'local.settings.json')
    print(f"Attempting to load local settings from: {os.path.abspath(settings_path)}")
    if os.path.exists(settings_path):
        with open(settings_path, 'r') as f:
            try:
                local_settings = json.load(f)
                _settings = local_settings.get('Values', {})
                print("Successfully loaded local settings.")
            except json.JSONDecodeError as e:
                print(f"Error decoding local.settings.json: {e}. Please ensure it's valid JSON.")
                _settings = {} # Reset to empty if decode fails
            except Exception as e:
                print(f"An unexpected error occurred loading local.settings.json: {e}")
                _settings = {}
    else:
        print(f"Warning: local.settings.json not found at {os.path.abspath(settings_path)}. Using environment variables only.")

def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Gets a setting from environment variables or local settings."""
    # Prioritize environment variables (common in Azure)
    value = os.environ.get(name)
    if value is not None:
        return value
    # Fallback to local settings if not in Azure environment
    if not IS_AZURE_ENVIRONMENT:
        return _settings.get(name, default)
    # Return default if not found anywhere
    return default

# --- Configuration Values ---
LOG_LEVEL_STR = get_setting('LOG_LEVEL', 'INFO').upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

OPENAI_API_KEY: Optional[str] = get_setting('OPENAI_API_KEY')
SUMMARIZATION_MODEL: str = get_setting('SUMMARIZATION_MODEL', 'gpt-4o')
AUDIO_TTS_MODEL: str = get_setting('AUDIO_TTS_MODEL', 'tts-1')
AUDIO_TTS_VOICE: str = get_setting('AUDIO_TTS_VOICE', 'alloy')

AZURE_STORAGE_CONNECTION_STRING: Optional[str] = get_setting('AZURE_STORAGE_CONNECTION_STRING')
AZURE_STORAGE_CONTAINER_NAME: Optional[str] = get_setting('AZURE_STORAGE_CONTAINER_NAME', 'podcast-audio') # Placeholder name

TARGET_EMAIL_ADDRESS: Optional[str] = get_setting('TARGET_EMAIL_ADDRESS')

# Gmail paths are relative to the function app root directory where __init__.py resides
# When running locally, this might mean './src/credentials.json',
# When deployed, Azure Functions mounts the code usually at /home/site/wwwroot/
# We assume the src folder contents are deployed directly into the function root
GMAIL_CREDENTIALS_PATH: str = get_setting('GMAIL_CREDENTIALS_PATH', 'credentials.json')
GMAIL_TOKEN_PATH: str = get_setting('GMAIL_TOKEN_PATH', 'token.json')

EMAIL_SOURCES: List[str] = [
    "noreply@news.bloomberg.com", "access@interactive.wsj.com",
    "email@stratechery.com", "nytdirect@nytimes.com",
    "crew@morningbrew.com", "richardhanania+hanpod@substack.com",
    "pragmaticengineer@substack.com", "hello@worddaily.com",
    "hello@historyfacts.com", "astralcodexten@substack.com",
    "hello@snacks.robinhood.com", "richardhanania+nls@substack.com",
    "citrini@substack.com"
]

# Podcast Generation Settings
PODCAST_MIN_DURATION_MINS: int = 30
PODCAST_MAX_DURATION_MINS: int = 90
# Estimated words per minute for TTS voice (adjust based on testing)
PODCAST_WORDS_PER_MINUTE: int = 150

# --- Sanity Checks ---
REQUIRED_SETTINGS = [
    'OPENAI_API_KEY',
    'AZURE_STORAGE_CONNECTION_STRING',
    'AZURE_STORAGE_CONTAINER_NAME',
    'TARGET_EMAIL_ADDRESS'
]

missing_settings = [
    setting for setting in REQUIRED_SETTINGS if not globals().get(setting)
]

if missing_settings:
    logging.warning(f"Missing critical configuration settings: {', '.join(missing_settings)}. "
                    f"Check environment variables or local.settings.json.")

# Ensure paths exist for local development (won't run in Azure deployment context)
if not IS_AZURE_ENVIRONMENT:
    if not os.path.exists(GMAIL_CREDENTIALS_PATH):
        logging.warning(f"Gmail credentials file not found at resolved path: {os.path.abspath(GMAIL_CREDENTIALS_PATH)}")
    if not os.path.exists(GMAIL_TOKEN_PATH):
        logging.warning(f"Gmail token file not found at resolved path: {os.path.abspath(GMAIL_TOKEN_PATH)}")

# --- Logging Setup ---
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Silence overly verbose loggers if needed
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)

# Log loaded values (excluding secrets) for verification
logging.info("Configuration loaded.")
logging.info(f"IS_AZURE_ENVIRONMENT: {IS_AZURE_ENVIRONMENT}")
logging.info(f"Log Level: {LOG_LEVEL_STR}")
logging.info(f"Summarization Model: {SUMMARIZATION_MODEL}")
logging.info(f"TTS Model: {AUDIO_TTS_MODEL}, Voice: {AUDIO_TTS_VOICE}")
logging.info(f"Target Email: {TARGET_EMAIL_ADDRESS}")
logging.info(f"Azure Container Name: {AZURE_STORAGE_CONTAINER_NAME}")
logging.info(f"Email Sources Count: {len(EMAIL_SOURCES)}")
logging.info(f"Resolved Gmail Credentials Path: {os.path.abspath(GMAIL_CREDENTIALS_PATH)}")
logging.info(f"Resolved Gmail Token Path: {os.path.abspath(GMAIL_TOKEN_PATH)}")
if missing_settings:
     logging.error(f"CRITICAL: Missing settings prevent proper operation: {missing_settings}")