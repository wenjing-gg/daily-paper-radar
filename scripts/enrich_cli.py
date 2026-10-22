"""通过 Claude Code / Codex CLI 生成摘要；提示词走 stdin，兼容 Windows 长输入。"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from runtime import PROFILE, STATE, write_json
from enrich_claude import build_prompt, parse_json
from analysis_prompt import FIELDS, validate_analysis
from digest_language import digest_language


def cli_command(cli):
    executable = shutil.which(cli)
    if not executable:
        raise RuntimeError('找不到模型 CLI，请设置 cli_path 为可执行文件的绝对路径')
    # npm 在 Windows 提供 .cmd 包装器，直接调用对应 JS，避免 cmd.exe 转义。
    path = Path(executable)
    if os.name == 'nt' and path.suffix.lower() in ('.cmd', '.bat'):
        package = {'codex': '@openai/codex/bin/codex.js',
                   'claude': '@anthropic-ai/claude-code/cli.js'}.get(path.stem.lower())
        target = path.parent / 'node_modules' / (package or '')
        node = shutil.which('node')
        if not package or not target.is_file() or not node:
            raise RuntimeError('CLI 包装器无法解析，请使用原生可执行文件或标准 npm 安装')
        return [node, str(target)]
    return [executable]


def call_cli(backend, cfg, prompt):
    command = cli_command(cfg.get('cli_path') or ('claude' if backend == 'claude_code' else 'codex'))
    with tempfile.TemporaryDirectory(prefix='daily-paper-radar-llm-') as folder:
        output = Path(folder) / 'result.json'
        if backend == 'claude_code':
            command += ['-p', '--output-format', 'text', '--tools', '', '--disallowedTools', 'mcp__*']
        else:
            command += ['exec', '--skip-git-repo-check', '--sandbox', 'read-only',
                        '--output-last-message', str(output)]
        if cfg.get('model'):
            command += ['--model', cfg['model']]
        if backend == 'codex':
            command += ['-']
        proc = subprocess.run(command, input=prompt, encoding='utf-8', errors='replace',
                              capture_output=True, cwd=folder, timeout=int(cfg.get('timeout_s', 600)))
        if proc.returncode:
            raise RuntimeError(f'{backend} 退出码 {proc.returncode}；请单独检查 CLI 登录及模型权限')
        return output.read_text(encoding='utf-8') if backend == 'codex' else proc.stdout


def main():
    profile = json.loads(PROFILE.read_text(encoding='utf-8-sig'))
    le = profile['llm_enrich']
    backend = le['backend']
    cfg = le.get(backend, {})
    payload = json.loads((STATE / 'output/raw_papers.json').read_text(encoding='utf-8'))
    papers = payload['papers']
    org_file = STATE / 'output/orgs.json'
    orgs = json.loads(org_file.read_text(encoding='utf-8')) if org_file.exists() else {}
    results = []
    batch_size = max(1, int(cfg.get('batch_size', 10)))
    for offset in range(0, len(papers), batch_size):
        batch = papers[offset:offset + batch_size]
        parsed = parse_json(call_cli(backend, cfg, build_prompt(profile, batch, orgs)))
        if not isinstance(parsed, dict) or not isinstance(parsed.get('papers'), list):
            raise RuntimeError('模型没有返回有效的 papers 数组')
        entries = parsed['papers']
        ids = [p.get('arxiv_id') for p in entries if isinstance(p, dict)]
        if len(ids) != len(entries) or len(set(ids)) != len(ids) or set(ids) != {p['arxiv_id'] for p in batch}:
            raise RuntimeError('模型输出的论文 ID 缺失、重复或不匹配')
        by_id = {p['arxiv_id']: p for p in entries}
        for paper in batch:
            enhanced = by_id[paper['arxiv_id']]
            validate_analysis(enhanced)
            results.append({**paper, **{k: enhanced[k] for k in FIELDS}, 'analysis_basis': 'abstract'})
    payload['papers'] = results
    default_model = 'CLI default model' if digest_language(profile) == 'en' else 'CLI 默认模型'
    payload['llm_enrich'] = {'backend': backend, 'model': cfg.get('model') or default_model}
    write_json(STATE / 'output/papers.json', payload)


if __name__ == '__main__':
    main()
