# src/llm_handler.py

import logging
import math
from typing import List, Dict, Tuple, Optional

# Use try-except for OpenAI import for robustness, though it should be installed
try:
    import openai
    from openai import OpenAI # Use the new v1+ client
except ImportError:
    logging.exception("OpenAI library not found. Please install with 'pip install openai'")
    # You might want to raise an error or handle this more gracefully depending on requirements
    raise

from . import config # Import configuration settings

logger = logging.getLogger(__name__)

# --- OpenAI Client Initialization ---
_openai_client = None
if config.OPENAI_API_KEY:
    try:
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
else:
    logger.error("OPENAI_API_KEY not found in configuration. OpenAI client not initialized.")


# --- Core Summarization Function ---
def summarize_text(text: str, source_name: str, target_word_count: int, model: str) -> Optional[str]:
    """
    Summarizes a single piece of text using the specified OpenAI model.

    Args:
        text: The original text content to summarize.
        source_name: The name of the source (e.g., 'New York Times') for context.
        target_word_count: The desired approximate word count for the summary.
        model: The OpenAI model ID to use (e.g., 'gpt-4o', 'gpt-4o-mini').

    Returns:
        The generated summary text, or None if an error occurs.
    """
    if not _openai_client:
        logger.error("OpenAI client is not initialized. Cannot summarize.")
        return None
    if not text:
        logger.warning(f"Received empty text for source '{source_name}'. Skipping summarization.")
        return None

    # --- CHANGE 2 & 4: Updated User Prompt for Persona and Vibe ---
    # Incorporate storytelling, podcast style, and desired vocal characteristics.
    user_prompt = f"""
    Take the following article from '{source_name}' and rewrite it as an engaging podcast segment.
    Use the article as source material, but write in a conversational, listener-friendly style—like a host sharing updates or telling a story.
    Focus on clarity, flow, and energy. Highlight key points, interesting developments, and any useful or surprising insights.
    Avoid reading the article verbatim or mentioning it's based on an email. Narrate the content naturally.

    Write in a soothing, clear, and engaging conversational style suitable for a morning podcast host using the 'shimmer' voice. Ensure a steady, easy-to-follow pace in the writing.

    Aim for a segment length of approximately {target_word_count} words.

    Article Text:
    ---
    {text}
    ---

    Podcast Segment Script:
    """
    # --- END CHANGE ---

    # --- CHANGE 1: Adjusted max_tokens Calculation ---
    # Use a slightly higher words-per-token estimate (0.75) and keep the 4096 cap.
    max_tokens_estimate = int(target_word_count / 0.75) # Use 0.75 words/token estimate
    max_tokens_upper_cap = 4096 # Set a hard upper limit for output tokens
    # Ensure at least 150 tokens requested, but cap at 4096
    max_tokens = max(150, min(max_tokens_estimate, max_tokens_upper_cap))
    # --- END CHANGE ---

    logger.info(f"Requesting summary for '{source_name}' with target ~{target_word_count} words using model '{model}'. Adjusted max_tokens: {max_tokens}")

    try:
        # --- CHANGE 2: Updated System Prompt ---
        response = _openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert podcast writer and storyteller, creating engaging audio segments from text sources."},
                {"role": "user", "content": user_prompt} # Use the updated user prompt
            ],
            temperature=0.6,  # Slightly higher temp might allow for more 'storytelling' style
            max_tokens=max_tokens,
            top_p=1.0,
            frequency_penalty=0.1, # Slight penalty to discourage repetitive phrasing
            presence_penalty=0.0
        )
        # --- END CHANGE ---

        summary = response.choices[0].message.content.strip()
        actual_word_count = len(summary.split())
        logger.info(f"Summary received for '{source_name}'. Actual word count: {actual_word_count} (Target: ~{target_word_count})")
        # Optional: Log token usage
        # usage = response.usage
        # logger.debug(f"OpenAI API Usage for '{source_name}': Prompt={usage.prompt_tokens}, Completion={usage.completion_tokens}, Total={usage.total_tokens}")

        return summary

    except openai.APIError as e:
        # Check specifically for token limit errors vs other rate limits
        if 'rate_limit_exceeded' in str(e).lower() and 'tokens' in str(e).lower():
             logger.error(f"OpenAI Rate Limit Error (Tokens) summarizing '{source_name}': {e}. Input or output tokens exceed limit.", exc_info=False) # Less verbose stack trace for this specific error
        elif 'rate_limit_exceeded' in str(e).lower():
             logger.error(f"OpenAI Rate Limit Error (Requests) summarizing '{source_name}': {e}.", exc_info=False)
        elif 'insufficient_quota' in str(e).lower():
             logger.error(f"OpenAI Insufficient Quota Error summarizing '{source_name}': {e}. Check billing/plan.", exc_info=False)
        else:
             logger.error(f"OpenAI API Error summarizing '{source_name}': {e}", exc_info=True) # Full trace for others
    except Exception as e:
        logger.error(f"Unexpected error summarizing '{source_name}': {e}", exc_info=True)

    return None


# --- Length Calculation Logic (No changes needed here based on request) ---
def calculate_target_lengths(
    contents: List[Dict[str, str]], # Expects [{'source': str, 'original_text': str}]
    min_duration_mins: int,
    max_duration_mins: int,
    words_per_minute: int
) -> List[Dict[str, int]]:
    """
    Calculates target summary word counts for each content piece based on
    total content length and desired podcast duration range.
    """
    if not contents:
        return []

    total_original_words = sum(len(item.get('original_text', '').split()) for item in contents)
    if total_original_words == 0:
        logger.warning("Total original word count is zero. Cannot calculate target lengths.")
        return [{'source': item['source'], 'target_words': 100} for item in contents] # Default small target

    min_target_words = min_duration_mins * words_per_minute
    max_target_words = max_duration_mins * words_per_minute

    # Heuristic mapping input word count ranges to target durations (within bounds)
    if total_original_words < 3000:
        target_duration_mins = min_duration_mins
    elif total_original_words < 8000:
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 45))
    elif total_original_words < 15000:
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 60))
    else:
        # For very large inputs, aim closer to the max allowed duration
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 75)) # Could even go to 80-85 if max is 90

    # Ensure the chosen target duration is strictly within the bounds
    target_duration_mins = max(min_duration_mins, min(max_duration_mins, target_duration_mins))
    total_target_words = target_duration_mins * words_per_minute

    logger.info(f"Total original words: {total_original_words}. Aiming for target duration: {target_duration_mins} mins ({total_target_words} words).")

    # Distribute total target words proportionally based on original text length
    target_lengths = []
    actual_total_target = 0
    min_words_per_summary = 75 # Increased slightly from 50

    # Calculate proportions first
    proportions = {}
    for item in contents:
        original_words = len(item.get('original_text', '').split())
        proportions[item['source']] = (original_words / total_original_words) if total_original_words > 0 else 0

    # Allocate based on proportions, ensuring minimum
    for item in contents:
        source = item['source']
        proportion = proportions[source]
        calculated_target = int(proportion * total_target_words)
        target_words = max(min_words_per_summary, calculated_target)
        target_lengths.append({'source': source, 'target_words': target_words})
        actual_total_target += target_words

    # Optional: Rescale if sum significantly deviates (more complex, skipping for now)
    # if actual_total_target > max_target_words * 1.1: # If sum is way over max
    #    scaling_factor = (max_target_words * 1.1) / actual_total_target
    #    # Rescale logic here, ensuring min_words_per_summary is still met

    logger.info(f"Calculated initial target lengths. Sum of targets: {actual_total_target} words.")
    return target_lengths


# --- Main Orchestration Function ---
def summarize_all(
    contents: List[Dict[str, str]], # Expects [{'source': str, 'original_text': str}]
    min_duration_mins: int,
    max_duration_mins: int,
    words_per_minute: int
) -> List[Dict[str, str]]:
    """
    Calculates target lengths and summarizes all content pieces.
    """
    if not contents:
        logger.warning("summarize_all called with no content.")
        return []
    if not _openai_client:
        logger.error("OpenAI client not initialized. Cannot summarize.")
        return []

    target_lengths = calculate_target_lengths(contents, min_duration_mins, max_duration_mins, words_per_minute)

    summaries = []
    target_length_map = {item['source']: item['target_words'] for item in target_lengths}

    for item in contents:
        source = item['source']
        original_text = item.get('original_text', '') # Ensure it's a string
        target_words = target_length_map.get(source)

        if not target_words:
             logger.warning(f"Could not find target word count for source '{source}'. Using default 150.")
             target_words = 150 # Fallback target

        # Add a small delay between API calls to help with potential rate limits
        # Note: The OpenAI library has automatic retries, but this adds an extra buffer.
        # time.sleep(1) # Consider adding a 1-second sleep if still hitting request rate limits

        summary_text = summarize_text(
            text=original_text,
            source_name=source,
            target_word_count=target_words,
            model=config.SUMMARIZATION_MODEL # Use model from config
        )

        if summary_text:
            summaries.append({'source': source, 'summary_text': summary_text})
        else:
            logger.warning(f"Summarization failed for source '{source}'. It will be excluded.")

    if not summaries:
         logger.error("Summarization failed for all provided content pieces.")
    else:
         logger.info(f"Successfully generated summaries for {len(summaries)} out of {len(contents)} pieces.")

    return summaries