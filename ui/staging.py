"""Staging access, upload and download helpers. No extraction business rules."""
from dataclasses import dataclass, field
import hashlib
import hmac
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
    password: str = field(repr=False)
    model: str = 'gemini-3.6-flash'


def read_settings():
    def setting(name, default=''):
        try:
            value = st.secrets.get(name, os.environ.get(name, default))
        except FileNotFoundError:
            value = os.environ.get(name, default)
        return str(value).strip() if value is not None else ''
    return Settings(setting('GEMINI_API_KEY'), setting('APP_PASSWORD'),
                    setting('GEMINI_MODEL', 'gemini-3.6-flash'))


def auth_tag(password):
    return hmac.new(password.encode('utf-8'), b'meeting-staging-session', hashlib.sha256).hexdigest()


def password_matches(supplied, expected):
    return bool(expected) and hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))


def login(password):
    supplied = st.session_state.pop('login_password', '')
    st.session_state.authenticated = password_matches(supplied, password)
    st.session_state.auth_tag = auth_tag(password) if st.session_state.authenticated else None
    st.session_state.login_failed = not st.session_state.authenticated


def require_login(settings):
    if not settings.password or settings.password == 'your_staging_password':
        st.warning('Chưa cấu hình APP_PASSWORD. Staging đã khóa; hãy thêm mật khẩu trong Secrets hoặc environment.')
        st.stop()
    if not settings.api_key or settings.api_key == 'your_api_key_here':
        st.error('Chưa cấu hình GEMINI_API_KEY. Hãy thêm API key trong Secrets hoặc environment để chạy staging.')
        st.stop()
    if not (st.session_state.get('authenticated') and
            st.session_state.get('auth_tag') == auth_tag(settings.password)):
        st.title('Đăng nhập staging')
        with st.form('staging_login'):
            st.text_input('Mật khẩu', type='password', key='login_password')
            st.form_submit_button('Đăng nhập', on_click=login, args=(settings.password,))
        if st.session_state.get('login_failed'):
            st.error('Mật khẩu không đúng. Vui lòng thử lại.')
        st.stop()


def logout():
    # Remove meeting data and access, but keep this session's API budget.
    counters = {key: st.session_state.get(key, 0) for key in
                ('extraction_count', 'ask_count', 'gemini_call_count')}
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state.update(counters)


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
    # Keep useful diagnostics, never credentials even in authenticated Logs.
    for secret in (settings.api_key, settings.password, os.environ.get('OPENAI_API_KEY', '')):
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'AIza[\w-]{25,}|(?:sk-|ghp_|github_pat_)[\w-]{20,}', '[REDACTED]', text)
    return text
