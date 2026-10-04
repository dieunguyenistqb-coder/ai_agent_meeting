"""Staging access, upload and download helpers. No extraction business rules."""
from dataclasses import dataclass, field
import json
import os
import re
import threading

import streamlit as st

import config
from src.request_context import GeminiRequestContext

MAX_UPLOAD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str = 'gemini-3.6-flash'


def read_settings():
    def setting(name, default=''):
        try:
            value = st.secrets.get(name, os.environ.get(name, default))
        except FileNotFoundError:
            value = os.environ.get(name, default)
        return str(value).strip() if value is not None else ''
    return Settings(setting('GEMINI_API_KEY'),
                    setting('GEMINI_MODEL', 'gemini-3.6-flash'))


def init_usage():
    for key in ('extraction_count', 'ask_count', 'gemini_call_count'):
        st.session_state.setdefault(key, 0)
    st.session_state.setdefault('usage_history', [])
    st.session_state.setdefault('extraction_busy', False)
    if 'extraction_lock' not in st.session_state:
        st.session_state.extraction_lock = threading.Lock()


def request_context(settings):
    def on_request():
        if st.session_state.gemini_call_count >= config.MAX_GEMINI_CALLS_PER_SESSION:
            raise RuntimeError('Session Gemini call limit reached')
        st.session_state.gemini_call_count += 1

    def on_usage(counts):
        if counts:
            st.session_state.usage_history.append(counts)

    return GeminiRequestContext(settings.api_key, settings.model, on_request, on_usage)


def upload_text(uploaded):
    if not uploaded.name.lower().endswith('.txt'):
        raise ValueError('Chỉ chấp nhận file .txt.')
    data = uploaded.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('File vượt giới hạn 1 MB của staging.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Không đọc được file. Vui lòng dùng transcript UTF-8 hoặc UTF-8-SIG.') from None
    if not text.strip():
        raise ValueError('Transcript không được để trống.')
    return text


def as_dict(value):
    return value.model_dump() if hasattr(value, 'model_dump') else value


def json_download(value):
    value = as_dict(value)
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def download_name(meeting_id, kind):
    safe_id = re.sub(r'[^\w.-]+', '_', str(meeting_id or 'meeting')).strip('.') or 'meeting'
    return f'{safe_id}_predicted_{kind}.json'


def redact_error(error, settings):
    text = f'{type(error).__name__}: {error}'
    # Keep useful diagnostics, never credentials in Logs.
    for secret in (settings.api_key, os.environ.get('OPENAI_API_KEY', '')):
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'AIza[\w-]{25,}|(?:sk-|ghp_|github_pat_)[\w-]{20,}', '[REDACTED]', text)
    return text
