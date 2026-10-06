import json
import unittest
from unittest.mock import patch, Mock
import requests
from services.extraction_service import extract_meeting, QwenConnectionError
from src.pipeline import process_transcript, PipelineError

class ExtractionServiceTests(unittest.TestCase):
    def extract(self, **kwargs):
        return extract_meeting('qwen_v6', '2026-10-04', 'Transcript',
                               meeting_id='M1', **kwargs)

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':'test-key'})
    def test_qwen_payload_auth_and_shared_pipeline(self):
        response = Mock(status_code=200, json=lambda:dict(ok=True, model_version='v6',prompt_version='prompt_v6',items=[]))
        with patch('services.extraction_service.requests.post', return_value=response) as post, patch('src.pipeline.call_llm') as gemini:
            result = self.extract(meeting_date_evidence={'source':'date'})
            self.assertEqual(result['provider'], 'qwen_v6')
            self.assertEqual(json.loads(result['raw_output'])['meeting_date_evidence'], {'source':'date'})
            raw, validated, final = process_transcript('Transcript','M1','2026-10-04',
                                                      extractor=lambda p: result['raw_output'])
            self.assertEqual(final.meeting_id,'M1')
            self.assertEqual(final.items,[])
            self.assertEqual(post.call_args.kwargs, dict(json={'transcript':'Ngày họp: 04-10-2026\n\nTranscript'},
                headers={'ngrok-skip-browser-warning':'1', 'X-API-Key':'test-key'}, timeout=300,allow_redirects=False))
            gemini.assert_not_called()

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':''})
    def test_failures_never_fallback(self):
        for failure, message in ((requests.Timeout('secret'), '>300 giây'),
                                 (requests.ConnectionError('secret'), 'Không kết nối được Qwen inference API.'),
                                 (Mock(status_code=503, text='Service unavailable'), 'HTTP 503')):
            with patch('services.extraction_service.requests.post') as post, patch('src.pipeline.call_llm') as gemini:
                if isinstance(failure, Exception): post.side_effect=failure
                else: post.return_value=failure
                with self.assertRaises(QwenConnectionError) as error: self.extract()
                self.assertIn(message, str(error.exception))
                self.assertNotIn('secret', str(error.exception))
                self.assertEqual(post.call_count,1)
                gemini.assert_not_called()

    def test_gemini_raw_and_invalid_json_preserved(self):
        for raw in ('not json', '{"items":[]}'):
            call=Mock(return_value=raw)
            result=extract_meeting('gemini',None,'text',meeting_id='M1',gemini_call=call)
            self.assertEqual(result['raw_output'],raw)
            call.assert_called_once()

    def test_qwen_items_still_rejected_by_schema(self):
        raw=json.dumps(dict(meeting_id='M1',meeting_date=None,meeting_date_evidence=None,items=[{'unexpected':'field'}]))
        with self.assertRaises(PipelineError):
            process_transcript('text','M1',None,extractor=lambda p:raw)

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':''})
    def test_ui_selection_no_fallback_and_actual_model_label(self):
        from test_app import make_app, upload
        response=Mock(status_code=200, json=lambda:dict(ok=True,model_version='v6',prompt_version='prompt_v6',items=[]))
        with patch('streamlit.file_uploader',return_value=upload()), patch('services.extraction_service.requests.post',return_value=response) as post, patch('src.pipeline.call_llm') as gemini:
            at=make_app()
            at.radio(key='extraction_provider').set_value('qwen_v6').run()
            post.assert_not_called()
            next(b for b in at.button if b.label=='Run Extraction').click().run()
            self.assertFalse(at.exception)
            post.assert_called_once()
            self.assertFalse(at.session_state['qwen_request_in_progress'])
            self.assertFalse(at.session_state['extraction_busy'])
            at.run()
            at.run()
            post.assert_called_once()
            gemini.assert_not_called()
            self.assertTrue(any('Prompt: prompt_v6' in c.value for c in at.caption))
            self.assertEqual(at.session_state['final_object'].items,[])
            at.radio(key='extraction_provider').set_value('gemini').run()
            self.assertTrue(any('Prompt: prompt_v6' in c.value for c in at.caption))
            gemini.assert_not_called()

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':''})
    def test_non_json_logging_and_skip_header_without_key(self):
        for code in (200, 502):
            response = Mock(status_code=code, headers={'Content-Type':'text/html'},
                            text='x' * 500 + 'DO_NOT_LOG')
            response.json.side_effect = ValueError('not json')
            with patch('services.extraction_service.requests.post', return_value=response) as post, self.assertLogs('services.extraction_service', level='WARNING') as logs:
                with self.assertRaisesRegex(QwenConnectionError, 'không phải JSON'):
                    self.extract()
                self.assertEqual(post.call_args.kwargs['headers'], {'ngrok-skip-browser-warning':'1'})
                self.assertEqual(post.call_args.kwargs['timeout'], 300)
                self.assertIn(str(code), '\n'.join(logs.output))
                self.assertIn('text/html', '\n'.join(logs.output))
                self.assertIn('x' * 500, '\n'.join(logs.output))
                self.assertNotIn('DO_NOT_LOG', '\n'.join(logs.output))

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':''})
    def test_latency_logged_on_success_and_timeout(self):
        response = Mock(status_code=200, json=lambda:dict(ok=True, model_version='v6', prompt_version='prompt_v6', items=[]))
        for failure in (None, requests.Timeout()):
            with patch('services.extraction_service.requests.post', return_value=response, side_effect=failure), patch('services.extraction_service.time.perf_counter', side_effect=[10, 157.25]), self.assertLogs('services.extraction_service', level='INFO') as logs:
                if failure:
                    with self.assertRaises(QwenConnectionError): self.extract()
                else:
                    self.extract()
                self.assertIn('Qwen request latency: 147.25 seconds', '\n'.join(logs.output))
                starts = [line for line in logs.output if 'QWEN CALL START' in line]
                ends = [line for line in logs.output if 'QWEN CALL END' in line]
                self.assertEqual(len(starts), 1)
                self.assertEqual(len(ends), 1)
                self.assertEqual(starts[0].split('request_id=')[1], ends[0].split('request_id=')[1])

    @patch.dict('os.environ', {'QWEN_API_URL':'https://example.test/extract','QWEN_API_KEY':''})
    def test_exact_url_and_http_error_log(self):
        response = Mock(status_code=404, text='x' * 300 + 'NOT_LOGGED', json=lambda: {'detail':'Not Found'})
        with patch('services.extraction_service.requests.post', return_value=response) as post, self.assertLogs('services.extraction_service', level='INFO') as logs:
            with self.assertRaisesRegex(QwenConnectionError, 'HTTP 404'): self.extract()
            self.assertEqual(post.call_args.args[0], 'https://example.test/extract')
            output = '\n'.join(logs.output)
            self.assertIn('Qwen request URL: https://example.test/extract', output)
            self.assertIn('status=404', output)
            self.assertIn('x' * 300, output)
            self.assertNotIn('NOT_LOGGED', output)
