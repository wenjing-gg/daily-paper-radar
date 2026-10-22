"""用 Actions artifact 保存去重与失败批次；不归档配置、密钥和运行日志。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from runtime import ROOT, write_json

NAME = 'radar-state'
PROFILE = ROOT / 'config/profile.actions.json'
STATE = ROOT / 'state'
SNAPSHOT = ROOT / 'state/artifact'
# 仅持久化流水线恢复必需的文件。
FILES = ('seen.json', 'pending.json', 'schedule.json', 'output/raw_papers.json',
         'output/papers.json', 'output/orgs.json', 'output/relevance.json',
         'output/digest.md', 'output/delivery.json', 'output/doc_delivery.json', 'output/enrich_cache.json', 'output/metadata_cache.json')


def fingerprint(value=None):
    if value is None:
        value = json.loads(PROFILE.read_text(encoding='utf-8'))
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def analysis_fingerprint():
    value = json.loads(PROFILE.read_text(encoding='utf-8'))
    value.pop('sinks', None)
    return fingerprint(value)


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('GitHub 状态读取失败，请检查 Actions 权限和运行记录；未开始推送。')
    return result.stdout


def restore_files(folder):
    meta = json.loads((folder / 'cloud.json').read_text(encoding='utf-8'))
    if meta.get('version') != 1:
        raise RuntimeError('状态版本不支持，停止推送。')
    if (folder / 'pending.json').exists() and meta.get('profile_hash') != fingerprint():
        value = json.loads(PROFILE.read_text(encoding='utf-8'))
        # 兼容旧快照：仅新增文档归档时可复用已付费的同一份分析。
        without_doc = dict(value, sinks=[s for s in value.get('sinks', []) if s.get('type') != 'feishu_doc'])
        same_analysis = meta.get('analysis_hash') == analysis_fingerprint()
        legacy_add_doc = meta.get('profile_hash') == fingerprint(without_doc)
        if not (same_analysis or legacy_add_doc):
            raise RuntimeError('上次批次尚未完成且订阅配置已变化；请恢复原配置重跑，完成后再修改方向。')
    for name in FILES:
        source = folder / name
        if source.is_file():
            target = STATE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    pending = STATE / 'pending.json'
    if pending.exists():
        data = json.loads(pending.read_text(encoding='utf-8'))
        # 不同 runner 的绝对工作目录可能变化；配置哈希一致才允许迁移。
        data['profile'] = str(PROFILE.resolve())
        write_json(pending, data)


def restore():
    repo = os.environ['GITHUB_REPOSITORY']
    pages = json.loads(gh('api', f'repos/{repo}/actions/artifacts?name={NAME}&per_page=100', '--paginate', '--slurp'))
    artifacts = [item for page in pages for item in page.get('artifacts', [])]
    if not artifacts:
        print('没有历史状态，从首次运行开始。')
        return
    # API 返回顺序不作为新旧依据，遍历所有分页后明确选择最新快照。
    artifact = max(artifacts, key=lambda a: (a.get('created_at', ''), a.get('id', 0)))
    if artifact.get('expired'):
        raise RuntimeError('最新状态已过期，停止推送以避免重复；请删除所有 radar-state artifact 后重新运行，最近论文可能再次推送。')
    with tempfile.TemporaryDirectory() as folder:
        gh('run', 'download', str(artifact['workflow_run']['id']), '--repo', repo,
           '--name', NAME, '--dir', folder)
        restore_files(Path(folder))
    print('已恢复去重记录和未完成批次。')


def snapshot():
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    SNAPSHOT.mkdir(parents=True)
    for name in FILES:
        source = STATE / name
        if source.is_file():
            target = SNAPSHOT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    write_json(SNAPSHOT / 'cloud.json', {'version': 1, 'profile_hash': fingerprint(), 'analysis_hash': analysis_fingerprint()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['restore', 'snapshot'])
    args = parser.parse_args()
    try:
        restore() if args.action == 'restore' else snapshot()
    except Exception as exc:
        # 不回显第三方响应、环境变量或下载内容。
        print(str(exc) if isinstance(exc, RuntimeError) else '云端状态处理失败；请检查 artifact 和 Actions 权限。')
        raise SystemExit(1)
