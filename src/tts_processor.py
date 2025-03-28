# src/tts_processor.py

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Use try-except for OpenAI import
try:
    import openai
    from openai import OpenAI
except ImportError:
    logging.exception("OpenAI library not found. Please install with 'pip install openai'")
    raise

# Use try-except for pydub import
try:
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError
except ImportError:
     logging.exception("pydub library not found. Please install with 'pip install pydub' (and ensure ffmpeg is installed)")
     raise


from . import config

logger = logging.getLogger(__name__)

# --- OpenAI Client Initialization (Re-use or separate instance) ---
# You could potentially refactor to have a single client instance shared across modules,
# but for simplicity, we'll initialize it here too if the key exists.
_openai_client = None
if config.OPENAI_API_KEY:
    try:
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully for TTS.")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client for TTS: {e}", exc_info=True)
else:
    logger.error("OPENAI_API_KEY not found. Cannot perform TTS.")


# --- Helper Function for Duration ---
def _get_audio_duration_ms(file_path: str) -> Optional[int]:
    """Gets the duration of an audio file in milliseconds using pydub."""
    try:
        audio = AudioSegment.from_file(file_path) # Let pydub detect format
        duration_ms = len(audio)
        logger.debug(f"Duration of {Path(file_path).name}: {duration_ms} ms")
        return duration_ms
    except CouldntDecodeError:
        logger.error(f"pydub couldn't decode file (ensure ffmpeg is installed and supports format): {file_path}", exc_info=True)
    except FileNotFoundError:
         logger.error(f"Audio file not found for duration check: {file_path}")
    except Exception as e:
        logger.error(f"Error getting duration for {file_path}: {e}", exc_info=True)
    return None

# --- Core TTS Generation Function ---
def generate_speech_segment(
    text: str,
    output_filename: str, # Just the filename, not the full path yet
    output_dir: str,
    model: str = config.AUDIO_TTS_MODEL,
    voice: str = config.AUDIO_TTS_VOICE
) -> Optional[Tuple[str, int]]:
    """
    Generates a single audio speech segment using OpenAI TTS.

    Args:
        text: The text to synthesize.
        output_filename: The desired base name for the output file (e.g., "segment_1.mp3").
        output_dir: The directory to save the file in.
        model: The TTS model to use.
        voice: The voice to use.

    Returns:
        A tuple (full_audio_path, duration_ms) or None if generation fails.
    """
    if not _openai_client:
        logger.error("OpenAI client not initialized. Cannot generate speech.")
        return None
    if not text:
        logger.warning(f"Received empty text for TTS generation ({output_filename}). Skipping.")
        return None

    # Sanitize filename slightly (replace spaces, limit length if needed)
    safe_filename = "".join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in output_filename)
    # Ensure it ends with .mp3 (OpenAI TTS default format for basic usage)
    if not safe_filename.lower().endswith('.mp3'):
        safe_filename += ".mp3"

    speech_file_path = Path(output_dir) / safe_filename
    logger.info(f"Requesting TTS for '{safe_filename}' using model '{model}', voice '{voice}'.")

    try:
        # Make the API call - Stream the response directly to a file
        response = _openai_client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3" # Other formats like opus, aac, flac available
        )

        response.stream_to_file(str(speech_file_path)) # Use Path object converted to string

        logger.info(f"Successfully saved TTS audio to: {speech_file_path}")

        # Get duration
        duration_ms = _get_audio_duration_ms(str(speech_file_path))
        if duration_ms is None:
            logger.error(f"Failed to get duration for generated file: {speech_file_path}. Cannot proceed with this segment.")
            # Optionally delete the potentially corrupt file?
            # os.remove(speech_file_path)
            return None

        return str(speech_file_path), duration_ms

    except openai.APIError as e:
        logger.error(f"OpenAI API Error generating speech for '{safe_filename}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error generating speech for '{safe_filename}': {e}", exc_info=True)

    # Cleanup if error occurred before duration check
    if speech_file_path.exists():
        try:
            os.remove(speech_file_path)
            logger.debug(f"Cleaned up failed TTS file: {speech_file_path}")
        except OSError as rm_err:
            logger.error(f"Error cleaning up failed TTS file {speech_file_path}: {rm_err}")

    return None


# --- Main Orchestration Function ---
def generate_speech_segments(
    summaries: List[Dict[str, str]] # Expects [{'source': str, 'summary_text': str}]
) -> Tuple[Optional[str], List[Dict[str, any]]]:
    """
    Generates intro, outro, and speech segments for all summaries.

    Args:
        summaries: List of dictionaries with 'source' and 'summary_text'.

    Returns:
        A tuple: (path_to_temp_directory, list_of_segment_details).
        The list contains dictionaries like:
        {'source': str, 'text': str, 'audio_path': str, 'duration_ms': int}
        Returns (None, []) if major errors occur or no segments are generated.
    """
    if not _openai_client:
        logger.error("OpenAI client not initialized. Cannot generate segments.")
        return None, []

    # Create a temporary directory for this run's audio segments
    # This directory should be cleaned up by the caller (function_app.py)
    try:
        # Prefix with something identifiable, use mkdtemp for secure creation
        temp_dir = tempfile.mkdtemp(prefix="podcast_tts_")
        logger.info(f"Created temporary directory for audio segments: {temp_dir}")
    except Exception as e:
        logger.error(f"Failed to create temporary directory for TTS: {e}", exc_info=True)
        return None, []

    all_segments_info = []
    segment_index = 0

    # 1. Generate Intro
    intro_text = "Welcome to your daily email digest."
    intro_result = generate_speech_segment(
        text=intro_text,
        output_filename=f"{segment_index:03d}_intro.mp3",
        output_dir=temp_dir
    )
    if intro_result:
        path, duration = intro_result
        all_segments_info.append({
            'source': 'Intro', 'text': intro_text, 'audio_path': path, 'duration_ms': duration
        })
        segment_index += 1
    else:
        logger.warning("Failed to generate intro segment.")
        # Proceed without intro? Or fail? Let's proceed for now.

    # 2. Generate Speech for each Summary
    for summary_item in summaries:
        source_name = summary_item['source']
        summary_text = summary_item['summary_text']

        # Add a lead-in phrase for the podcast flow
        segment_text = f"Next up, from {source_name}. {summary_text}"

        # Limit segment text length? OpenAI TTS has limits (around 4096 chars).
        # If summaries are very long, they might need splitting. For now, assume they fit.
        max_chars = 4000 # Slightly below limit
        if len(segment_text) > max_chars:
             logger.warning(f"Segment text for '{source_name}' exceeds {max_chars} chars ({len(segment_text)}). Truncating.")
             segment_text = segment_text[:max_chars]


        # Introduce slight delay between API calls to avoid rate limits?
        time.sleep(0.5) # Sleep for 500ms

        segment_result = generate_speech_segment(
            text=segment_text,
            # Create a somewhat safe filename from the source
            output_filename=f"{segment_index:03d}_{source_name[:20]}.mp3",
            output_dir=temp_dir
        )

        if segment_result:
            path, duration = segment_result
            all_segments_info.append({
                'source': source_name, 'text': segment_text, 'audio_path': path, 'duration_ms': duration
            })
            segment_index += 1
        else:
            logger.warning(f"Failed to generate TTS segment for '{source_name}'. It will be excluded.")
            # Optionally add placeholder? For now, just skip.

    # 3. Generate Outro
    outro_text = "This concludes your daily email digest."
    outro_result = generate_speech_segment(
        text=outro_text,
        output_filename=f"{segment_index:03d}_outro.mp3",
        output_dir=temp_dir
    )
    if outro_result:
        path, duration = outro_result
        all_segments_info.append({
            'source': 'Outro', 'text': outro_text, 'audio_path': path, 'duration_ms': duration
        })
        segment_index += 1
    else:
        logger.warning("Failed to generate outro segment.")

    if not all_segments_info:
        logger.error("Failed to generate any speech segments.")
        # Clean up the empty temp dir?
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass # Ignore if not empty for some reason
        return None, []

    logger.info(f"Generated {len(all_segments_info)} speech segments in {temp_dir}")
    return temp_dir, all_segments_info