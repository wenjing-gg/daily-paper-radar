"""通用配置与两种原生协议的契约测试；不连接真实模型。"""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from llm_api import build_request, resolve_settings, response_text
from enrich_llm import call_llm
from run_daily import validate


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.env = {'LLM_BASE_URL': 'https://api.openai.com', 'LLM_MODEL_NAME': 'configured-model', 'LLM_API_KEY': uuid4().hex}
        self.patch = patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        os.environ['LLM_OFFPEAK_ONLY'] = 'false'  # 契约测试不依赖当前是否处于低峰时段。
        self.addCleanup(self.patch.stop)

    def test_openai_headers_and_body(self):
        settings, headers, body = build_request({}, 'system', 'user')
        self.assertEqual(settings['endpoint'], 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer ' + self.env['LLM_API_KEY'])
        self.assertNotIn('x-api-key', headers)
        self.assertEqual(body['model'], self.env['LLM_MODEL_NAME'])
        self.assertEqual(body['messages'][0], {'role': 'system', 'content': 'system'})

    def test_anthropic_headers_body_and_text_blocks(self):
        os.environ['LLM_BASE_URL'] = 'https://api.anthropic.com/v1/'
        response = {'content': [{'type': 'thinking', 'thinking': 'internal'}, {'type': 'text', 'text': '正文'}], 'stop_reason': 'end_turn'}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
            self.assertEqual(call_llm({}, 'system', 'user'), '正文')
        req = request.call_args.args[0]
        headers = {k.lower(): v for k, v in req.headers.items()}
        body = json.loads(req.data)
        self.assertEqual(req.full_url, 'https://api.anthropic.com/v1/messages')
        self.assertEqual(headers['x-api-key'], self.env['LLM_API_KEY'])
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        self.assertNotIn('authorization', headers)
        self.assertEqual(body['system'], 'system')
        self.assertEqual(body['max_tokens'], 4096)
        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'user'}])

    def test_endpoint_and_gateway_prefix_preserved(self):
        for url, protocol, expected in [
            ('https://gateway.example/api/v4', 'auto', 'https://gateway.example/api/v4/chat/completions'),
            ('https://gateway.example/v1/messages', 'auto', 'https://gateway.example/v1/messages'),
            ('https://gateway.example/anthropic/v1', 'anthropic', 'https://gateway.example/anthropic/v1/messages'),
        ]:
            with self.subTest(url=url):
                os.environ['LLM_BASE_URL'] = url
                self.assertEqual(resolve_settings({'protocol': protocol})['endpoint'], expected)

    def test_claude_model_through_openai_gateway_does_not_switch_protocol(self):
        os.environ['LLM_BASE_URL'] = 'https://gateway.example/v1'
        os.environ['LLM_MODEL_NAME'] = 'claude-provider-model'
        self.assertEqual(resolve_settings({})['protocol'], 'openai')

    def test_missing_each_required_environment_value_fails(self):
        for name in self.env:
            with self.subTest(name=name), patch.dict(os.environ, {name: ''}):
                with self.assertRaises(ValueError):
                    resolve_settings({})

    def test_legacy_json_cannot_override_unified_environment(self):
        settings = resolve_settings({'base_url': 'https://old.example', 'model': 'old-model'})
        self.assertEqual(settings['model'], 'configured-model')
        self.assertEqual(settings['base_url'], self.env['LLM_BASE_URL'])

    def test_conflicting_protocol_is_rejected(self):
        os.environ['LLM_BASE_URL'] = 'https://gateway.example/v1/messages'
        with self.assertRaises(ValueError):
            resolve_settings({'protocol': 'openai'})

    def test_truncated_or_missing_output_fails(self):
        for data, protocol in [
            ({'content': [{'type': 'text', 'text': '{}'}], 'stop_reason': 'max_tokens'}, 'anthropic'),
            ({'content': []}, 'anthropic'),
            ({'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}, 'openai'),
        ]:
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                response_text(data, protocol)

    def test_api_backend_preflight_uses_unified_environment(self):
        profile = {'keywords': ['agent'], 'llm_enrich': {'backend': 'api', 'api': {}}, 'sinks': []}
        self.assertEqual(validate(profile), 'api')


if __name__ == '__main__':
    unittest.main()
