"""语言覆盖模型约束、卡片固定文案和云端配置；中文仍为默认值。"""
from datetime import date
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analysis_prompt import build_analysis_prompt
from cloud_config import build_profile
from digest_language import digest_language, digest_title
from render_digest import render_digest
from run_daily import validate
import enrich_cli

ROOT = Path(__file__).resolve().parents[1]


class LanguageTests(unittest.TestCase):
    def test_default_and_invalid_language(self):
        self.assertEqual(digest_language({}), 'zh')
        self.assertEqual(digest_title({}), '论文日报')
        with self.assertRaisesRegex(ValueError, 'digest_language'):
            validate({'digest_language': 'fr'})
        with self.assertRaisesRegex(ValueError, 'digest_language'):
            build_profile({'DIGEST_LANGUAGE': 'fr'})

    def test_cloud_and_prompt_use_english_without_chinese_length_requirement(self):
        profile = build_profile({'DIGEST_LANGUAGE': 'en'})
        self.assertEqual(profile['digest_language'], 'en')
        self.assertEqual(profile['digest_title'], 'Daily Paper Radar')
        prompt = build_analysis_prompt(profile, [], {})
        self.assertIn('所有面向读者的文本字段必须使用英文', prompt)
        self.assertIn('summary_cn', prompt)
        self.assertNotIn('220–350字中文', prompt)
        self.assertNotIn('中文短标题', prompt)
        self.assertEqual(build_profile({})['digest_language'], 'zh')

    def test_english_all_branches_have_no_chinese_fixed_copy(self):
        paper = json.loads((ROOT / 'examples/papers.en.json').read_text(encoding='utf-8'))['papers'][0]
        paper.update(hf_url='https://huggingface.co/papers/1706.03762', hf_upvotes=2,
                     code_urls=['https://example.org/code'], first_author_affiliation='Example University')
        profile = {'digest_language': 'en', 'render': {'max_detailed': 1},
                   'deadlines': [{'name': 'Example conference', 'full_paper_due': '2026-10-21'}]}
        for mode in ('full', 'concise'):
            for basis in ('abstract', 'fulltext', None):
                paper['analysis_basis'] = basis
                for papers in ([], [paper], [paper, dict(paper, relevance='med'), dict(paper, relevance='low')], [{'title': 'Raw title', 'summary': 'Raw abstract'}]):
                    with self.subTest(mode=mode, basis=basis, count=len(papers)):
                        body = render_digest(papers, date(2026, 10, 22), profile, mode)
                        self.assertIsNone(re.search(r'[\u3400-\u9fff]', body), body)
        body = render_digest([paper], date(2026, 10, 22), profile, 'concise')
        self.assertIn('Limitations / To verify', body)
        self.assertIn('Read in depth', body)
        self.assertIn('Reading basis', body)

    def test_chinese_default_keeps_reading_decision_in_group(self):
        papers = json.loads((ROOT / 'examples/papers.zh.json').read_text(encoding='utf-8'))['papers']
        body = render_digest(papers, date(2026, 10, 22), {}, 'concise')
        for text in ('论文日报', '摘要分析', '局限 / 待核实', '建议精读'):
            self.assertIn(text, body)
        self.assertNotIn('**证据**', body)

    def test_cli_default_model_label_respects_english(self):
        data = json.loads((ROOT / 'examples/papers.en.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            profile = root / 'profile.json'
            profile.write_text(json.dumps({'digest_language': 'en', 'llm_enrich': {'backend': 'codex'}}), encoding='utf-8')
            (root / 'output/raw_papers.json').write_text(json.dumps(data), encoding='utf-8')
            with patch.multiple(enrich_cli, PROFILE=profile, STATE=root), patch.object(enrich_cli, 'call_cli', return_value=json.dumps(data)):
                enrich_cli.main()
            result = json.loads((root / 'output/papers.json').read_text(encoding='utf-8'))
            self.assertEqual(result['llm_enrich']['model'], 'CLI default model')


if __name__ == '__main__':
    unittest.main()
