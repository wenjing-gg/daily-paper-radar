"""错峰边界、夏冬令时例外、分离投递与单篇缓存回归。"""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import sys
import unittest
import json
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from llm_budget import assert_offpeak, us_standard_time
from cloud_run import late_publish_due
from runtime import write_json
from render_digest import announce_window
from datetime import date
import run_daily
import enrich_llm


class LateDeliveryTests(unittest.TestCase):
    def test_summer_delayed_analysis_catches_up_without_peak_override(self):
        env = {'ALLOW_LATE_PUBLISH': 'true', 'LLM_OFFPEAK_ONLY': 'true'}
        self.assertFalse(late_publish_due(env, datetime.fromisoformat('2026-09-30T09:29:59+08:00')))
        self.assertTrue(late_publish_due(env, datetime.fromisoformat('2026-09-30T09:30:00+08:00')))
        self.assertTrue(late_publish_due(env, datetime.fromisoformat('2026-09-30T13:33:00+08:00')))
        self.assertEqual(env['LLM_OFFPEAK_ONLY'], 'true')

    def test_winter_manual_and_custom_target(self):
        self.assertFalse(late_publish_due({'ALLOW_LATE_PUBLISH': 'true'}, datetime.fromisoformat('2026-12-01T09:20:00+08:00')))
        self.assertTrue(late_publish_due({'ALLOW_LATE_PUBLISH': 'true'}, datetime.fromisoformat('2026-12-01T09:30:00+08:00')))
        self.assertFalse(late_publish_due({}, datetime.fromisoformat('2026-09-30T13:33:00+08:00')))
        self.assertFalse(late_publish_due({'ALLOW_LATE_PUBLISH': 'true', 'PUBLISH_TIME_BEIJING': '15:00'}, datetime.fromisoformat('2026-09-30T13:33:00+08:00')))
        with self.assertRaises(ValueError):
            late_publish_due({'ALLOW_LATE_PUBLISH': 'true', 'PUBLISH_TIME_BEIJING': '29:00'})


class BudgetTests(unittest.TestCase):
    def test_arxiv_monday_has_sunday_announcement(self):
        self.assertIn('北京时间 **2026-09-28 08:00**', announce_window(date(2026, 9, 28)))
        self.assertIn('2026-12-01 09:00', announce_window(date(2026, 12, 1)))
        self.assertIsNone(announce_window(date(2026, 9, 26)))
        self.assertIsNone(announce_window(date(2026, 9, 27)))

    def check(self, time, **extra):
        assert_offpeak({'LLM_OFFPEAK_ONLY': 'true', **extra}, datetime.fromisoformat(time))

    def test_peak_windows_and_margin(self):
        for time in ('2026-09-29T08:10:00+08:00', '2026-09-29T12:00:00+08:00', '2026-09-29T18:00:00+08:00'):
            self.check(time)
        for time in ('2026-09-29T08:50:00+08:00', '2026-09-29T09:00:00+08:00', '2026-09-29T13:50:00+08:00', '2026-09-29T17:59:00+08:00'):
            with self.assertRaises(RuntimeError):
                self.check(time)

    def test_weekends_and_configured_holidays(self):
        self.check('2026-10-03T10:00:00+08:00')
        self.check('2026-10-01T10:00:00+08:00', LLM_OFFPEAK_HOLIDAYS='2026-10-01')
        with self.assertRaises(RuntimeError):
            self.check('2026-10-01T10:00:00+08:00')

    def test_winter_exception_requires_explicit_freshness_priority(self):
        with self.assertRaises(RuntimeError):
            self.check('2026-12-01T09:10:00+08:00')
        self.check('2026-12-01T09:10:00+08:00', ARXIV_FRESHNESS_PRIORITY='true')
        with self.assertRaises(RuntimeError):
            self.check('2026-12-01T10:30:00+08:00', ARXIV_FRESHNESS_PRIORITY='true')
        with self.assertRaises(RuntimeError):
            self.check('2026-09-29T09:10:00+08:00', ARXIV_FRESHNESS_PRIORITY='true')

    def test_us_dst_boundary(self):
        self.assertFalse(us_standard_time(datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc)))
        self.assertTrue(us_standard_time(datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)))


class SplitPipelineTests(unittest.TestCase):
    def test_analysis_does_not_send_and_publish_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile, state = root / 'profile.json', root / 'state'
            write_json(profile, {'keywords': ['agent'], 'resolve_orgs': False, 'llm_enrich': {'backend': 'none'}, 'sinks': []})
            calls = []
            def step(name, env, logger, *args):
                calls.append(name)
                if name == 'fetch_papers.py':
                    write_json(state / 'output/raw_papers.json', {'papers': [{'arxiv_id': '2609.00001'}]})
            with patch.object(run_daily, 'run_step', side_effect=step):
                run_daily.pipeline(profile, state, action='analyze')
                self.assertNotIn('publish.py', calls)
                self.assertFalse((state / 'seen.json').exists())
                calls.clear()
                # 推送阶段即使没有模型凭据，也应只读取已生成日报。
                write_json(profile, {'keywords': ['agent'], 'llm_enrich': {'backend': 'api'}, 'sinks': []})
                run_daily.pipeline(profile, state, action='publish')
                self.assertEqual(calls, ['publish.py'])
                self.assertTrue((state / 'seen.json').exists())
                calls.clear()
                run_daily.pipeline(profile, state, action='publish')
                self.assertEqual(calls, [])

    def test_reissue_keeps_seen_and_uses_saved_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile, state = root / 'profile.json', root / 'state'
            write_json(profile, {'keywords': ['agent'], 'resolve_orgs': False, 'llm_enrich': {'backend': 'none'}, 'sinks': []})
            write_json(state / 'seen.json', ['2501.00001', '2609.00001'])
            write_json(state / 'output/raw_papers.json', {'papers': [{'arxiv_id': '2609.00001'}]})
            write_json(state / 'output/delivery.json', ['old-receipt'])
            calls = []
            def step(name, env, logger, *args):
                calls.append(name)
                if name == 'publish.py':
                    self.assertFalse((state / 'output/delivery.json').exists())
            with patch.object(run_daily, 'run_step', side_effect=step):
                run_daily.pipeline(profile, state, action='reissue')
            self.assertEqual(calls, ['render_digest.py', 'publish.py'])
            self.assertEqual(json.loads((state / 'seen.json').read_text()), ['2501.00001', '2609.00001'])
            self.assertFalse((state / 'pending.json').exists())

    def test_partial_analysis_cache_is_reused_after_retry(self):
        papers = [{'arxiv_id': '2609.00001'}, {'arxiv_id': '2609.00002'}]
        def analyzed(paper):
            return {**paper, 'relevance': 'low', 'short_title': '方法', 'affiliations': '?',
                    'summary_cn': '', 'insight_for_us': '', 'one_liner': '概览', 'evidence': '',
                    'limitations': '', 'reading_priority': 'skip', 'reading_reason': '不相关'}
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            profile = {'llm_enrich': {'backend': 'api', 'api': {'concurrency': 1}}}
            with patch.multiple(enrich_llm, STATE=state, OUT=state / 'output/papers.json'), patch.object(enrich_llm, 'load_profile', return_value=profile), patch.object(enrich_llm, 'load_papers', return_value=(papers, {})), patch.object(enrich_llm, 'load_orgs', return_value={}), patch('llm_api.resolve_settings', return_value={'model': 'test-model', 'protocol': 'openai'}):
                with patch.object(enrich_llm, 'enrich_one', side_effect=[analyzed(papers[0]), {**papers[1], '_llm_error': 'RuntimeError'}]):
                    with self.assertRaises(RuntimeError):
                        enrich_llm.main()
                with patch.object(enrich_llm, 'enrich_one', return_value=analyzed(papers[1])) as call:
                    enrich_llm.main()
                    self.assertEqual(call.call_count, 1)
                    self.assertEqual(call.call_args.args[2]['arxiv_id'], '2609.00002')
