"""来源准入先于付费摘要；不猜机构、不把个人作者数量当机构身份。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from source_gate import apply_gate, matches, load_policy
from affiliation_pdf import extract_evidence, enrich_pdf_affiliation
from fetch_papers import select_and_merge
import fetch_papers
from runtime import write_json


class SourceGateTests(unittest.TestCase):
    def paper(self, org='', **extra):
        return dict(arxiv_id='2609.00001', authors='A Author', first_author_affiliation=org,
                    affiliation_source='https://arxiv.org/html/2609.00001' if org else '', **extra)

    def test_accepts_ranked_or_listed_org_and_rejects_individual_and_unknown(self):
        cfg = {'enabled': True}
        for org in ['Tsinghua University', 'Meta AI', 'Department of Computing, Imperial College London']:
            accepted, report = apply_gate([self.paper(org)], cfg)
            self.assertEqual(len(accepted), 1)
        for org in ['', 'Independent Researcher', 'University of Illinois at Chicago', 'Unknown Lab', 'Indiana University of Pennsylvania']:
            accepted, report = apply_gate([self.paper(org)], cfg)
            self.assertEqual(accepted, [], org)
            self.assertEqual(report['rejected'], 1)
        self.assertFalse(matches('Submitted by an individual', ['MIT']))
        self.assertFalse(matches('The Chinese University of Hong Kong', ['University of Hong Kong']))

    def test_code_preference_is_not_an_open_source_license_claim(self):
        a = self.paper('Meta', code_urls=[])
        b = dict(a, arxiv_id='2609.00002', code_urls=['https://github.com/example/project'])
        accepted, _ = apply_gate([a, b], {'enabled': True, 'code_policy': 'prefer'})
        self.assertEqual([p['arxiv_id'] for p in accepted], [b['arxiv_id'], a['arxiv_id']])
        self.assertEqual(accepted[0]['source_gate']['code_status'], 'link_found_unverified')
        accepted, report = apply_gate([a], {'enabled': True, 'code_policy': 'required'})
        self.assertEqual(report['decisions'][0]['reason'], 'no_code_link')

    def test_qs_year_ties_and_invalid_configuration(self):
        ranking, _, _ = load_policy({})
        self.assertEqual(ranking['edition'], 2027)
        self.assertTrue(all(p['rank'] <= 100 for p in ranking['universities']))
        self.assertEqual(len([p for p in ranking['universities'] if p['rank'] == 100]), 2)
        with self.assertRaises(ValueError):
            load_policy({'code_policy': 'guess'})
        with self.assertRaises(ValueError):
            load_policy({'max_qs_rank': 101})

    def test_gate_does_not_consume_hf_quota_before_screening(self):
        profile = {'source_gate': {'enabled': True}, 'keywords': [],
                   'sources': {'huggingface': {'enabled': True, 'max_papers': 1}}}
        a = self.paper('Unknown Lab', hf_upvotes=20, sources=['huggingface'], summary='')
        b = dict(self.paper('Tsinghua University', hf_upvotes=10, sources=['huggingface'], summary=''), arxiv_id='2609.00002')
        candidates = select_and_merge([], [a, b], profile)
        self.assertEqual(len(candidates), 2)
        accepted, _ = apply_gate(candidates, profile['source_gate'])
        self.assertEqual([p['arxiv_id'] for p in accepted], [b['arxiv_id']])

    def test_fetch_output_contains_only_approved_papers_before_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / 'profile.json'
            write_json(profile, {'source_gate': {'enabled': True}, 'paper_metadata': {'enabled': True},
                                'sources': {'huggingface': {'enabled': True, 'max_papers': 1}}})
            candidates = [self.paper('Independent Researcher', hf_upvotes=20, summary='', sources=['huggingface']),
                          dict(self.paper('Meta', hf_upvotes=10, summary='', sources=['huggingface']), arxiv_id='2609.00002')]
            with patch.multiple(fetch_papers, PROFILE=profile, STATE=root), patch.object(fetch_papers, 'collect_huggingface', return_value=candidates), patch.object(fetch_papers, 'enrich_metadata', side_effect=lambda p:p), patch.object(fetch_papers.time, 'sleep'):
                fetch_papers.main()
            payload = json.loads((root / 'output/raw_papers.json').read_text())
            self.assertEqual(payload['new_count'], 1)
            self.assertEqual(payload['papers'][0]['first_author_affiliation'], 'Meta')
            self.assertEqual(payload['source_gate']['rejected'], 1)

    def test_pdf_result_requires_matching_author_and_verbatim_evidence(self):
        text = 'A Author 1\n1 Tsinghua University\nB Author 2\n2 Unknown Lab'
        result = {'matched_author': 'A Author', 'affiliations': [{'name': 'Tsinghua University', 'evidence': '1 Tsinghua University'}]}
        self.assertEqual(len(extract_evidence(result, text, 'A Author')), 1)
        self.assertEqual(extract_evidence(result, text, 'B Author'), [])
        result['affiliations'][0]['name'] = 'Imaginary University'
        self.assertEqual(extract_evidence(result, text, 'A Author'), [])

    def test_pdf_recognition_cached_and_model_not_recalled(self):
        with tempfile.TemporaryDirectory() as folder, patch('affiliation_pdf.STATE', Path(folder)), patch('affiliation_pdf.first_page_text', return_value='A Author\n1 Tsinghua University'), patch('enrich_llm.call_llm', return_value=json.dumps({'matched_author': 'A Author', 'affiliations': [{'name': 'Tsinghua University', 'evidence': '1 Tsinghua University'}]})) as call:
            profile = {'llm_enrich': {'backend': 'api', 'api': {}}}
            for _ in range(2):
                result = enrich_pdf_affiliation(self.paper(), profile)
                self.assertEqual(result['first_author_affiliation'], 'Tsinghua University')
            self.assertEqual(call.call_count, 1)
