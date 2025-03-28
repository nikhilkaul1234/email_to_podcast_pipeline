# src/audio_processor.py

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Use try-except for pydub import
try:
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError
except ImportError:
     logging.exception("pydub library not found. Please install with 'pip install pydub' (and ensure ffmpeg is installed)")
     raise

logger = logging.getLogger(__name__)

# Default silence between segments in milliseconds
DEFAULT_SILENCE_MS = 750


def _create_ffmpeg_metadata_file(
    chapters: List[Dict[str, any]], # Expects [{'title': str, 'start_ms': int, 'end_ms': int}]
    output_metadata_path: str,
    podcast_title: str = "Daily Email Digest"
) -> bool:
    """
    Creates a metadata file in the format required by ffmpeg for chapters.

    Format Reference: https://ffmpeg.org/ffmpeg-formats.html#Metadata-1
    """
    logger.info(f"Creating ffmpeg metadata file at: {output_metadata_path}")
    try:
        with open(output_metadata_path, 'w', encoding='utf-8') as f:
            f.write(";FFMETADATA1\n") # Header required by ffmpeg
            f.write(f"title={podcast_title}\n")
            f.write("artist=Generated Podcast Bot\n") # Optional: Add artist
            # You could add more global metadata here if desired

            f.write("\n") # Blank line separation helpful

            # TIMEBASE is crucial for chapter timing. Use milliseconds (1/1000 seconds).
            timebase_num = 1
            timebase_den = 1000
            f.write(f"[METADATA]\n") # Optional global metadata block if needed, often empty
            f.write(f"timebase={timebase_num}/{timebase_den}\n\n")


            for i, chap in enumerate(chapters):
                title = chap.get('title', f'Chapter {i+1}')
                start_ms = chap.get('start_ms', 0)
                end_ms = chap.get('end_ms', 0)

                if end_ms <= start_ms:
                    logger.warning(f"Chapter '{title}' has invalid end time ({end_ms}ms) <= start time ({start_ms}ms). Skipping.")
                    continue

                # Ensure title doesn't contain problematic characters for metadata? Basic cleaning.
                clean_title = title.replace('=', '-').replace(';', ',').replace('#', '-').replace('\\', '-').replace('\n', ' ')

                f.write("[CHAPTER]\n")
                f.write(f"TIMEBASE={timebase_num}/{timebase_den}\n")
                f.write(f"START={start_ms}\n")
                f.write(f"END={end_ms}\n")
                f.write(f"title={clean_title}\n\n")

        logger.info(f"Successfully wrote {len(chapters)} chapters to metadata file.")
        return True

    except Exception as e:
        logger.error(f"Failed to create ffmpeg metadata file: {e}", exc_info=True)
        return False


def assemble_podcast(
    segments: List[Dict[str, any]], # Expects [{'source': str, 'audio_path': str, 'duration_ms': int}]
    output_filename_base: str, # E.g., "daily_digest_2023-10-27"
    output_dir: str,
    silence_ms: int = DEFAULT_SILENCE_MS
) -> Optional[Tuple[str, List[Dict[str, any]]]]:
    """
    Concatenates audio segments, adds silence, embeds chapters using ffmpeg, outputs M4A.

    Args:
        segments: List of dicts with audio segment details.
        output_filename_base: Base name for the final output file (without extension).
        output_dir: Directory to store intermediate and final files.
        silence_ms: Duration of silence to add between segments (in ms).

    Returns:
        Tuple (path_to_final_m4a, list_of_chapter_details) or None if assembly fails.
        Chapter details are like [{'title': str, 'start_ms': int, 'end_ms': int}].
    """
    if not segments:
        logger.warning("No audio segments provided to assemble.")
        return None

    logger.info(f"Starting podcast assembly for {len(segments)} segments.")

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    combined_audio = AudioSegment.empty()
    chapters_for_metadata = []
    current_position_ms = 0
    temp_files_to_clean = []

    # 1. Concatenate Audio using pydub
    logger.info("Concatenating audio segments with pydub...")
    silence = AudioSegment.silent(duration=silence_ms) if silence_ms > 0 else AudioSegment.empty()

    for i, segment in enumerate(segments):
        audio_path = segment.get('audio_path')
        duration_ms = segment.get('duration_ms')
        source_title = segment.get('source', f'Segment {i+1}')

        if not audio_path or not os.path.exists(audio_path):
            logger.warning(f"Audio file not found for segment '{source_title}'. Skipping: {audio_path}")
            continue
        if not isinstance(duration_ms, int) or duration_ms <= 0:
             logger.warning(f"Invalid duration ({duration_ms}) for segment '{source_title}'. Attempting to load anyway, chapter timing may be off.")
             # Try to load and get duration again as fallback
             try:
                 loaded_segment_check = AudioSegment.from_file(audio_path)
                 duration_ms = len(loaded_segment_check)
                 logger.info(f"Fallback duration loaded for '{source_title}': {duration_ms} ms")
                 if duration_ms <= 0: raise ValueError("Duration still zero or negative.")
             except Exception as load_err:
                  logger.error(f"Could not load or get valid duration for '{source_title}'. Skipping segment. Error: {load_err}")
                  continue


        # Add silence before segment (except for the very first one)
        if i > 0:
            combined_audio += silence
            current_position_ms += silence_ms

        # Record chapter start time *before* adding this segment's audio
        chapter_start_ms = current_position_ms

        # Load and append the actual audio segment
        try:
            audio_segment = AudioSegment.from_file(audio_path)
            combined_audio += audio_segment
            current_position_ms += len(audio_segment) # Use actual loaded duration
        except CouldntDecodeError:
            logger.error(f"pydub failed to decode segment '{source_title}' from {audio_path}. Skipping.")
            # Roll back position if silence was added? Tricky. Best to just skip.
            continue
        except Exception as e:
            logger.error(f"Error loading segment '{source_title}' from {audio_path}: {e}. Skipping.")
            continue

        # Record chapter end time
        chapter_end_ms = current_position_ms
        chapters_for_metadata.append({
            'title': source_title,
            'start_ms': chapter_start_ms,
            'end_ms': chapter_end_ms
        })
        logger.debug(f"Appended '{source_title}'. Chapter: {chapter_start_ms}ms - {chapter_end_ms}ms")


    if len(combined_audio) == 0:
        logger.error("Audio concatenation resulted in an empty audio segment. Aborting.")
        return None

    # 2. Export Concatenated Audio (Temporarily)
    # Using mkstemp for a secure temporary file path
    try:
        fd, temp_concat_mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="concat_", dir=output_dir)
        os.close(fd) # Close the file descriptor, we just need the path
        temp_files_to_clean.append(temp_concat_mp3_path)
        logger.info(f"Exporting concatenated audio to temporary file: {temp_concat_mp3_path}")
        combined_audio.export(temp_concat_mp3_path, format="mp3")
    except Exception as e:
        logger.error(f"Failed to export concatenated MP3: {e}", exc_info=True)
        # Clean up temp files created so far
        for f_path in temp_files_to_clean:
            try: os.remove(f_path)
            except OSError: pass
        return None

    # 3. Create Chapter Metadata File
    try:
        fd, temp_metadata_path = tempfile.mkstemp(suffix=".txt", prefix="metadata_", dir=output_dir)
        os.close(fd)
        temp_files_to_clean.append(temp_metadata_path)
        if not _create_ffmpeg_metadata_file(chapters_for_metadata, temp_metadata_path):
            raise RuntimeError("Failed to create ffmpeg metadata file.") # Propagate failure
    except Exception as e:
         logger.error(f"Failed during metadata file creation: {e}", exc_info=True)
         # Clean up temp files
         for f_path in temp_files_to_clean:
            try: os.remove(f_path)
            except OSError: pass
         return None


    # 4. Run ffmpeg to Combine Audio and Metadata into M4A
    final_m4a_path = str(Path(output_dir) / f"{output_filename_base}.m4a")
    logger.info(f"Running ffmpeg to create final M4A with chapters: {final_m4a_path}")

    ffmpeg_cmd = [
    'ffmpeg',
    '-y',                      # Overwrite output
    '-hide_banner',            # Less verbose output
    '-loglevel', 'warning',    # Show warnings/errors
    '-i', temp_concat_mp3_path, # Input 1: Concatenated MP3 audio
    '-i', temp_metadata_path,   # Input 2: Metadata file
    '-map_metadata', '1',       # Apply metadata from Input 2
    '-codec:a', 'aac',          # Encode audio stream to AAC
    # Optional: Specify audio bitrate like '-b:a', '192k', - ensure comma if uncommented!
    final_m4a_path              # Output file MUST be the last argument here
]

    logger.debug(f"ffmpeg command: {' '.join(ffmpeg_cmd)}")

    try:
        # Run ffmpeg command
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=False) # check=False to handle errors manually

        if result.returncode != 0:
            logger.error(f"ffmpeg command failed with return code {result.returncode}")
            logger.error(f"ffmpeg stderr:\n{result.stderr}")
            raise RuntimeError(f"ffmpeg failed. Stderr: {result.stderr}")
        else:
            logger.info("ffmpeg command completed successfully.")
            if result.stderr: # Log any warnings ffmpeg might have produced
                 logger.warning(f"ffmpeg stderr (warnings):\n{result.stderr}")

    except FileNotFoundError:
        logger.critical("ffmpeg command not found. Please ensure ffmpeg is installed and in the system PATH.")
        # Clean up temp files
        for f_path in temp_files_to_clean:
           try: os.remove(f_path)
           except OSError: pass
        return None
    except Exception as e:
        logger.error(f"An error occurred while running ffmpeg: {e}", exc_info=True)
        # Clean up temp files
        for f_path in temp_files_to_clean:
            try: os.remove(f_path)
            except OSError: pass
        # Also remove potentially incomplete final M4A file
        if os.path.exists(final_m4a_path):
             try: os.remove(final_m4a_path)
             except OSError: pass
        return None

    # 5. Cleanup Temporary Files
    logger.info("Cleaning up temporary concatenation and metadata files...")
    for f_path in temp_files_to_clean:
        try:
            os.remove(f_path)
            logger.debug(f"Removed temp file: {f_path}")
        except OSError as e:
            logger.warning(f"Could not remove temporary file {f_path}: {e}")

    logger.info(f"Podcast assembly finished. Final file: {final_m4a_path}")
    return final_m4a_path, chapters_for_metadata