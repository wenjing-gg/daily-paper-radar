"""文档归档只追加，失败后重试未完成段，链接和标题可阅读。"""
from datetime import date
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sinks import feishu_doc
from cloud_config import build_profile
from enrich_llm import enrich_one


class DocTests(unittest.TestCase):
    def test_document_url_and_markdown(self):
        self.assertEqual(feishu_doc.document_id('https://example.feishu.cn/docx/DocumentExample?from=share'), 'DocumentExample')
        self.assertEqual(feishu_doc.document_id('https://example.feishu.cn/wiki/Example'), 'Example')
        with self.assertRaises(ValueError):
            feishu_doc.document_id('https://example.feishu.cn/docs/Example')
        blocks = feishu_doc.blocks('日期日报', '**原始标题**\n\n**1. 方法**\n[论文](https://arxiv.org/abs/2609.00001)')
        self.assertEqual([b['block_type'] for b in blocks], [3, 4, 2])
        self.assertEqual(blocks[-1]['text']['elements'][0]['text_run']['text_element_style']['link']['url'], 'https://arxiv.org/abs/2609.00001')

    def test_partial_append_resumes_without_repeating_successful_chunks(self):
        temporary_secret = secrets.token_urlsafe(24)
        env = dict(FEISHU_APP_ID=secrets.token_hex(8), FEISHU_APP_SECRET=temporary_secret, FEISHU_DOC_ID='DocumentExample')
        append_calls = []
        fail = [True]
        def request(path, payload, token=None):
            if '/auth/' in path:
                return {'tenant_access_token': temporary_secret}
            self.assertEqual(payload['index'], -1)
            append_calls.append(path)
            if len(append_calls) == 2 and fail[0]:
                fail[0] = False
                raise RuntimeError('模拟第二段失败')
            return {'code': 0}
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', env), patch.object(feishu_doc, 'STATE', Path(folder)), patch.object(feishu_doc, 'CHUNK_SIZE', 2), patch.object(feishu_doc, 'request', side_effect=request), patch.object(feishu_doc.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                feishu_doc.send('日报', '一\n二\n三\n四', {}, {}, date.today())
            feishu_doc.send('日报', '一\n二\n三\n四', {}, {}, date.today())
            self.assertEqual(len(append_calls), 4)
            self.assertEqual(append_calls[1], append_calls[2])
            self.assertNotIn(temporary_secret, (Path(folder)/'output/doc_delivery.json').read_text())
            feishu_doc.send('日报', '一\n二\n三\n四', {}, {}, date.today())
            self.assertEqual(len(append_calls), 4)

    def test_wiki_resolves_document_before_append(self):
        temporary_secret = secrets.token_urlsafe(24)
        env = dict(FEISHU_APP_ID=secrets.token_hex(8), FEISHU_APP_SECRET=temporary_secret,
                   FEISHU_DOC_ID='https://example.feishu.cn/wiki/Example')
        def request(path, payload=None, token=None):
            if '/auth/' in path:
                return {'tenant_access_token': temporary_secret}
            if '/wiki/' in path:
                self.assertIsNone(payload)
                return {'data': {'node': {'obj_type': 'docx', 'obj_token': 'ResolvedDocument'}}}
            self.assertIn('/documents/ResolvedDocument/blocks/ResolvedDocument/', path)
            self.assertEqual(payload['index'], -1)
            return {'code': 0}
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', env), patch.object(feishu_doc, 'STATE', Path(folder)), patch.object(feishu_doc, 'request', side_effect=request):
            self.assertEqual(feishu_doc.send('日报', '正文', {}, {}, date.today())['parts'], 1)

    def test_cloud_archive_is_opt_in(self):
        self.assertEqual(len(build_profile({})['sinks']), 1)
        self.assertEqual(build_profile({'FEISHU_DOC_ID': 'DocumentExample'})['sinks'][1]['type'], 'feishu_doc')

    def test_invalid_analysis_retries_only_the_failed_paper(self):
        with patch('enrich_llm._enrich_once', side_effect=[{'_llm_error': 'ValueError'}, {'summary_cn': '成功'}]) as attempt:
            self.assertEqual(enrich_one({}, {}, {'arxiv_id': '2609.00001'}, '')['summary_cn'], '成功')
            self.assertEqual(attempt.call_count, 2)
