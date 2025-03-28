# src/config.py
import os
import json
import logging
from typing import List, Optional

# --- Environment Loading ---
IS_AZURE_ENVIRONMENT = os.environ.get('WEBSITE_INSTANCE_ID') is not None

_settings = {}
if not IS_AZURE_ENVIRONMENT:
    settings_path = os.path.join(os.path.dirname(__file__), '..', 'local.settings.json')
    if os.path.exists(settings_path):
        with open(settings_path, 'r') as f:
            try:
                local_settings = json.load(f)
                _settings = local_settings.get('Values', {})
                print(f"Successfully loaded local settings from {os.path.abspath(settings_path)}")
            except json.JSONDecodeError as e:
                print(f"Error decoding local.settings.json: {e}. Please ensure it's valid JSON.")
                _settings = {}
            except Exception as e:
                print(f"An unexpected error occurred loading local.settings.json: {e}")
                _settings = {}
    else:
        print(f"Warning: local.settings.json not found at {os.path.abspath(settings_path)}. Using environment variables only.")

def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Gets a setting from environment variables or local settings."""
    value = os.environ.get(name)
    if value is not None:
        return value
    if not IS_AZURE_ENVIRONMENT:
        return _settings.get(name, default)
    return default

# --- Configuration Values ---
LOG_LEVEL_STR = get_setting('LOG_LEVEL', 'INFO').upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

OPENAI_API_KEY: Optional[str] = get_setting('OPENAI_API_KEY')
# Default to gpt-4o-mini as requested, but allow override via settings
SUMMARIZATION_MODEL: str = get_setting('SUMMARIZATION_MODEL', 'gpt-4o-mini')
AUDIO_TTS_MODEL: str = get_setting('AUDIO_TTS_MODEL', 'tts-1')
# --- CHANGE 4: Update Default Voice ---
AUDIO_TTS_VOICE: str = get_setting('AUDIO_TTS_VOICE', 'shimmer') # Default changed to shimmer
# --- END CHANGE ---

AZURE_STORAGE_CONNECTION_STRING: Optional[str] = get_setting('AZURE_STORAGE_CONNECTION_STRING')
AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = None # Attempt to parse from connection string if needed elsewhere
if AZURE_STORAGE_CONNECTION_STRING:
     try:
         # Simple parsing, might fail on more complex strings (e.g., emulator)
         parts = {p.split('=', 1)[0].lower(): p.split('=', 1)[1] for p in AZURE_STORAGE_CONNECTION_STRING.split(';') if '=' in p}
         AZURE_STORAGE_ACCOUNT_NAME = parts.get('accountname')
     except Exception:
         logging.warning("Could not parse AccountName from Azure Storage Connection String.")

AZURE_STORAGE_CONTAINER_NAME: Optional[str] = get_setting('AZURE_STORAGE_CONTAINER_NAME', 'podcast-audio')

TARGET_EMAIL_ADDRESS: Optional[str] = get_setting('TARGET_EMAIL_ADDRESS')

# --- CHANGE: Adjust paths based on whether running locally ('func start' from root) or deployed
# In Azure, files are usually in /home/site/wwwroot/. Assume deployment flattens src/.
if IS_AZURE_ENVIRONMENT:
     GMAIL_CREDENTIALS_PATH: str = get_setting('GMAIL_CREDENTIALS_PATH', 'credentials.json')
     GMAIL_TOKEN_PATH: str = get_setting('GMAIL_TOKEN_PATH', 'token.json')
else:
     # When running locally, assume 'func start' is run from project root
     # Paths are relative to project root where function_app.py lives
     GMAIL_CREDENTIALS_PATH: str = get_setting('GMAIL_CREDENTIALS_PATH', 'src/credentials.json')
     GMAIL_TOKEN_PATH: str = get_setting('GMAIL_TOKEN_PATH', 'src/token.json')


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
PODCAST_WORDS_PER_MINUTE: int = 150 # Estimated WPM for TTS voice

# --- Sanity Checks ---
REQUIRED_SETTINGS = [
    'OPENAI_API_KEY',
    'AZURE_STORAGE_CONNECTION_STRING',
    'AZURE_STORAGE_CONTAINER_NAME',
    'TARGET_EMAIL_ADDRESS'
]

missing_settings = [
    setting for setting in REQUIRED_SETTINGS if not globals().get(setting) and not get_setting(setting) # Check both globals and get_setting
]

# Check file paths specifically for local development
if not IS_AZURE_ENVIRONMENT:
    if not os.path.exists(GMAIL_CREDENTIALS_PATH):
        missing_settings.append(f"GMAIL_CREDENTIALS_PATH ({GMAIL_CREDENTIALS_PATH})")
    if not os.path.exists(GMAIL_TOKEN_PATH):
        missing_settings.append(f"GMAIL_TOKEN_PATH ({GMAIL_TOKEN_PATH})")


# --- Logging Setup ---
# Remove existing handlers to avoid duplication if module is reloaded
root_logger = logging.getLogger()
if root_logger.hasHandlers():
    root_logger.handlers.clear()

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Silence overly verbose loggers
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
logging.getLogger('azure.core.pipeline.policies').setLevel(logging.WARNING) # Quieten Azure SDK noise

# Log loaded values (excluding secrets) for verification
logging.info("--- Configuration Loaded ---")
logging.info(f"Azure Environment: {IS_AZURE_ENVIRONMENT}")
logging.info(f"Log Level: {LOG_LEVEL_STR}")
logging.info(f"Summarization Model: {SUMMARIZATION_MODEL}")
logging.info(f"TTS Model: {AUDIO_TTS_MODEL}, Voice: {AUDIO_TTS_VOICE}")
logging.info(f"Target Email: {TARGET_EMAIL_ADDRESS}")
logging.info(f"Azure Account Name: {AZURE_STORAGE_ACCOUNT_NAME}")
logging.info(f"Azure Container Name: {AZURE_STORAGE_CONTAINER_NAME}")
logging.info(f"Email Sources Count: {len(EMAIL_SOURCES)}")
logging.info(f"Resolved Gmail Credentials Path: {os.path.abspath(GMAIL_CREDENTIALS_PATH)}")
logging.info(f"Resolved Gmail Token Path: {os.path.abspath(GMAIL_TOKEN_PATH)}")
logging.info("---------------------------")

if missing_settings:
     logging.error(f"CRITICAL: Missing configuration settings prevent proper operation: {', '.join(missing_settings)}")
     # You might want to raise an error here in production if certain settings are absolutely required
     # raise ValueError(f"Missing critical configuration settings: {', '.join(missing_settings)}")