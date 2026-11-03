"""
The only file that talks to the language model (Groq), adapted from Round 1.

Errors raise LLMUnavailable with a short reason that is safe to show: no keys,
server paths or raw service messages. The groq package is imported only when
needed, so Round 2 runs without it.
"""
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_DEFAULT_MODEL = 'openai/gpt-oss-120b'
MAX_OUTPUT_TOKENS = 1200


class LLMUnavailable(Exception):
    """The language model could not be reached or gave no usable reply."""


def generate(system_prompt, user_prompt):
    provider = os.getenv('LLM_PROVIDER', 'groq').strip().lower() or 'groq'
    if provider != 'groq':
        raise LLMUnavailable('The AI service is not configured.')

    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        raise LLMUnavailable('The AI service is not configured.')

    try:
        import groq
    except ImportError:
        raise LLMUnavailable('The AI package is not installed on this server.')

    # The free plan allows few tokens per minute. The client waits and retries
    # on "too many requests" a couple of times before giving up.
    client = groq.Groq(
        api_key=api_key,
        timeout=getattr(settings, 'LLM_TIMEOUT_SECONDS', 30),
        max_retries=2,
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv('GROQ_MODEL', GROQ_DEFAULT_MODEL),
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=0,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            reasoning_effort='low',
            include_reasoning=False,
        )
    except groq.RateLimitError:
        raise LLMUnavailable('The AI service is busy (rate limit reached). Please try again in a minute.')
    except groq.APIError as error:
        # The full error goes to the server log only.
        logger.warning('Groq request failed: %s', type(error).__name__)
        raise LLMUnavailable('The AI service could not be reached.')

    return (response.choices[0].message.content or '').strip()
