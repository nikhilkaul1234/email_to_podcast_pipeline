# src/content_parser.py

import re
import logging
from bs4 import BeautifulSoup, NavigableString, Comment

logger = logging.getLogger(__name__)

# Tags often containing main content
PRIMARY_CONTENT_TAGS = ['article', 'main']
# Common container divs that might hold the primary content
COMMON_CONTAINER_SELECTORS = ['div#content', 'div#main', 'div.post', 'div.story', 'div.article-body']
# Tags to generally remove entirely as they contain noise
TAGS_TO_REMOVE = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript', 'figure', 'figcaption']
# Tags whose *content* might be useful, but the tag itself isn't (inline formatting)
TAGS_TO_UNWRAP = ['span', 'strong', 'em', 'b', 'i', 'u', 'a'] # Keep 'a' for now, maybe remove later or extract hrefs?
# Block tags that usually indicate structure
BLOCK_TAGS = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'div', 'ul', 'ol']


def _clean_text(text: str) -> str:
    """Basic text cleanup: removes excessive whitespace and weird characters."""
    if not text:
        return ""
    # Replace multiple whitespace chars (including newlines, tabs) with a single space
    text = re.sub(r'\s+', ' ', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    # Optional: Remove non-printable characters? Be careful not to remove legitimate unicode.
    # text = ''.join(c for c in text if c.isprintable() or c.isspace())
    return text

def extract_content_from_html(html_body: str) -> str:
    """
    Attempts to extract the main article content from HTML using heuristics.
    """
    if not html_body:
        return ""

    logger.debug("Starting HTML content extraction.")
    soup = BeautifulSoup(html_body, 'lxml') # Use lxml parser

    # 1. Remove noise tags entirely
    for tag_name in TAGS_TO_REMOVE:
        for tag in soup.find_all(tag_name):
            tag.decompose() # Remove the tag and its content

    # 2. Remove comments
    for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 3. Attempt to find a primary content container
    content_node = None
    # First, look for semantic <article> or <main> tags
    for primary_tag in PRIMARY_CONTENT_TAGS:
        content_node = soup.find(primary_tag)
        if content_node:
            logger.debug(f"Found primary content node: <{primary_tag}>")
            break

    # If not found, look for common container div IDs/classes
    if not content_node:
        for selector in COMMON_CONTAINER_SELECTORS:
            try:
                content_node = soup.select_one(selector)
                if content_node:
                    logger.debug(f"Found potential container node with selector: '{selector}'")
                    break
            except Exception as e:
                # Handle potential invalid CSS selectors, though unlikely for these simple ones
                logger.warning(f"CSS Selector error for '{selector}': {e}")
                continue

    # If still no specific container found, use the whole body as the starting point
    if not content_node:
        logger.debug("No specific primary content container found, using soup body.")
        content_node = soup.body
        if not content_node: # Should always have a body, but just in case
             logger.warning("HTML parsing resulted in no <body> tag. Returning empty.")
             return "" # Cannot proceed

    # 4. Extract text from the chosen node, focusing on block elements
    # We'll get text from relevant block tags and join with newlines for structure
    extracted_texts = []
    # Iterate through descendants, preferring block tags
    for element in content_node.find_all(BLOCK_TAGS, recursive=True):
        # Get text directly within this element, ignoring text from nested block elements
        # This prevents duplication when processing nested divs, lists etc.
        element_text = ''.join(element.find_all(text=True, recursive=False)).strip()

        # Also get text from immediate children that are NavigableString (not tags)
        string_children_text = ''.join(
            [str(child).strip() for child in element.children if isinstance(child, NavigableString)]
        ).strip()

        full_text = f"{element_text} {string_children_text}".strip()

        cleaned = _clean_text(full_text)
        if cleaned:
            extracted_texts.append(cleaned)

            # Special handling for lists: try to add bullet points or numbers
            if element.name == 'li':
                 parent = element.find_parent(['ul', 'ol'])
                 if parent and parent.name == 'ul':
                     extracted_texts[-1] = "- " + extracted_texts[-1] # Add bullet for <ul> items
                 elif parent and parent.name == 'ol':
                     # Attempt to number <ol> items (basic)
                     try:
                         # Find index within parent's 'li' children
                         li_index = parent.find_all('li', recursive=False).index(element) + 1
                         extracted_texts[-1] = f"{li_index}. " + extracted_texts[-1]
                     except ValueError:
                         extracted_texts[-1] = "* " + extracted_texts[-1] # Fallback numbering

    # If the above extraction yielded very little, fall back to getting all text
    if not extracted_texts or len(" ".join(extracted_texts)) < 100: # Arbitrary threshold
        logger.debug("Block tag extraction yielded little text, falling back to get_text().")
        all_text = content_node.get_text(separator=' ', strip=True)
        cleaned_all_text = _clean_text(all_text)
        if cleaned_all_text:
             extracted_texts = [cleaned_all_text] # Replace previous attempt
        else:
             extracted_texts = [] # Ensure it's empty if get_text also fails


    # 5. Combine extracted text pieces
    final_content = "\n\n".join(extracted_texts) # Join paragraphs/blocks with double newline

    logger.info(f"Extracted content length: {len(final_content)} characters.")
    # logger.debug(f"Extracted content preview: {final_content[:500]}...") # Optional: log preview

    return final_content


def parse_content(plain_body: Optional[str], html_body: Optional[str]) -> str:
    """
    Parses email content, preferring HTML, and falls back to plain text.
    Returns the cleaned, extracted main content as a single string.
    """
    content = ""
    if html_body:
        logger.info("Processing HTML body.")
        try:
            content = extract_content_from_html(html_body)
        except Exception as e:
            logger.error(f"Error parsing HTML body: {e}", exc_info=True)
            # Fall through to try plain text if HTML parsing fails
            content = "" # Ensure content is reset

    # If HTML parsing failed or didn't yield content, or if there was no HTML body
    if not content and plain_body:
        logger.info("HTML processing yielded no content or failed, using plain text body.")
        content = _clean_text(plain_body) # Apply basic cleanup to plain text too
    elif not content and not plain_body:
        logger.warning("No HTML or plain text body found to process.")

    return content