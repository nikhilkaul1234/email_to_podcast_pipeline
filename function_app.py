# function_app.py
# Root file for the Azure Function App using the v2 programming model.

import azure.functions as func
import logging
import datetime
import shutil  # For directory cleanup
import os      # For path checks

# --- Module Imports ---
# Attempt to import modules assuming 'src' is a package relative to this file
# or that 'src' contents are deployed alongside function_app.py in the root.
try:
    from src import (
        config,
        email_client,
        content_parser,
        llm_handler,
        tts_processor
        # Placeholders for future modules:
        # audio_processor,
        # storage_client
    )
except ImportError as e:
    # Fallback for deployment scenarios where 'src' might not be treated as a package
    logging.warning(f"Relative import failed ({e}). Trying direct import assuming modules are in root or PYTHONPATH.")
    try:
        import config
        import email_client
        import content_parser
        import llm_handler
        import tts_processor
        # Placeholders for future modules:
        # import audio_processor
        # import storage_client
    except ImportError as fallback_e:
         logging.error(f"Fallback import also failed ({fallback_e}). Critical module missing or incorrect project structure.")
         # Re-raise or exit depending on desired behavior on fatal error
         raise fallback_e

# Define the Azure Function App object
app = func.FunctionApp()

# --- Timer Trigger Function ---
# Schedule Format: "{second} {minute} {hour} {day} {month} {day of week}" (UTC)
# Example: "0 0 7 * * *" = 7:00 AM UTC daily
# Set run_on_startup=True for easy local testing (runs when func host starts)
@app.schedule(schedule="0 0 7 * * *", # ADJUST CRON SCHEDULE AS NEEDED
              arg_name="myTimer",
              run_on_startup=False, # Set to True ONLY for local debugging
              use_monitor=True)    # Set based on whether you want Azure Monitor logging for timer
def daily_email_podcast_job(myTimer: func.TimerRequest) -> None:
    """
    Main Azure Function triggered daily to fetch emails, summarize,
    generate a podcast audio file, upload it, and send a notification.
    """
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if myTimer.past_due:
        logging.warning('The timer is past due!')

    logging.info(f'Python timer trigger function started execution at {utc_timestamp}')
    logging.info(f"Configuration - Target: {config.TARGET_EMAIL_ADDRESS}, Sources: {len(config.EMAIL_SOURCES)}, Summarizer: {config.SUMMARIZATION_MODEL}, TTS Voice: {config.AUDIO_TTS_VOICE}")

    # --- Variable Initialization ---
    temp_tts_dir = None      # Path to the temporary directory holding TTS audio segments
    gmail_service = None     # Gmail API service object
    podcast_url = None       # URL of the final uploaded podcast file
    email_contents = []      # List holding {'source': str, 'original_text': str}
    summaries = []           # List holding {'source': str, 'summary_text': str}
    audio_segments = []      # List holding detailed info about each TTS segment file
    chapters = []            # List holding {'title': str, 'start_ms': int} for the podcast

    try:
        # --- Step 1: Initialize Gmail Service ---
        logging.info("Initializing Gmail service...")
        gmail_service = email_client._get_gmail_service()
        if not gmail_service:
             # Error already logged in _get_gmail_service
             raise ConnectionError("Failed to initialize Gmail Service.") # Stop execution

        # --- Step 2: Find Recent Emails ---
        logging.info("Searching for recent emails...")
        messages = email_client.find_recent_emails(gmail_service, config.EMAIL_SOURCES, days_ago=1)
        if not messages:
            logging.info("No new emails found from specified sources today. Exiting.")
            # Optional: Send a 'no content' notification email if desired
            # email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, "Daily Digest - No Content", "No new articles found today.")
            return # Normal exit, nothing to process

        logging.info(f"Found {len(messages)} candidate emails.")

        # --- Step 3: Fetch, Parse, and Store Content for Each Email ---
        logging.info("Fetching and parsing email content...")
        for msg_summary in messages:
            msg_id = msg_summary['id']
            logging.debug(f"Processing message ID: {msg_id}")
            message = email_client.get_email_details(gmail_service, msg_id)
            if not message: continue # Error logged in get_email_details

            sender = email_client.get_sender(message) or f"Unknown Source <{msg_id[:10]}...>"
            plain_body, html_body = email_client.extract_email_body(message)
            original_text = content_parser.parse_content(plain_body, html_body)

            if original_text:
                logging.info(f"Parsed content (length: {len(original_text)}) from '{sender}'")
                email_contents.append({'source': sender, 'original_text': original_text})
            else:
                logging.warning(f"Could not parse usable content from '{sender}' (ID: {msg_id}).")

        if not email_contents:
            logging.info("No usable content extracted from found emails. Exiting.")
            # Optional: Send notification
            # email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, "Daily Digest - No Usable Content", "Found emails, but couldn't extract usable content today.")
            return

        logging.info(f"Successfully extracted content from {len(email_contents)} emails.")

        # --- Step 4: Calculate Target Lengths & Summarize ---
        logging.info("Starting content summarization...")
        summaries = llm_handler.summarize_all(
            contents=email_contents,
            min_duration_mins=config.PODCAST_MIN_DURATION_MINS,
            max_duration_mins=config.PODCAST_MAX_DURATION_MINS,
            words_per_minute=config.PODCAST_WORDS_PER_MINUTE
        )
        if not summaries:
             logging.error("Summarization process failed to produce any summaries. Aborting.")
             raise ValueError("Summarization yielded no results.") # Stop execution

        logging.info(f"Summarization complete. Generated {len(summaries)} summaries.")

        # --- Step 5: Generate TTS Audio Segments ---
        logging.info("Starting TTS generation...")
        temp_tts_dir, audio_segments = tts_processor.generate_speech_segments(
            summaries=summaries # Pass the generated summaries
        )
        if not temp_tts_dir or not audio_segments:
            logging.error("TTS generation failed to produce segments or temporary directory. Aborting.")
            raise ValueError("TTS generation failed.") # Stop execution

        logging.info(f"TTS generation complete. Generated {len(audio_segments)} segments in {temp_tts_dir}.")

        # --- Step 6: Assemble Podcast with Chapters ---
        # TODO: Implement audio_processor using paths/durations from audio_segments
        logging.warning("Audio assembly logic not yet implemented.")
        # Placeholder Logic (Remove when audio_processor is implemented)
        final_audio_path = "dummy_placeholder_podcast.m4a" # Indicates assembly hasn't run
        logging.info(f"Placeholder: Assuming final audio path is {final_audio_path}")
        chapters = []
        current_time_ms = 0
        for i, seg in enumerate(audio_segments):
             # Ensure duration exists and is an int
             duration = seg.get('duration_ms')
             if isinstance(duration, int) and duration >= 0:
                  chapters.append({'title': seg.get('source', f'Segment {i}'), 'start_ms': current_time_ms})
                  current_time_ms += duration
             else:
                  logging.warning(f"Invalid or missing duration for segment {i} ({seg.get('source', 'N/A')}). Chapter timing might be inaccurate.")
        total_duration_secs = current_time_ms // 1000
        logging.info(f"Placeholder: Calculated {len(chapters)} chapters. Estimated total duration: {total_duration_secs // 60}m {total_duration_secs % 60}s.")
        # End Placeholder Logic

        # --- Step 7: Upload to Cloud Storage ---
        # TODO: Implement storage_client using the actual final_audio_path from audio_processor
        logging.warning("Azure Storage upload logic not yet implemented.")
        # Placeholder Logic (Remove when storage_client is implemented)
        if os.path.exists(final_audio_path): # Check if placeholder path is actually real (it shouldn't be)
             logging.warning("Placeholder audio file path appears to exist - this should not happen yet.")
             podcast_url = "https://placeholder.invalid/real_path_found_unexpectedly.m4a"
        else:
             # Simulate successful upload if audio *assembly* was supposed to succeed
             if final_audio_path != "dummy_placeholder_podcast.m4a": # Check if assembly placeholder was updated
                 podcast_url = f"https://{config.AZURE_STORAGE_CONTAINER_NAME}.blob.core.windows.net/audio/{os.path.basename(final_audio_path)}?sas_token=dummy" # Simulated URL
                 logging.info(f"Placeholder: Simulating upload success. URL: {podcast_url}")
             else:
                 logging.error("Placeholder: Audio assembly step did not produce a final path. Cannot simulate upload.")
                 podcast_url = None
        # End Placeholder Logic

        # --- Step 8: Send Email Notification ---
        if podcast_url:
            logging.info(f"Preparing notification email for URL: {podcast_url}")
            email_subject = f"Your Daily News Digest Podcast - {datetime.date.today().strftime('%Y-%m-%d')}"
            # Count summaries actually included (assuming 1 intro, 1 outro)
            article_count = max(0, len(audio_segments) - 2) if len(audio_segments) >= 2 else 0
            email_body = f"Hi,\n\nHere is your summarized news podcast for today ({article_count} articles included).\n\nListen here: {podcast_url}\n\nChapters:\n"
            for chap in chapters:
                 start_secs = chap['start_ms'] // 1000
                 minutes = start_secs // 60
                 seconds = start_secs % 60
                 email_body += f"- {chap.get('title', 'Chapter')} ({minutes:02d}:{seconds:02d})\n"
            email_body += "\nEnjoy!"

            success = email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, email_subject, email_body)
            if success:
                logging.info("Notification email sent successfully.")
            else:
                # Error already logged by send_email
                logging.error("Failed to send notification email.")
        else:
            logging.error("Podcast generation or upload failed, no URL obtained. Cannot send notification.")
            # Raise an error here maybe, to indicate the overall process failed?
            raise RuntimeError("Failed to obtain final podcast URL.")


    except (ConnectionError, ValueError, RuntimeError, openai.APIError) as e:
         # Catch specific, expected exceptions from our workflow or OpenAI
         logging.error(f"Workflow halted due to an error: {e}", exc_info=True)
         # Try to send a failure notification
         try:
             if gmail_service and config.TARGET_EMAIL_ADDRESS: # Check if we can send email
                  email_client.send_email(
                       gmail_service, config.TARGET_EMAIL_ADDRESS,
                       f"Error: Daily Digest Failed ({type(e).__name__})",
                       f"The daily podcast generation failed.\n\nError:\n{e}\n\nCheck the Azure Function logs ({utc_timestamp}) for details."
                  )
                  logging.info("Sent error notification email.")
             else:
                  logging.warning("Cannot send error notification email (Gmail service unavailable or target address missing).")
         except Exception as email_err:
              logging.error(f"Additionally, failed to send error notification email: {email_err}")

    except Exception as e:
        # Catch-all for any other unexpected errors
        logging.error(f"An unexpected error occurred during the podcast generation process: {e}", exc_info=True)
        # Try to send a failure notification
        try:
            if gmail_service and config.TARGET_EMAIL_ADDRESS:
                 email_client.send_email(
                      gmail_service, config.TARGET_EMAIL_ADDRESS,
                      "Error: Daily Digest Failed Unexpectedly",
                      f"An unexpected error occurred during podcast generation:\n\n{e}\n\nCheck the Azure Function logs ({utc_timestamp}) for details."
                 )
                 logging.info("Sent unexpected error notification email.")
            else:
                 logging.warning("Cannot send unexpected error notification email.")
        except Exception as email_err:
             logging.error(f"Additionally, failed to send unexpected error notification email: {email_err}")


    finally:
        # --- Step 9: Cleanup Temporary Files ---
        if temp_tts_dir and os.path.isdir(temp_tts_dir):
            try:
                shutil.rmtree(temp_tts_dir)
                logging.info(f"Successfully cleaned up temporary TTS directory: {temp_tts_dir}")
            except Exception as e:
                logging.error(f"Error cleaning up temporary TTS directory {temp_tts_dir}: {e}", exc_info=True)
        else:
            # Log only if temp_tts_dir was expected to exist but didn't (might indicate earlier failure)
            if temp_tts_dir is not None:
                 logging.warning(f"Temporary TTS directory '{temp_tts_dir}' not found or not a directory during cleanup.")
            else:
                 logging.debug("No temporary TTS directory was created or needed cleanup.")
        # Also clean up the placeholder final file if it exists? (Shouldn't normally)
        # if 'final_audio_path' in locals() and os.path.exists(final_audio_path) and "dummy_placeholder" in final_audio_path:
        #     try: os.remove(final_audio_path)
        #     except: pass

    logging.info(f'Python timer trigger function finished execution at {datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()}')