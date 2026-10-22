"""来源融合、智能分析、凭据加载与公开发布包回归。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_huggingface import normalize_entry, collect_huggingface
from fetch_papers import select_and_merge
from runtime import load_env, redact
from analysis_prompt import build_analysis_prompt, validate_analysis
from render_digest import render_digest
from build_release import release_files, ROOT


def hf_entry(aid, votes, title='Unrelated topic'):
    return {'paper': {'id': aid, 'title': title, 'summary': 'A concrete method.', 'upvotes': votes,
                      'authors': [{'name': 'Author'}]}, 'publishedAt': '2026-09-28T00:00:00Z'}


class SourceTests(unittest.TestCase):
    def test_merges_versions_and_retains_both_sources(self):
        hf = normalize_entry(hf_entry('2609.00001v2', 25))
        arxiv = {**hf, 'title': 'Agent reasoning', 'categories': ['cs.AI'], 'sources': ['arxiv']}
        for k in list(arxiv):
            if k.startswith('hf_'):
                del arxiv[k]
        profile = {'keywords': ['agent'], 'sources': {'arxiv': {'enabled': True}, 'huggingface': {'enabled': True}}}
        result = select_and_merge([arxiv], [hf], profile)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sources'], ['arxiv', 'huggingface'])
        self.assertEqual(result[0]['hf_upvotes'], 25)
        self.assertEqual(result[0]['categories'], ['cs.AI'])

    def test_hf_curated_bypasses_keywords_but_obeys_votes_and_cap(self):
        papers = [normalize_entry(hf_entry(f'2609.0000{i}', v)) for i, v in enumerate((1, 10, 30), 1)]
        profile = {'keywords': ['agent'], 'sources': {'huggingface': {'enabled': True, 'min_upvotes': 5, 'max_papers': 1}}}
        result = select_and_merge([], papers, profile)
        self.assertEqual([p['hf_upvotes'] for p in result], [30])
        profile['sources']['huggingface']['keyword_filter'] = True
        self.assertEqual(select_and_merge([], papers, profile), [])

    def test_hf_lookback_deduplicates(self):
        with patch('fetch_huggingface.fetch_daily', side_effect=[[hf_entry('2609.00001', 12)], [hf_entry('2609.00001', 8)]]), patch('fetch_huggingface.time.sleep'):
            result = collect_huggingface({'lookback_days': 2})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hf_upvotes'], 12)

    def test_partial_source_failure_is_not_silently_ignored(self):
        with patch('fetch_huggingface.fetch_daily', side_effect=RuntimeError('network unavailable')):
            with self.assertRaises(RuntimeError):
                collect_huggingface({'lookback_days': 2})


class EnvironmentTests(unittest.TestCase):
    def test_dotenv_load_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            value = uuid4().hex
            path = Path(folder) / '.env'
            path.write_text('RADAR_TEST_TOKEN=' + value + '\nEXISTING=from_file\nLITERAL="$(command) # untouched"\n', encoding='utf-8-sig')
            os.environ['EXISTING'] = 'from_environment'
            load_env(path)
            self.assertEqual(os.environ['RADAR_TEST_TOKEN'], value)
            self.assertEqual(os.environ['EXISTING'], 'from_environment')
            self.assertEqual(os.environ['LITERAL'], '$(command) # untouched')
            self.assertNotIn(value, redact('error ' + value))

    def test_bad_dotenv_does_not_expose_content(self):
        with tempfile.TemporaryDirectory() as folder:
            value = uuid4().hex
            path = Path(folder) / '.env'
            path.write_text('invalid name=' + value)
            with self.assertRaises(ValueError) as error:
                load_env(path)
            self.assertNotIn(value, str(error.exception))

    def test_release_excludes_runtime_and_personal_files(self):
        files = {p.relative_to(ROOT).as_posix() for p in release_files()}
        self.assertTrue({'README.md', 'README.zh-CN.md', 'VERSION', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md'}.issubset(files))
        self.assertIn('.env.example', files)
        self.assertIn('LICENSE', files)
        self.assertNotIn('.env', files)
        self.assertNotIn('config/profile.json', files)
        self.assertFalse(any(p.startswith(('state/', 'dist/')) for p in files))


class AnalysisTests(unittest.TestCase):
    def test_evidence_and_reading_suggestion_are_required(self):
        result = {'arxiv_id': '2609.00001', 'relevance': 'high', 'short_title': '方法', 'affiliations': '?',
                  'summary_cn': '方法机制', 'insight_for_us': '与研究有关', 'one_liner': '一句话看点',
                  'evidence': '摘要未提供充分定量证据', 'limitations': '需要核实训练成本',
                  'reading_priority': 'deep_read', 'reading_reason': '先查看方法与基线对照'}
        validate_analysis(result)
        result['evidence'] = ''
        with self.assertRaises(ValueError):
            validate_analysis(result)

    def test_render_exposes_hf_and_reading_decision(self):
        paper = normalize_entry(hf_entry('2609.00001', 42))
        paper.update(relevance='high', summary_cn='中文方法', one_liner='一句话看点', evidence='基线对比',
                     limitations='待核实成本', reading_priority='deep_read', reading_reason='先读方法')
        markdown = render_digest([paper], date(2026, 9, 28), {})
        for value in ('42 票', 'huggingface.co/papers/2609.00001', '待核实成本', '建议精读', '先读方法'):
            self.assertIn(value, markdown)

    def test_relevance_precedes_vote_count(self):
        high = {**normalize_entry(hf_entry('2609.00001', 1, 'Relevant paper')), 'relevance': 'high'}
        med = {**normalize_entry(hf_entry('2609.00002', 100, 'Popular paper')), 'relevance': 'med'}
        markdown = render_digest([med, high], date(2026, 9, 28), {})
        self.assertLess(markdown.index('Relevant paper'), markdown.index('Popular paper'))

class ApiTests(unittest.TestCase):
    def test_custom_endpoint_and_optional_temperature(self):
        import io
        from enrich_llm import call_llm
        response = {'choices': [{'message': {'content': '{"papers": []}'}}]}
        cfg = {'require_api_key': False}
        env = {'LLM_BASE_URL': 'http://localhost:12345/custom/chat/completions', 'LLM_MODEL_NAME': 'configured-model',
               'LLM_OFFPEAK_ONLY': 'false'}
        with patch.dict(os.environ, env, clear=True), patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
            self.assertEqual(call_llm(cfg, 'system', 'user'), '{"papers": []}')
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, env['LLM_BASE_URL'])
        self.assertNotIn('temperature', json.loads(req.data))
        self.assertNotIn('Authorization', req.headers)

    def test_failed_analysis_is_not_a_successful_low_relevance_result(self):
        from enrich_llm import enrich_one
        with patch('enrich_llm.call_llm', return_value='{"papers": []}'):
            result = enrich_one({}, {}, {'arxiv_id': '2609.00001'}, '')
        self.assertIn('_llm_error', result)


if __name__ == '__main__':
    unittest.main()
