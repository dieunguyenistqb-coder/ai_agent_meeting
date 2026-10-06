"""Provider boundary only; validation and decisions remain in the shared pipeline."""
import json
import logging
import os
import time
from uuid import uuid4
from pathlib import Path

import requests
from dotenv import dotenv_values

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False

QWEN_CONNECTION_MESSAGE = 'Không kết nối được Qwen inference API.'


class QwenConnectionError(RuntimeError):
    pass


def extract_meeting(provider, meeting_date, transcript, *, meeting_id,
                    meeting_date_evidence=None, gemini_call=None, model_version=None, request_id=None):
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
    from src.extraction_normalization import prepare_transcript
    transcript = prepare_transcript(transcript, meeting_date)
    local = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    url = os.environ.get('QWEN_API_URL', local.get('QWEN_API_URL') or '').strip()
    key = os.environ.get('QWEN_API_KEY', local.get('QWEN_API_KEY') or '')
    if not url:
        raise QwenConnectionError(QWEN_CONNECTION_MESSAGE)
    headers = {'ngrok-skip-browser-warning': '1'}
    if key:
        headers['X-API-Key'] = key
    request_id = request_id or str(uuid4())
    logger.info('QWEN CALL START request_id=%s', request_id)
    logger.info('Qwen request URL: %s', url)
    started = time.perf_counter()
    try:
        response = requests.post(url, json={'transcript': transcript},
                                 headers=headers,
                                 timeout=300, allow_redirects=False)
    except requests.Timeout:
        raise QwenConnectionError('Qwen xử lý quá thời gian cho phép (>300 giây).') from None
    except requests.ConnectionError:
        raise QwenConnectionError(QWEN_CONNECTION_MESSAGE) from None
    except requests.RequestException:
        raise QwenConnectionError('Không thể gửi yêu cầu tới Qwen inference API. Vui lòng kiểm tra cấu hình kết nối.') from None
    finally:
        logger.info('Qwen request latency: %.2f seconds', time.perf_counter() - started)
        logger.info('QWEN CALL END request_id=%s', request_id)
    if response.status_code != 200:
        logger.warning('Qwen HTTP response: status=%s body=%r',
                       response.status_code, response.text[:300])
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
    if response.status_code != 200:
        raise QwenConnectionError(
            f'Qwen inference API trả về HTTP {response.status_code}. Vui lòng kiểm tra dịch vụ hoặc thử lại sau.')
    if not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('items'), list):
        raise ValueError('Qwen3-8B trả về dữ liệu không hợp lệ (ok/items).')
    logger.info('QWEN RAW ITEM COUNT: %s; items=%r', len(data['items']),
                [(x.get('item_id'), x.get('description')) for x in data['items'] if isinstance(x, dict)])
    if not all(isinstance(data.get(k), str) and data[k] for k in ('model_version', 'prompt_version')):
        raise ValueError('Qwen3-8B thiếu thông tin model_version/prompt_version.')
    raw = json.dumps(dict(meeting_id=meeting_id, meeting_date=meeting_date,
                          meeting_date_evidence=meeting_date_evidence, items=data['items']),
                     ensure_ascii=False)
    return dict(provider=provider, model_version=data['model_version'],
                prompt_version=data['prompt_version'], items=data['items'], raw_output=raw)
