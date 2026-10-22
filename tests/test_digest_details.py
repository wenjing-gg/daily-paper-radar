"""一作机构不能误取合作者机构；日报和飞书卡片保留溯源与清晰分隔。"""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_metadata import parse_metadata, enrich_metadata
from render_digest import _read_papers, render_digest, clean_title
from sinks.feishu_bot import _build_card
from fetch_huggingface import normalize_entry
from fetch_papers import select_and_merge


class DigestDetailsTests(unittest.TestCase):
    def test_affiliation_is_scoped_to_first_named_author(self):
        html = '''<div class="ltx_authors"><span class="ltx_role_author">
        <span class="ltx_personname">A Author</span>
        <span class="ltx_role_affiliation">Affiliation: University A</span></span>
        <span class="ltx_role_author"><span class="ltx_personname">B Author</span>
        <span class="ltx_role_affiliation">University B</span></span></div>
        <div class="ltx_abstract"><a href="https://github.com/example/project">Code</a></div>
        <a href="https://github.com/example/reference">Referenced project</a>'''
        metadata = parse_metadata(html, 'A Author')
        self.assertEqual(metadata['first_author_affiliation'], 'University A')
        self.assertEqual(metadata['code_urls'], ['https://github.com/example/project'])
        self.assertNotIn('first_author_affiliation', parse_metadata(html, 'Other Author'))

    def test_unavailable_metadata_does_not_remove_paper_or_abstract_link(self):
        paper = {'arxiv_id': '2609.00001', 'summary': 'Code: https://github.com/example/project.'}
        with patch('paper_metadata.urllib.request.urlopen', side_effect=TimeoutError):
            result = enrich_metadata(paper)
        self.assertEqual(result['metadata_status'], 'unavailable')
        self.assertEqual(result['code_urls'], ['https://github.com/example/project'])
        self.assertNotIn('first_author_affiliation', result)

    def test_recorded_model_and_card_separators(self):
        paper = {'arxiv_id': '2609.00001', 'short_title': '26.09-arxiv-?-新方法',
                 'title': 'A paper', 'relevance': 'high', 'summary_cn': '长摘要',
                 'one_liner': '一句话概览', 'code_urls': ['https://github.com/example/project']}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'papers.json'
            path.write_text(json.dumps({'papers': [paper, dict(paper, arxiv_id='2609.00002')],
                                        'llm_enrich': {'model': 'configured-model'}}), encoding='utf-8')
            papers, _ = _read_papers(path)
        md = render_digest(papers, date(2026, 9, 29), {}, mode='concise')
        self.assertIn('总结模型：configured-model', md)
        self.assertNotIn('🏛️', md)
        self.assertIn('💻 **代码**', md)
        self.assertNotIn('arxiv-?', md)
        self.assertNotIn('一句话概览', md)
        self.assertIn('长摘要', md)
        self.assertLess(md.index('总结模型'), md.index('**1.'))
        self.assertIn('🔥🔥🔥', md)
        self.assertNotIn('★', md)
        elements = _build_card('日报', md, 'blue')['card']['elements']
        self.assertGreaterEqual(sum(e['tag'] == 'hr' for e in elements), 2)
        self.assertEqual(sum(e.get('content', '').startswith(('**1.', '**2.')) for e in elements), 2)

    def test_seen_papers_do_not_consume_daily_candidate_quota(self):
        papers = [normalize_entry({'paper': {'id': f'2609.0000{i}', 'upvotes': votes}})
                  for i, votes in ((1, 20), (2, 10))]
        profile = {'sources': {'huggingface': {'enabled': True, 'max_papers': 1}}}
        selected = select_and_merge([], papers, profile, {'2609.00001'})
        self.assertEqual([p['arxiv_id'] for p in selected], ['2609.00002'])

    def test_title_uses_only_evidenced_venue_and_first_author(self):
        paper = dict(arxiv_id='2503.00001', short_title='大模型推理，通过反馈修订工具库',
                     first_author_affiliation='Tsinghua University；Shanghai AI Laboratory',
                     venue='ACL', venue_source='https://example.org/paper')
        self.assertEqual(clean_title(paper, date(2026, 9, 29)), '26.09.29-ACL-清华/上海AI Lab-大模型推理，通过反馈修订工具库')
        paper.pop('venue_source')
        self.assertNotIn('ACL', clean_title(paper))

    def test_low_relevance_list_is_limited(self):
        papers = [dict(arxiv_id=f'2609.{i:05d}', short_title=f'低相关研究{i}', relevance='low') for i in range(12)]
        md = render_digest(papers, date(2026, 9, 29), {})
        self.assertEqual(md.count('[26.09.29-低相关研究'), 5)
        self.assertIn('**12**', md)
