import azure.functions as func
import datetime
import json
import logging

app = func.FunctionApp()

# function_app.py
# Note: This file should be at the root of your project, alongside host.json

# Import our custom modules using relative paths from the 'src' package perspective
# This assumes your source code is in 'src/' and function_app.py is at the root.
# Azure Functions deployment might put everything in the root, adjust if needed.
# A common pattern is to put function_app.py and src/ together in deployment.
# Let's assume for now they are deployed side-by-side or src/ is added to sys.path.
# If deployed: /home/site/wwwroot/function_app.py, /home/site/wwwroot/src/config.py etc.
# If running locally: /path/to/project/function_app.py, /path/to/project/src/config.py etc.
# Python should handle this relative import if function_app.py can see the 'src' folder.

# Try importing directly assuming 'src' might be added to path or be in root
try:
    from src import config, email_client, content_parser
    # Placeholders for modules we haven't created yet
    # from src import llm_handler, tts_processor, audio_processor, storage_client
except ImportError as e:
    logging.error(f"ImportError: {e}. Check PYTHONPATH or project structure. Assuming src/* is in the root for deployment.")
    # Fallback attempt assuming src contents are copied to root in deployment
    import config
    import email_client
    import content_parser
    # Placeholders
    # import llm_handler
    # import tts_processor
    # import audio_processor
    # import storage_client

# Define the Azure Function App object
app = func.FunctionApp()

# Define the timer trigger function
# Schedule Format: "{second} {minute} {hour} {day} {month} {day of week}"
# Example: Run once daily at 7:00 AM UTC -> "0 0 7 * * *"
# Check Azure Functions CRON expressions documentation for details.
# Use 'run_on_startup=True' for easy local testing (runs when func host starts)
# Set use_monitor=False if you don't need the execution tracking in Azure Storage logs for timer
@app.schedule(schedule="0 1 6 * * *", # 4 PM UTC daily - ADJUST AS NEEDED!
              arg_name="myTimer",
              run_on_startup=False, # Set to True for local debugging runs
              use_monitor=True)
def daily_email_podcast_job(myTimer: func.TimerRequest) -> None:
    """
    Main function triggered daily to fetch, summarize, and generate podcast.
    """
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if myTimer.past_due:
        logging.warning('The timer is past due!')

    logging.info(f'Python timer trigger function executed at {utc_timestamp}')
    logging.info(f"Using configuration - Target Email: {config.TARGET_EMAIL_ADDRESS}, "
                 f"Sources: {len(config.EMAIL_SOURCES)}, Summarizer: {config.SUMMARIZATION_MODEL}")

    # --- Main Workflow ---
    processed_content = [] # List to hold objects like {'source': 'NYT', 'text': 'Summary...'}

    try:
        # 1. Initialize Gmail Service
        gmail_service = email_client._get_gmail_service()
        if not gmail_service:
             logging.error("Failed to initialize Gmail Service. Aborting run.")
             return # Stop execution if Gmail connection fails

        # 2. Find Recent Emails
        messages = email_client.find_recent_emails(gmail_service, config.EMAIL_SOURCES, days_ago=1)
        if not messages:
            logging.info("No new emails found from sources today.")
            # Optional: Send a notification email saying no content today?
            # email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, "Daily Digest - No Content", "No new articles found today.")
            return # Nothing more to do

        logging.info(f"Found {len(messages)} emails to process.")

        # 3. Fetch, Parse, and Store Content for Each Email
        email_contents = [] # List to hold {'source': str, 'original_text': str}
        for msg_summary in messages:
            msg_id = msg_summary['id']
            logging.debug(f"Fetching details for message ID: {msg_id}")
            message = email_client.get_email_details(gmail_service, msg_id)

            if not message:
                logging.warning(f"Could not fetch details for message {msg_id}. Skipping.")
                continue

            # Extract sender for associating content with source later
            sender = email_client.get_sender(message)
            source_name = sender or f"Unknown Source (ID: {msg_id})" # Basic source naming

            # Extract body
            plain_body, html_body = email_client.extract_email_body(message)

            # Parse content (prioritize HTML)
            original_text = content_parser.parse_content(plain_body, html_body)

            if original_text:
                logging.info(f"Successfully parsed content (length: {len(original_text)}) from {source_name}")
                email_contents.append({'source': source_name, 'original_text': original_text})
            else:
                logging.warning(f"Could not parse meaningful content from {source_name} (ID: {msg_id}). Skipping.")


        if not email_contents:
            logging.info("Finished processing emails, but no usable content was extracted.")
            # Optional: Send notification
            # email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, "Daily Digest - No Content", "Found emails, but could not extract usable content today.")
            return

        logging.info(f"Successfully extracted content from {len(email_contents)} emails.")

        # --- Placeholder for next steps ---

        # 4. Calculate Target Lengths & Summarize
        # TODO: Implement length calculation based on total content and 30-90 min target
        # TODO: Call llm_handler.summarize for each item in email_contents
        # Example structure:
        # summaries = llm_handler.summarize_all(email_contents, config.PODCAST_MIN_DURATION_MINS, config.PODCAST_MAX_DURATION_MINS, config.PODCAST_WORDS_PER_MINUTE)
        # processed_content = summaries # Assuming summarize_all returns list like [{'source': 'NYT', 'summary_text': '...'}]
        logging.warning("Summarization logic not yet implemented.") # Placeholder log
        # TEMP: For now, just pass original text to simulate structure
        processed_content = [{'source': item['source'], 'summary_text': f"Summary for {item['source']} (Content length: {len(item['original_text'])})"} for item in email_contents]


        # 5. Generate TTS Audio Segments
        # TODO: Call tts_processor for intro, each summary, outro
        # Example structure:
        # audio_segments = tts_processor.generate_speech_segments(processed_content)
        # audio_segments should contain paths to audio files and their durations
        logging.warning("TTS generation logic not yet implemented.") # Placeholder log
        # TEMP: Simulate audio segments info
        audio_segments = [
            {'source': 'Intro', 'audio_path': 'dummy_intro.mp3', 'duration_ms': 5000, 'text': 'Welcome to your daily digest.'},
        ]
        segment_duration_ms = 30000 # 30 seconds dummy duration per segment
        for i, item in enumerate(processed_content):
             audio_segments.append({
                 'source': item['source'],
                 'audio_path': f'dummy_segment_{i}.mp3',
                 'duration_ms': segment_duration_ms,
                 'text': item['summary_text']
             })
        audio_segments.append({
             'source': 'Outro', 'audio_path': 'dummy_outro.mp3', 'duration_ms': 3000, 'text': 'End of digest.'
        })


        # 6. Assemble Podcast with Chapters
        # TODO: Call audio_processor to concatenate segments and add chapters
        # Example structure:
        # final_audio_path, chapters = audio_processor.assemble_podcast(audio_segments, output_filename="daily_digest.m4a")
        logging.warning("Audio assembly logic not yet implemented.") # Placeholder log
        # TEMP: Simulate result
        final_audio_path = "dummy_final_podcast.m4a"
        chapters = [{'title': seg['source'], 'start_ms': sum(s['duration_ms'] for s in audio_segments[:i])} for i, seg in enumerate(audio_segments)]


        # 7. Upload to Cloud Storage
        # TODO: Call storage_client to upload final_audio_path and get URL
        # Example structure:
        # podcast_url = storage_client.upload_and_get_sas_url(final_audio_path, config.AZURE_STORAGE_CONNECTION_STRING, config.AZURE_STORAGE_CONTAINER_NAME)
        logging.warning("Azure Storage upload logic not yet implemented.") # Placeholder log
        # TEMP: Simulate result
        podcast_url = "https://example.com/dummy_podcast_link.m4a"


        # 8. Send Email Notification
        if podcast_url:
            logging.info(f"Generated podcast URL: {podcast_url}")
            # TODO: Format email body nicely with chapters
            email_subject = f"Your Daily News Digest Podcast - {datetime.date.today().strftime('%Y-%m-%d')}"
            email_body = f"Hi,\n\nHere is your summarized news podcast for today.\n\nListen here: {podcast_url}\n\nChapters:\n"
            for chap in chapters:
                 start_secs = chap['start_ms'] // 1000
                 minutes = start_secs // 60
                 seconds = start_secs % 60
                 email_body += f"- {chap['title']} ({minutes:02d}:{seconds:02d})\n"
            email_body += "\nEnjoy!"

            success = email_client.send_email(gmail_service, config.TARGET_EMAIL_ADDRESS, email_subject, email_body)
            if success:
                logging.info("Notification email sent successfully.")
            else:
                logging.error("Failed to send notification email.")
        else:
            logging.error("Podcast generation or upload failed, no URL obtained. Cannot send notification.")


        # 9. Cleanup (Optional)
        # TODO: Delete temporary audio files if needed
        logging.info("Cleanup logic not yet implemented.")


    except ConnectionError as e:
         # Handle specific connection errors (like auth failure) gracefully
         logging.error(f"A connection error occurred: {e}", exc_info=True)
         # Optionally try to send a failure notification if possible, or just log
    except Exception as e:
        # Catch-all for unexpected errors during the process
        logging.error(f"An unexpected error occurred during the podcast generation process: {e}", exc_info=True)
        # Optionally try to send a failure notification
        try:
            if 'gmail_service' in locals() and gmail_service: # Check if service was initialized
                 email_client.send_email(
                      gmail_service, config.TARGET_EMAIL_ADDRESS,
                      "Error: Daily Digest Failed",
                      f"An error occurred during the podcast generation:\n\n{e}\n\nCheck the Azure Function logs for details."
                 )
        except Exception as email_err:
             logging.error(f"Additionally, failed to send error notification email: {email_err}")


    logging.info('Python timer trigger function finished execution.')