"""Provider boundary only; validation and decisions remain in the shared pipeline."""
import json
import logging
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

QWEN_CONNECTION_MESSAGE = (
    'Không kết nối được Qwen3-8B. Vui lòng khởi động Colab inference API hoặc chọn Gemini API.'
)


class QwenConnectionError(RuntimeError):
    pass


def extract_meeting(provider, meeting_date, transcript, *, meeting_id,
                    meeting_date_evidence=None, gemini_call=None, model_version=None):
    payload = dict(transcript=transcript, meeting_id=meeting_id,
                   meeting_date=meeting_date, meeting_date_evidence=meeting_date_evidence)
    if provider == 'gemini':
        # Reuse the existing SDK, request context, quota handling and retry path.
        if gemini_call is None:
            from src.pipeline import call_llm_with_retry
            gemini_call = call_llm_with_retry
        raw = gemini_call(payload)
        try:
            parsed = json.loads(raw)
            items = parsed.get('items') if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            items = None
        return dict(provider=provider, model_version=model_version,
                    prompt_version='prompt_v1', items=items, raw_output=raw)
    if provider != 'qwen_v6':
        raise ValueError('Provider không hợp lệ.')
    local = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    url = os.environ.get('QWEN_API_URL', local.get('QWEN_API_URL') or '').strip()
    key = os.environ.get('QWEN_API_KEY', local.get('QWEN_API_KEY') or '')
    if not url:
        raise QwenConnectionError(QWEN_CONNECTION_MESSAGE)
    headers = {'ngrok-skip-browser-warning': '1'}
    if key:
        headers['X-API-Key'] = key
    try:
        response = requests.post(url, json={'meeting_date': meeting_date, 'transcript': transcript},
                                 headers=headers,
                                 timeout=180, allow_redirects=False)
    except requests.RequestException:
        raise QwenConnectionError(QWEN_CONNECTION_MESSAGE) from None
    try:
        data = response.json()
    except ValueError:
        logger.warning('Qwen non-JSON response: HTTP status=%s Content-Type=%s body=%r',
                       response.status_code, response.headers.get('Content-Type', ''),
                       response.text[:500])
        raise QwenConnectionError(
            f'Qwen3-8B trả về phản hồi không phải JSON (HTTP {response.status_code}). '
            'Vui lòng kiểm tra endpoint Colab/ngrok; chi tiết đã ghi trong log server.'
        ) from None
    if not 200 <= response.status_code < 300:
        raise QwenConnectionError(QWEN_CONNECTION_MESSAGE)
    if not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('items'), list):
        raise ValueError('Qwen3-8B trả về dữ liệu không hợp lệ (ok/items).')
    if not all(isinstance(data.get(k), str) and data[k] for k in ('model_version', 'prompt_version')):
        raise ValueError('Qwen3-8B thiếu thông tin model_version/prompt_version.')
    raw = json.dumps(dict(meeting_id=meeting_id, meeting_date=meeting_date,
                          meeting_date_evidence=meeting_date_evidence, items=data['items']),
                     ensure_ascii=False)
    return dict(provider=provider, model_version=data['model_version'],
                prompt_version=data['prompt_version'], items=data['items'], raw_output=raw)
