"""干净发布目录里的真实子进程链路；外部服务仅使用本机 HTTP 替身。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_release import release_files, ROOT


class ReleaseSmokeTests(unittest.TestCase):
    def test_clean_package_analyzes_renders_retries_and_deduplicates(self):
        analysis = json.loads((ROOT / 'examples/papers.en.json').read_text(encoding='utf-8'))['papers'][0]
        requests = []
        failures = [True]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body))
                if self.path == '/v1/chat/completions':
                    response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'papers': [analysis]})}}]}
                elif self.path == '/delivery':
                    response = {'code': 1 if failures[0] else 0}
                else:
                    self.send_error(404)
                    return
                payload = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory(prefix='radar clean ') as folder:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 3)
            self.addCleanup(server.shutdown)
            root = Path(folder)
            for source in release_files():
                target = root / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMP', 'TEMP', 'TMPDIR')}
            base = f'http://127.0.0.1:{server.server_port}'
            env.update(LLM_BASE_URL=base, LLM_MODEL_NAME='local-protocol-test',
                       LLM_API_KEY=secrets.token_urlsafe(24), FEISHU_WEBHOOK=base + '/delivery',
                       LLM_OFFPEAK_ONLY='true', LLM_PEAK_WINDOWS='00:00-23:59',
                       LLM_PEAK_WEEKDAYS='1,2,3,4,5,6,7', PYTHONUTF8='1', NO_PROXY='127.0.0.1')

            def run(*args):
                return subprocess.run([sys.executable, *args], cwd=root, env=env, capture_output=True, text=True, timeout=30)

            self.assertEqual(run('scripts/init_config.py').returncode, 0)
            profile_path = root / 'config/profile.json'
            profile = json.loads(profile_path.read_text(encoding='utf-8'))
            profile.update(digest_language='en', resolve_orgs=False,
                           sinks=[{'type': 'feishu_bot', 'enabled': True}])
            profile_path.write_text(json.dumps(profile), encoding='utf-8')
            self.assertEqual(run('scripts/run_daily.py', '--check').returncode, 0)
            output = root / 'state/output'
            output.mkdir(parents=True)
            (output / 'raw_papers.json').write_text(json.dumps({'papers': [{k: analysis[k] for k in ('arxiv_id', 'title', 'authors', 'abs_url', 'pdf_url', 'sources')}], 'new_count': 1}), encoding='utf-8')
            pending = root / 'state/pending.json'
            pending.write_text(json.dumps({'date': '2026-10-22', 'phase': 'fetched', 'profile': str(profile_path.resolve())}), encoding='utf-8')
            first = run('scripts/run_daily.py', '--allow-peak')
            self.assertNotEqual(first.returncode, 0)
            self.assertTrue(pending.exists())
            self.assertFalse((root / 'state/seen.json').exists())
            failures[0] = False
            retry = run('scripts/run_daily.py', '--publish-only')
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertFalse(pending.exists())
            self.assertEqual(json.loads((root / 'state/seen.json').read_text()), [analysis['arxiv_id']])
            self.assertEqual(run('scripts/run_daily.py', '--publish-only').returncode, 0)
            self.assertEqual([p for p, _ in requests].count('/v1/chat/completions'), 1)
            self.assertEqual([p for p, _ in requests].count('/delivery'), 2)
            body = json.dumps(requests[-1][1], ensure_ascii=False)
            self.assertIn('Read in depth', body)
            self.assertNotRegex(body, r'[\u3400-\u9fff]')
            self.assertEqual(env['LLM_OFFPEAK_ONLY'], 'true')
            self.assertNotIn('LLM_OFFPEAK_ONLY=false', (root / '.env').read_text().replace('# LLM_OFFPEAK_ONLY=false', ''))
            for language in ('zh', 'en'):
                self.assertEqual(run('scripts/render_demo.py', '--language', language).returncode, 0)
                self.assertTrue((root / f'state/demo/feishu-card.{language}.json').exists())


if __name__ == '__main__':
    unittest.main()
