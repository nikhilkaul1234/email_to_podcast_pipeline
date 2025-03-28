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
        model: The OpenAI model ID to use (e.g., 'gpt-4o', 'gpt-3.5-turbo').

    Returns:
        The generated summary text, or None if an error occurs.
    """
    if not _openai_client:
        logger.error("OpenAI client is not initialized. Cannot summarize.")
        return None
    if not text:
        logger.warning(f"Received empty text for source '{source_name}'. Skipping summarization.")
        return None

    # Adjust prompt based on requirements
    prompt = f"""
    Please act as a concise news summarizer for a spoken podcast format.
    Summarize the following article from '{source_name}'.
    Focus on the key information, main points, and conclusions. Avoid introductory phrases like "This article discusses...". Get straight to the point.
    Aim for a summary length of approximately {target_word_count} words.

    Article Text:
    ---
    {text}
    ---

    Summary:
    """

    # Estimate max_tokens. This is a rough guide; the model doesn't strictly adhere.
    # OpenAI token count is usually ~0.75 words per token. Add some buffer.
    # Ensure max_tokens isn't excessively small or large.
    max_tokens = max(100, int(target_word_count / 0.6)) # Allow generous token count

    logger.info(f"Requesting summary for '{source_name}' with target ~{target_word_count} words using model '{model}'. Estimated max_tokens: {max_tokens}")

    try:
        response = _openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes articles for a podcast."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,  # Lower temperature for more focused summaries
            max_tokens=max_tokens,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0
        )

        summary = response.choices[0].message.content.strip()
        actual_word_count = len(summary.split())
        logger.info(f"Summary received for '{source_name}'. Actual word count: {actual_word_count} (Target: ~{target_word_count})")
        # Optional: Log token usage
        # usage = response.usage
        # logger.debug(f"OpenAI API Usage for '{source_name}': Prompt={usage.prompt_tokens}, Completion={usage.completion_tokens}, Total={usage.total_tokens}")

        return summary

    except openai.APIError as e:
        logger.error(f"OpenAI API Error summarizing '{source_name}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error summarizing '{source_name}': {e}", exc_info=True)

    return None


# --- Length Calculation Logic ---
def calculate_target_lengths(
    contents: List[Dict[str, str]], # Expects [{'source': str, 'original_text': str}]
    min_duration_mins: int,
    max_duration_mins: int,
    words_per_minute: int
) -> List[Dict[str, int]]:
    """
    Calculates target summary word counts for each content piece based on
    total content length and desired podcast duration range.

    Args:
        contents: List of dictionaries, each containing 'source' and 'original_text'.
        min_duration_mins: Minimum desired podcast duration in minutes.
        max_duration_mins: Maximum desired podcast duration in minutes.
        words_per_minute: Estimated speaking rate.

    Returns:
        List of dictionaries, each containing 'source' and 'target_words'.
    """
    if not contents:
        return []

    total_original_words = sum(len(item.get('original_text', '').split()) for item in contents)
    if total_original_words == 0:
        logger.warning("Total original word count is zero. Cannot calculate target lengths.")
        return [{'source': item['source'], 'target_words': 100} for item in contents] # Default small target

    # Calculate total target words based on duration range
    min_target_words = min_duration_mins * words_per_minute
    max_target_words = max_duration_mins * words_per_minute

    # Determine a preliminary total target based on a simple ratio (capped by max_duration)
    # This is a heuristic: longer input -> longer output, but within limits.
    # Example: Try to scale output based on input length, maybe aiming for 50 mins if input is medium?
    # Let's try a simple proportional scaling capped by max.
    # A very rough "average" summary ratio might be 10:1? This varies wildly.
    # Let's aim for a target *within* the range based on input size.

    # Simplified approach: Scale linearly between min and max based on input word count? Needs reference points.
    # Let's try mapping input word count ranges to target durations.
    # < 3000 words -> 30 mins
    # 3000-8000 words -> 45 mins
    # 8000-15000 words -> 60 mins
    # > 15000 words -> 75 mins (capped below 90)
    # This is arbitrary and can be adjusted.

    if total_original_words < 3000:
        target_duration_mins = min_duration_mins
    elif total_original_words < 8000:
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 45))
    elif total_original_words < 15000:
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 60))
    else:
        target_duration_mins = min(max_duration_mins, max(min_duration_mins, 75))

    # Ensure the chosen target duration is strictly within the bounds
    target_duration_mins = max(min_duration_mins, min(max_duration_mins, target_duration_mins))
    total_target_words = target_duration_mins * words_per_minute

    logger.info(f"Total original words: {total_original_words}. Aiming for target duration: {target_duration_mins} mins ({total_target_words} words).")

    # Distribute total target words proportionally based on original text length
    target_lengths = []
    actual_total_target = 0
    min_words_per_summary = 50 # Ensure summaries aren't trivially short

    for item in contents:
        original_words = len(item.get('original_text', '').split())
        proportion = (original_words / total_original_words) if total_original_words > 0 else 0
        calculated_target = int(proportion * total_target_words)
        # Apply minimum length and round up slightly? Using math.ceil after multiplying
        target_words = max(min_words_per_summary, calculated_target)
        target_lengths.append({'source': item['source'], 'target_words': target_words})
        actual_total_target += target_words

    # Optional: Adjust if the sum of minimums exceeds the total target or if total is too low/high?
    # If actual_total_target significantly differs from total_target_words, could rescale.
    # For simplicity, we'll stick with the proportional distribution + minimum.
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

    Args:
        contents: List of dictionaries with 'source' and 'original_text'.
        min_duration_mins: Minimum podcast duration.
        max_duration_mins: Maximum podcast duration.
        words_per_minute: Estimated speaking rate.

    Returns:
        List of dictionaries, each containing 'source' and 'summary_text'.
        Returns empty list if summarization fails for all items or input is empty.
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
        original_text = item['original_text']
        target_words = target_length_map.get(source)

        if not target_words:
             logger.warning(f"Could not find target word count for source '{source}'. Using default 150.")
             target_words = 150 # Fallback target

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
            # Optionally add a placeholder or skip entirely
            # summaries.append({'source': source, 'summary_text': f"[Summarization failed for {source}]"})


    if not summaries:
         logger.error("Summarization failed for all provided content pieces.")
    else:
         logger.info(f"Successfully generated summaries for {len(summaries)} out of {len(contents)} pieces.")

    return summaries