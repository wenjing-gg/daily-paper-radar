"""首次配置应可直接读取，重复初始化不能覆盖用户修改。"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import init_config


class InitConfigTests(unittest.TestCase):
    def test_first_setup_and_existing_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'config/_template.json').write_bytes((init_config.ROOT / 'config/_template.json').read_bytes())
            (root / '.env.example').write_bytes((init_config.ROOT / '.env.example').read_bytes())
            with patch.object(init_config, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                init_config.main()
                profile = root / 'config/profile.json'
                self.assertEqual(json.loads(profile.read_text(encoding='utf-8'))['paper_preferences'], '')
                self.assertTrue((root / '.env').exists())
                personal = {'focus_description': '我的研究方向', 'paper_preferences': '我的筛选标准'}
                profile.write_text(json.dumps(personal), encoding='utf-8')
                (root / '.env').write_text('# 用户保留的配置\n', encoding='utf-8')
                init_config.main()
                self.assertEqual(json.loads(profile.read_text(encoding='utf-8')), personal)
                self.assertEqual((root / '.env').read_text(encoding='utf-8'), '# 用户保留的配置\n')


if __name__ == '__main__':
    unittest.main()
