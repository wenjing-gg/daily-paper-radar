"""验证多次触发能恢复分析、准时段投递，并避免当天重复费用。"""
from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cloud_run import tick
from runtime import write_json
import run_daily


class TickTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state = Path(self.folder.name)
        self.env = {'LLM_OFFPEAK_ONLY': 'true'}
        self.run = Mock()

    def at(self, stamp, run=None):
        tick([], self.env, self.state, clock=lambda: datetime.fromisoformat(stamp), run=run or self.run)

    def test_summer_analyzes_then_waits_and_peak_delivery_uses_no_model(self):
        self.at('2026-09-30T08:10:00+08:00')
        self.run.assert_called_once_with(['--analyze-only'])
        write_json(self.state / 'pending.json', {'date': '2026-09-30', 'phase': 'rendered'})
        self.run.reset_mock()
        self.at('2026-09-30T09:29:00+08:00')
        self.run.assert_not_called()
        self.at('2026-09-30T09:30:00+08:00')
        self.run.assert_called_once_with(['--publish-only'])

    def test_winter_waits_for_release_and_requires_peak_exception(self):
        self.at('2026-12-01T08:55:00+08:00')
        self.at('2026-12-01T09:10:00+08:00')
        self.run.assert_not_called()
        self.env['ARXIV_FRESHNESS_PRIORITY'] = 'true'
        self.at('2026-12-01T09:10:00+08:00')
        self.run.assert_called_once_with(['--analyze-only'])

    def test_missed_analysis_waits_for_offpeak_then_analyzes_and_publishes(self):
        write_json(self.state / 'pending.json', {'phase': 'fetched'})
        self.at('2026-09-30T10:10:00+08:00')
        self.run.assert_not_called()
        self.at('2026-09-30T12:17:00+08:00')
        self.assertEqual([c.args[0] for c in self.run.call_args_list], [['--analyze-only'], ['--publish-only']])

    def test_analysis_crossing_delivery_time_sends_immediately(self):
        times = iter(map(datetime.fromisoformat, ['2026-12-01T09:25:00+08:00', '2026-12-01T09:33:00+08:00']))
        self.env['ARXIV_FRESHNESS_PRIORITY'] = 'true'
        tick([], self.env, self.state, clock=lambda: next(times), run=self.run)
        self.assertEqual([c.args[0] for c in self.run.call_args_list], [['--analyze-only'], ['--publish-only']])

    def test_completed_day_skips_and_next_day_restarts(self):
        write_json(self.state / 'schedule.json', {'completed_date': '2026-09-30'})
        self.at('2026-09-30T12:17:00+08:00')
        self.run.assert_not_called()
        self.at('2026-10-01T08:10:00+08:00')
        self.run.assert_called_once_with(['--analyze-only'])

    def test_analysis_failure_keeps_retry_possible_and_never_publishes(self):
        self.run.side_effect = RuntimeError('temporary failure')
        with self.assertRaises(RuntimeError):
            self.at('2026-09-30T08:10:00+08:00')
        self.assertFalse((self.state / 'schedule.json').exists())
        self.run.assert_called_once_with(['--analyze-only'])

    def test_invalid_pricing_configuration_is_not_swallowed(self):
        self.env['LLM_PEAK_WINDOWS'] = 'invalid'
        with self.assertRaises(RuntimeError):
            self.at('2026-09-30T08:10:00+08:00')

    def test_old_version_success_is_migrated_but_failed_batch_is_not(self):
        write_json(self.state / 'output/raw_papers.json', {'generated_at': '2026-09-30T00:10:00Z', 'papers': [{'arxiv_id': '2609.00001'}]})
        (self.state / 'output/digest.md').write_text('digest')
        write_json(self.state / 'seen.json', ['2609.00001'])
        self.at('2026-09-30T12:17:00+08:00')
        self.run.assert_not_called()
        write_json(self.state / 'pending.json', {'phase': 'rendered'})
        self.at('2026-09-30T12:17:00+08:00')
        self.run.assert_called_once_with(['--publish-only'])

    def test_manual_all_and_empty_batch_record_completion_only_after_delivery(self):
        profile = self.state / 'profile.json'
        write_json(profile, {'keywords': ['agent'], 'llm_enrich': {'backend': 'none'}, 'sinks': []})
        def step(name, env, logger, *args):
            if name == 'fetch_papers.py':
                write_json(self.state / 'output/raw_papers.json', {'papers': []})
            if name == 'publish.py':
                self.assertFalse((self.state / 'schedule.json').exists())
        with patch.object(run_daily, 'run_step', side_effect=step), patch.object(run_daily, 'beijing_today', return_value=datetime(2026, 9, 30).date()):
            run_daily.pipeline(profile, self.state)
        self.assertEqual(json.loads((self.state / 'schedule.json').read_text())['completed_date'], '2026-09-30')
        self.at('2026-09-30T12:17:00+08:00')
        self.run.assert_not_called()
