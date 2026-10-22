"""无网络回归：断点恢复、跨平台 CLI、群投递和配置检查。"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_daily
import publish
import enrich_cli
from runtime import write_json, run_lock


class PipelineTests(unittest.TestCase):
    def test_failure_preserves_batch_and_seen_then_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg, state = root / 'profile.json', root / 'state'
            write_json(cfg, {'keywords': ['agent'], 'resolve_orgs': False, 'llm_enrich': {'backend': 'none'}, 'sinks': []})
            calls = []
            failing = True
            def step(name, env, logger, *args):
                calls.append(name)
                if name == 'fetch_papers.py':
                    write_json(state / 'output/raw_papers.json', {'papers': [{'arxiv_id': '2609.00001'}], 'new_count': 1})
                if name == 'publish.py' and failing:
                    raise RuntimeError('模拟发布失败')
            with patch.object(run_daily, 'run_step', side_effect=step):
                with self.assertRaises(RuntimeError):
                    run_daily.pipeline(cfg, state)
                self.assertFalse((state / 'seen.json').exists())
                self.assertTrue((state / 'pending.json').exists())
                failing = False
                run_daily.pipeline(cfg, state)
            self.assertEqual(calls.count('fetch_papers.py'), 1)
            self.assertEqual(json.loads((state / 'seen.json').read_text()), ['2609.00001'])
            self.assertFalse((state / 'pending.json').exists())

    def test_interactive_prepare_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg, state = root / 'profile.json', root / 'state'
            write_json(cfg, {'keywords': ['agent'], 'llm_enrich': {'backend': 'codex'}, 'sinks': []})
            calls = []
            def step(name, env, logger, *args):
                calls.append(name)
                if name == 'fetch_papers.py':
                    write_json(state / 'output/raw_papers.json', {'papers': [{'arxiv_id': '2609.00001'}]})
            with patch.object(run_daily, 'run_step', side_effect=step):
                run_daily.pipeline(cfg, state, action='prepare')
                write_json(state / 'output/papers.json', {'papers': []})
                with self.assertRaises(RuntimeError):
                    run_daily.pipeline(cfg, state, action='finish')
                write_json(state / 'output/papers.json', {'papers': [{'arxiv_id': '2609.00001', 'relevance': 'high', 'short_title': '测试', 'summary_cn': '摘要', 'insight_for_us': '启发', 'affiliations': '?', 'one_liner': '一句话', 'evidence': '待核实结果', 'limitations': '核实成本', 'reading_priority': 'deep_read', 'reading_reason': '先读方法'}]})
                run_daily.pipeline(cfg, state, action='finish')
            self.assertEqual(calls, ['fetch_papers.py', 'render_digest.py', 'publish.py'])

    def test_lock_excludes_concurrent_run(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / 'run.lock'
            with run_lock(lock):
                with self.assertRaises(RuntimeError):
                    with run_lock(lock):
                        pass
            with run_lock(lock):
                pass

    def test_actual_render_publish_from_another_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='中文 空格 ') as folder:
            root = Path(folder)
            cfg, state = root / 'profile.json', root / 'state'
            write_json(cfg, {'keywords': ['agent'], 'inbox_dir': str(root / 'inbox'), 'sinks': [{'type': 'local_file', 'dir': str(root / 'published')}], 'deadlines': []})
            write_json(state / 'output/raw_papers.json', {'papers': [], 'new_count': 0})
            env = dict(os.environ, DAILY_PAPER_RADAR_PROFILE=str(cfg), DAILY_PAPER_RADAR_STATE=str(state), PYTHONUTF8='1')
            for name in ('render_digest.py', 'publish.py'):
                result = subprocess.run([sys.executable, str(run_daily.ROOT / 'scripts' / name)], cwd=root, env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(list((root / 'published').glob('*.md')))
            self.assertTrue((state / 'output/digest.md').exists())


class DeliveryTests(unittest.TestCase):
    def test_retry_only_failed_group(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / 'raw.json', {'new_count': 1})
            profile = {'sinks': [{'type': 'feishu_bot', 'name': 'A'}, {'type': 'feishu_bot', 'name': 'B'}]}
            attempts = []
            def send(sc, *args):
                attempts.append(sc['name'])
                return sc['name'] == 'A' or attempts.count('B') == 2
            with patch.object(publish, 'STATE', root), patch.object(publish, 'RAW_PAPERS', root / 'raw.json'), patch.object(publish, 'load_profile', return_value=profile), patch.object(publish, '_load_papers_for_render', return_value=([], lambda *a, **k: '日报')), patch.object(publish, 'run_sink', side_effect=send), patch.object(sys, 'argv', ['publish.py', '--date', '2026-09-28']):
                self.assertEqual(publish.main(), 1)
                self.assertEqual(publish.main(), 0)
            self.assertEqual(attempts, ['A', 'B', 'B'])

    def test_resend_bot_uses_saved_date_and_skips_document(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = root / 'output/digest.md'
            write_json(root / 'output/papers.json', {'papers': []})
            digest.write_text('**日报 · 2026-09-29（北京时间）**', encoding='utf-8')
            profile = {'sinks': [{'type': 'feishu_bot'}, {'type': 'feishu_doc'}]}
            with patch.multiple(publish, STATE=root, DEFAULT_DIGEST=digest, RAW_PAPERS=root / 'raw.json'), patch.object(publish, 'load_profile', return_value=profile), patch.object(publish, '_load_papers_for_render', return_value=([], lambda *a, **k: '日报')), patch.object(publish, 'run_sink', return_value=True) as send, patch.object(sys, 'argv', ['publish.py', '--resend-bot']):
                self.assertEqual(publish.main(), 0)
                self.assertEqual(publish.main(), 0)
                self.assertEqual(send.call_count, 2)
                self.assertTrue(all(c.args[0]['type'] == 'feishu_bot' for c in send.call_args_list))
                self.assertTrue(all(c.args[-1].isoformat() == '2026-09-29' for c in send.call_args_list))

    def test_empty_sinks_do_not_enable_legacy(self):
        with patch.object(publish, 'load_profile', return_value={'sinks': []}), patch.object(publish, 'legacy_sinks') as legacy, patch.object(publish, '_load_papers_for_render', return_value=([], lambda *a, **k: '日报')), patch.object(sys, 'argv', ['publish.py']), contextlib.redirect_stdout(io.StringIO()):
            publish.main()
            legacy.assert_not_called()


class CliTests(unittest.TestCase):
    def test_prompt_uses_stdin_and_custom_model(self):
        for backend in ('claude_code', 'codex'):
            captured = []
            def execute(command, **kwargs):
                captured.append((command, kwargs))
                if backend == 'codex':
                    Path(command[command.index('--output-last-message') + 1]).write_text('{"papers": []}', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, '{"papers": []}', '')
            with patch.object(enrich_cli, 'cli_command', return_value=['cli']), patch.object(enrich_cli.subprocess, 'run', side_effect=execute):
                result = enrich_cli.call_cli(backend, {'model': 'selected-model'}, '中文摘要' * 10000)
            command, options = captured[0]
            self.assertIn('selected-model', command)
            self.assertEqual(options['input'], '中文摘要' * 10000)
            self.assertEqual(options['encoding'], 'utf-8')
            self.assertEqual(json.loads(result), {'papers': []})

    def test_cli_failure_not_accepted(self):
        with patch.object(enrich_cli, 'cli_command', return_value=['cli']), patch.object(enrich_cli.subprocess, 'run', return_value=subprocess.CompletedProcess(['cli'], 1, '{}', 'error')):
            with self.assertRaises(RuntimeError):
                enrich_cli.call_cli('claude_code', {}, 'prompt')


if __name__ == '__main__':
    unittest.main()
