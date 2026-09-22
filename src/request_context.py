"""Optional web request settings, isolated by execution context (not process env)."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class GeminiRequestContext:
    api_key: str = field(repr=False)
    model: str
    on_request: Callable[[], None]
    on_usage: Callable[[dict], None]
    timeout_ms: int = 90000


current_request = ContextVar('gemini_request', default=None)


@contextmanager
def gemini_request(context):
    token = current_request.set(context)
    try:
        yield
    finally:
        current_request.reset(token)


def usage_counts(metadata):
    """Return only numeric token fields actually supplied by the SDK."""
    result = {}
    for label, name in (('input_tokens', 'prompt_token_count'),
                        ('output_tokens', 'candidates_token_count'),
                        ('thinking_tokens', 'thoughts_token_count'),
                        ('total_tokens', 'total_token_count')):
        value = metadata.get(name) if isinstance(metadata, dict) else getattr(metadata, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[label] = value
    return result
