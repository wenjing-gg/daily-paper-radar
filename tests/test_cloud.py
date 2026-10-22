"""云端配置与状态恢复不泄露凭据，且能跨 runner 恢复失败批次。"""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cloud_config
import cloud_state
from runtime import write_json


class CloudTests(unittest.TestCase):
    def test_cloud_topics_and_credentials_are_separate(self):
        ephemeral = secrets.token_urlsafe(24)
        profile = cloud_config.build_profile({'PAPER_KEYWORDS': 'agent, reasoning, ',
                                            'PAPER_FOCUS': '推理', 'FEISHU_SECRET': ephemeral})
        self.assertEqual(profile['keywords'], ['agent', 'reasoning'])
        self.assertNotIn(ephemeral, json.dumps(profile))
        self.assertEqual(profile['sinks'][0]['secret_env'], 'FEISHU_SECRET')
        self.assertEqual(cloud_config.build_profile({})['keywords'], [])
        self.assertNotIn('secret_env', cloud_config.build_profile({})['sinks'][0])

    def test_snapshot_resumes_batch_without_archiving_logs_or_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile, state, archive = root / 'profile.json', root / 'state', root / 'artifact'
            write_json(profile, cloud_config.build_profile({}))
            write_json(state / 'seen.json', ['old'])
            write_json(state / 'pending.json', {'profile': '/old/runner/profile.json', 'phase': 'rendered'})
            write_json(state / 'output/delivery.json', {'delivered': []})
            (state / 'run.log').write_text('不应归档', encoding='utf-8')
            with patch.multiple(cloud_state, PROFILE=profile, STATE=state, SNAPSHOT=archive):
                cloud_state.snapshot()
                self.assertFalse((archive / 'run.log').exists())
                self.assertFalse((archive / 'profile.json').exists())
                with patch.object(cloud_state, 'STATE', root / 'new_state'):
                    cloud_state.restore_files(archive)
                restored = json.loads((root / 'new_state/pending.json').read_text())
                self.assertEqual(restored['profile'], str(profile.resolve()))
                self.assertTrue((root / 'new_state/output/delivery.json').exists())
                write_json(profile, cloud_config.build_profile({'PAPER_FOCUS': '改变方向'}))
                with self.assertRaisesRegex(RuntimeError, '尚未完成'):
                    cloud_state.restore_files(archive)

    def test_expired_state_stops_instead_of_silently_resetting(self):
        response = json.dumps([{'artifacts': [{'expired': True}]}])
        with patch.dict('os.environ', {'GITHUB_REPOSITORY': 'example/repo'}), patch.object(cloud_state, 'gh', return_value=response):
            with self.assertRaisesRegex(RuntimeError, '过期'):
                cloud_state.restore()

    def test_restore_selects_newest_across_unordered_pages(self):
        response = json.dumps([
            {'artifacts': [{'id': 1, 'created_at': '2026-09-29T01:00:00Z', 'workflow_run': {'id': 10}}]},
            {'artifacts': [{'id': 3, 'created_at': '2026-09-29T03:00:00Z', 'workflow_run': {'id': 30}},
                           {'id': 2, 'created_at': '2026-09-29T02:00:00Z', 'workflow_run': {'id': 20}}]}])
        with patch.dict('os.environ', {'GITHUB_REPOSITORY': 'example/repo'}), patch.object(cloud_state, 'gh', side_effect=[response, '']) as call, patch.object(cloud_state, 'restore_files'):
            cloud_state.restore()
            self.assertIn('--paginate', call.call_args_list[0].args)
            self.assertEqual(call.call_args_list[1].args[:3], ('run', 'download', '30'))

    def test_adding_doc_to_old_pending_batch_preserves_paid_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / 'profile.json'
            archive = root / 'archive'
            write_json(profile, cloud_config.build_profile({}))
            with patch.multiple(cloud_state, PROFILE=profile, STATE=root / 'state'):
                write_json(archive / 'cloud.json', {'version': 1, 'profile_hash': cloud_state.fingerprint()})
                write_json(archive / 'pending.json', {'phase': 'rendered', 'profile': '/old/profile.json'})
                write_json(profile, cloud_config.build_profile({'FEISHU_DOC_ID': 'DocumentExample'}))
                cloud_state.restore_files(archive)
                self.assertTrue((root / 'state/pending.json').exists())


if __name__ == '__main__':
    unittest.main()
