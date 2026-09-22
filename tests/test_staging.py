import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import config
from src import llm_client, pipeline
from src.request_context import GeminiRequestContext, current_request, gemini_request, usage_counts
from ui import staging
from test_app import APP, TEST_PASSWORD, make_app, navigate, response, upload


class StagingTests(unittest.TestCase):
    def test_missing_settings_block_app(self):
        for api_key, password, expected in [('', TEST_PASSWORD, 'GEMINI_API_KEY'),
                                            ('mock-key', '', 'APP_PASSWORD')]:
            at = AppTest.from_file(APP, default_timeout=15)
            at.secrets['GEMINI_API_KEY'] = api_key
            at.secrets['APP_PASSWORD'] = password
            with patch.object(pipeline, 'call_llm') as llm:
                at.run()
            self.assertFalse(at.exception)
            self.assertFalse(at.get('file_uploader'))
            self.assertFalse(at.button)
            self.assertTrue(any(expected in e.value for e in list(at.error) + list(at.warning)))
            llm.assert_not_called()

    def test_login_logout_clears_data_preserves_budget(self):
        at = AppTest.from_file(APP, default_timeout=15)
        at.secrets.update(APP_PASSWORD=TEST_PASSWORD, GEMINI_API_KEY='mock-key')
        with patch.object(pipeline, 'call_llm') as llm:
            at.run()
            self.assertFalse(at.get('file_uploader'))
            at.text_input(key='login_password').set_value('wrong')
            at.button[0].click().run()
            self.assertTrue(at.error)
            at.text_input(key='login_password').set_value(TEST_PASSWORD)
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.session_state['authenticated'])
            at.session_state['extraction_count'] = 2
            at.session_state['raw_output'] = 'private meeting data'
            next(b for b in at.button if b.key == 'logout').click().run()
            self.assertFalse(at.get('file_uploader'))
            self.assertEqual(at.session_state['extraction_count'], 2)
            self.assertNotIn('raw_output', at.session_state)
            llm.assert_not_called()

    def test_upload_guards(self):
        cases = [('file.txt', b'', 'trống'), ('file.json', b'{}', '.txt'),
                 ('file.txt', b'\xff', 'UTF-8'), ('file.txt', b'a' * (1024 * 1024 + 1), '1 MB')]
        for name, data, expected in cases:
            with self.subTest(name=name, expected=expected), patch('streamlit.file_uploader',
                    return_value=SimpleNamespace(name=name, getvalue=lambda: data)), patch.object(pipeline, 'call_llm') as llm:
                at = make_app()
                self.assertFalse(at.exception)
                self.assertTrue(next(b for b in at.button if b.label == 'Run Extraction').disabled)
                self.assertTrue(any(expected in e.value for e in at.error))
                llm.assert_not_called()
        self.assertEqual(staging.upload_text(SimpleNamespace(name='ok.txt', getvalue=lambda: b'\xef\xbb\xbfhello')), 'hello')

    def test_downloads_and_budget_no_rerun_calls(self):
        with patch('streamlit.file_uploader', return_value=upload()), patch.object(pipeline, 'call_llm', side_effect=response) as llm:
            at = make_app()
            at.button[0].click().run()
            self.assertEqual(at.session_state['extraction_count'], 1)
            navigate(at, 'Validation & JSON')
            self.assertEqual([d.label for d in at.get('download_button')], ['Download Raw JSON', 'Download Final JSON'])
            self.assertEqual(json.loads(staging.json_download(at.session_state['final_object']))['meeting_id'], 'M001')
            self.assertEqual(staging.download_name('M001', 'raw'), 'M001_predicted_raw.json')
            self.assertEqual(staging.json_download({'text': 'Tiếng Việt'}).decode().count('Tiếng Việt'), 1)
            navigate(at, 'Transcript')
            at.session_state['extraction_count'] = config.MAX_EXTRACTIONS_PER_SESSION
            at.run()
            self.assertTrue(at.button[0].disabled)
            self.assertEqual(llm.call_count, 1)

    def test_busy_guard_and_error_redaction(self):
        settings = staging.Settings('mock-sensitive-key', TEST_PASSWORD)
        redacted = staging.redact_error(RuntimeError(settings.api_key + ' ' + settings.password), settings)
        self.assertNotIn(settings.api_key, redacted)
        self.assertNotIn(settings.password, redacted)
        with patch('streamlit.file_uploader', return_value=upload()), patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            lock = at.session_state['extraction_lock']
            lock.acquire()
            try:
                at.button[0].click().run()
            finally:
                lock.release()
            llm.assert_not_called()
            self.assertEqual(at.session_state['extraction_count'], 0)

    def test_context_and_usage_sdk_mock(self):
        observer, usage = Mock(), Mock()
        context = GeminiRequestContext('mock-key', 'gemini-3.6-flash', observer, usage)
        from google import genai
        with patch.object(genai, 'Client') as client:
            client.return_value.models.generate_content.return_value = SimpleNamespace(
                text='{}', usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, total_token_count=15))
            with gemini_request(context):
                self.assertEqual(llm_client.call_llm(dict(transcript='demo', meeting_id='DEMO', meeting_date=None)), '{}')
            self.assertIsNone(current_request.get())
            self.assertEqual(client.call_args.kwargs['http_options']['timeout'], 90000)
            self.assertEqual(client.return_value.models.generate_content.call_args.kwargs['model'], 'gemini-3.6-flash')
            observer.assert_called_once()
            usage.assert_called_once_with(dict(input_tokens=10, output_tokens=5, total_tokens=15))
        self.assertEqual(usage_counts(None), {})
        self.assertEqual(usage_counts({'thoughts_token_count': 3}), {'thinking_tokens': 3})

    def test_sdk_retry_usage_and_call_budget(self):
        from google import genai
        from google.genai.errors import ServerError
        final_response = SimpleNamespace(text=response(dict(meeting_id='M001', meeting_date=None,
            meeting_date_evidence=None)), usage_metadata={'prompt_token_count': 3, 'total_token_count': 8})
        with patch('streamlit.file_uploader', return_value=upload()), patch.object(genai, 'Client') as client, patch.object(pipeline.time, 'sleep'):
            client.return_value.models.generate_content.side_effect = [ServerError(503, {}), final_response]
            at = make_app()
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['gemini_call_count'], 2)
            self.assertEqual(at.session_state['extraction_count'], 1)
            self.assertEqual(at.session_state['usage_history'], [{'input_tokens': 3, 'total_tokens': 8}])
            at.session_state['gemini_call_count'] = config.MAX_GEMINI_CALLS_PER_SESSION
            at.button[0].click().run()
            self.assertEqual(client.return_value.models.generate_content.call_count, 2)
            self.assertIn('giới hạn', at.session_state['user_error_message'])

    def test_timeout_is_friendly(self):
        with patch('streamlit.file_uploader', return_value=upload()), patch.object(pipeline, 'call_llm', side_effect=TimeoutError('technical timeout')):
            at = make_app()
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertIn('phản hồi quá lâu', at.error[0].value)
            self.assertFalse(at.session_state['extraction_busy'])

    def test_secrets_precedence_and_env_fallback(self):
        with patch.object(staging.st, 'secrets', {'GEMINI_API_KEY': 'mock-cloud', 'APP_PASSWORD': 'test-cloud'}), patch.dict(
                os.environ, {'GEMINI_API_KEY': 'mock-env', 'APP_PASSWORD': 'test-env'}, clear=True):
            settings = staging.read_settings()
            self.assertEqual(settings.api_key, 'mock-cloud')
            self.assertEqual(settings.model, 'gemini-3.6-flash')
        with patch.object(staging.st, 'secrets', {}), patch.dict(os.environ, {'GEMINI_API_KEY': 'mock-env'}, clear=True):
            self.assertEqual(staging.read_settings().api_key, 'mock-env')


if __name__ == '__main__':
    unittest.main()
