"""
Thin streaming wrapper around the Anthropic API for the "ask AI" panel.
Bring-your-own-key: reads ANTHROPIC_API_KEY from the environment. If it's
missing, callers get a clear LLMNotConfigured error instead of a crash.
"""

import os
from typing import Iterator, List, Optional

MODEL = os.environ.get("READER3_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a reading companion embedded in an ebook reader called reader3. \
The reader is currently on the book "{title}" by {authors}, chapter "{chapter_title}".

Answer questions about the text directly and concisely — a paragraph or two unless asked \
for more. Ground your answer in the passage given below; don't pad with disclaimers or \
restate the question. If something outside the passage is asked (broader context, \
historical background, etc.), answer it plainly using your own knowledge, and say so.

--- PASSAGE / CONTEXT ---
{context}
--- END PASSAGE ---
"""


class LLMNotConfigured(Exception):
    pass


class LLMError(Exception):
    pass


def stream_chat(
    question: str,
    context: str,
    title: str,
    authors: str,
    chapter_title: str,
    history: Optional[List[dict]] = None,
) -> Iterator[str]:
    """Yields text deltas. Raises LLMNotConfigured / LLMError on failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY is not set. Export it before starting the server "
            "(see README) to enable the AI chat panel."
        )

    try:
        import anthropic
    except ImportError:
        raise LLMError("The 'anthropic' package isn't installed. Run `uv sync`.")

    client = anthropic.Anthropic(api_key=api_key)

    system = SYSTEM_PROMPT.format(
        title=title, authors=authors or "Unknown", chapter_title=chapter_title, context=context
    )

    messages = list(history or [])
    messages.append({"role": "user", "content": question})

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("Couldn't reach the Anthropic API — check your network connection.")
