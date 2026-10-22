#!/usr/bin/env python3
"""Windows/macOS 统一入口：检查、预览、批次恢复和定时执行。"""
from __future__ import annotations

from digest_language import digest_title
from runtime import beijing_today
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from runtime import ROOT, write_json, run_lock, redact


def validate(profile, publishing=True):
    from digest_language import digest_language
    digest_language(profile)
    from fetch_papers import source_config
    sources = source_config(profile)
    if sources.get('arxiv', {}).get('enabled') and not profile.get('keywords'):
        raise ValueError('启用 arXiv RSS 时 keywords 不能为空')
    hf = sources.get('huggingface', {})
    if hf.get('enabled'):
        if not 1 <= int(hf.get('lookback_days', 3)) <= 14 or int(hf.get('max_papers', 20)) < 1 or int(hf.get('min_upvotes', 0)) < 0:
            raise ValueError('Hugging Face 的回看天数、数量或最低票数无效')
        if hf.get('keyword_filter') and not profile.get('keywords'):
            raise ValueError('启用 HF 关键词过滤时 keywords 不能为空')
    gate = profile.get('source_gate', {})
    if gate.get('enabled'):
        from source_gate import load_policy
        load_policy(gate)
        if not profile.get('paper_metadata', {}).get('enabled'):
            raise ValueError('来源筛选需要启用 paper_metadata')
    le = profile.get('llm_enrich', {})
    backend = le.get('backend', 'openai_compatible' if le.get('enabled') else 'none')
    if backend not in ('none', 'claude_code', 'codex', 'api', 'openai_compatible'):
        raise ValueError('不支持的 llm_enrich.backend')
    cfg = le.get(backend, le if le.get('enabled') else {})
    if backend in ('claude_code', 'codex'):
        from enrich_cli import cli_command
        cli_command(cfg.get('cli_path') or ('claude' if backend == 'claude_code' else 'codex'))
    if backend in ('api', 'openai_compatible'):
        from enrich_llm import resolve_cfg
        from llm_api import resolve_settings
        cfg = resolve_cfg(profile)
        resolve_settings(cfg)
    if int(profile.get('render', {}).get('max_detailed', 10)) < 1:
        raise ValueError('render.max_detailed 必须为正整数')
    for key in ('timeout_s', 'batch_size', 'max_papers', 'request_timeout_s', 'concurrency'):
        if key in cfg and int(cfg[key]) < 1:
            raise ValueError(f'模型配置 {key} 必须为正整数')
    for sink in profile.get('sinks', []):
        if sink.get('enabled') is False:
            continue
        if sink.get('type') not in ('feishu_bot', 'feishu_doc', 'feishu_bitable', 'notion', 'obsidian', 'local_file', 'webhook'):
            raise ValueError('不支持的 sink type')
        if any(k in sink for k in ('webhook', 'secret', 'api_key', 'password', 'token')):
            raise ValueError('凭据只能通过环境变量引用，不能直接写入配置')
        if publishing and sink['type'] == 'feishu_doc':
            from sinks.feishu_doc import document_id
            document_id(os.environ.get(sink.get('document_id_env', 'FEISHU_DOC_ID'), ''))
            for key, default in (('app_id_env', 'FEISHU_APP_ID'), ('app_secret_env', 'FEISHU_APP_SECRET')):
                if not os.environ.get(sink.get(key, default), '').strip():
                    raise ValueError(f'文档归档缺少环境变量 {sink.get(key, default)}')
        if publishing and sink['type'] == 'feishu_bot':
            if not os.environ.get(sink.get('webhook_env', 'FEISHU_WEBHOOK')):
                raise ValueError('飞书群机器人的环境变量未设置')
            if sink.get('secret_env') and not os.environ.get(sink['secret_env']):
                raise ValueError('配置了 secret_env 但对应环境变量未设置；未启用签名时删除该字段')
    return backend


def run_step(name, env, logger, *args):
    logger.info('执行 %s', name)
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *args],
                          cwd=ROOT, env=env, capture_output=True, encoding='utf-8', errors='replace')
    if proc.stdout.strip():
        logger.info('%s', redact(proc.stdout.strip()))
    if proc.stderr.strip():
        logger.info('%s', redact(proc.stderr.strip()))
    if proc.returncode:
        raise RuntimeError(f'{name} 失败，退出码 {proc.returncode}')


def pipeline(profile_path, state, preview=False, action=None, allow_peak=False):
    env = dict(os.environ, DAILY_PAPER_RADAR_PROFILE=str(profile_path), DAILY_PAPER_RADAR_STATE=str(state), PYTHONUTF8='1')
    if allow_peak:
        env['LLM_OFFPEAK_ONLY'] = 'false'
        print('仅本次允许高峰模型调用，可能产生高峰费用；定时配置不变。', flush=True)
    profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
    validation_profile = dict(profile, llm_enrich={'backend': 'none'}) if action in ('prepare', 'finish', 'publish') else profile
    backend = validate(validation_profile, publishing=not preview and action not in ('prepare', 'analyze'))
    state.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('daily-paper-radar')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    file_handler = RotatingFileHandler(state / 'run.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    for handler in (file_handler, logging.StreamHandler()):
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        logger.addHandler(handler)
    try:
        with run_lock(state / 'run.lock'):
            pending = state / 'pending.json'
            output = state / 'output'
            if pending.exists():
                job = json.loads(pending.read_text(encoding='utf-8'))
                if job['profile'] != str(profile_path):
                    raise RuntimeError('该状态目录有其他配置的待处理批次，请使用独立 --state-dir')
                if job.get('phase') not in ('fetched', 'enriched', 'rendered'):
                    raise RuntimeError('待处理批次阶段无效，请检查状态文件')
                if action == 'reissue':
                    raise RuntimeError('存在未完成批次，请用 all 或 publish 恢复；不要再次重建重发批次')
                logger.info('恢复上次未完成的批次')
            else:
                if action == 'publish':
                    logger.info('没有待发布日报；不会调用模型补生成')
                    return
                if action == 'finish':
                    raise RuntimeError('请先使用 --prepare 创建待处理批次')
                if action == 'reissue':
                    if not (output / 'raw_papers.json').exists():
                        raise RuntimeError('没有可重发的历史批次，请先运行正常分析')
                    logger.info('手动重新分析并重发上一批，保留历史去重记录')
                    if profile.get('source_gate', {}).get('enabled'):
                        run_step('fetch_papers.py', env, logger, '--refilter-saved')
                else:
                    run_step('fetch_papers.py', env, logger)
                for name in ('delivery.json', 'papers.json', 'orgs.json', 'relevance.json', 'enrich_cache.json'):
                    (output / name).unlink(missing_ok=True)
                # 新批次不得同步上批次的深读笔记。
                for name in ('notes', 'fulltext'):
                    shutil.rmtree(output / name, ignore_errors=True)
                job = {'date': beijing_today().isoformat(), 'phase': 'fetched', 'profile': str(profile_path)}
                write_json(pending, job)
            if action == 'publish' and job['phase'] != 'rendered':
                raise RuntimeError('日报尚未分析完成；推送阶段不会调用模型，请在低价时段重跑分析任务')
            raw = json.loads((output / 'raw_papers.json').read_text(encoding='utf-8'))
            if action == 'prepare':
                logger.info('批次已准备：%s', output / 'raw_papers.json')
                return
            if action == 'finish' and job['phase'] == 'fetched':
                if raw['papers']:
                    enhanced = json.loads((output / 'papers.json').read_text(encoding='utf-8'))['papers']
                    ids = [p['arxiv_id'] for p in enhanced]
                    if len(ids) != len(set(ids)) or set(ids) != {p['arxiv_id'] for p in raw['papers']}:
                        raise RuntimeError('papers.json 必须覆盖本批次的全部论文且无重复')
                    from analysis_prompt import FIELDS, validate_analysis
                    by_id = {p['arxiv_id']: p for p in enhanced}
                    merged = []
                    extras = ('summary_cn_short', 'insight_short', 'key_formula', 'main_results', 'analysis_basis')
                    for original in raw['papers']:
                        paper = by_id[original['arxiv_id']]
                        validate_analysis(paper)
                        if paper.get('analysis_basis', 'abstract') not in ('abstract', 'fulltext'):
                            raise RuntimeError('analysis_basis 必须为 abstract 或 fulltext')
                        merged.append({**original, **{k: paper[k] for k in FIELDS + extras if k in paper}})
                    write_json(output / 'papers.json', {**raw, 'papers': merged})
                job['phase'] = 'enriched'
                write_json(pending, job)
            if job['phase'] == 'fetched':
                if raw['papers']:
                    if profile.get('resolve_orgs', True):
                        run_step('enrich_orgs.py', env, logger)
                    if backend != 'none':
                        run_step('enrich_llm.py' if backend in ('api', 'openai_compatible') else 'enrich_cli.py', env, logger)
                    if profile.get('deep_read', {}).get('enabled'):
                        logger.info('定时模式为摘要分析；全文深读请在客户端交互模式执行')
                job['phase'] = 'enriched'
                write_json(pending, job)
            if job['phase'] == 'enriched':
                run_step('render_digest.py', env, logger, '--date', job['date'])
                job['phase'] = 'rendered'
                job['ready_at'] = datetime.now(timezone.utc).isoformat()
                write_json(pending, job)
            if action == 'analyze':
                logger.info('日报已生成，等待定时推送；不发送消息、不提交去重记录')
                return
            if preview:
                logger.info('预览完成：%s', output / 'digest.md')
                return
            stamp = raw.get('generated_at') or job.get('ready_at')
            if action == 'publish' and stamp:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds() / 3600
                if age > float(os.environ.get('MAX_DIGEST_AGE_HOURS') or 48):
                    raise RuntimeError('待发布日报超过 MAX_DIGEST_AGE_HOURS，已停止投递；请检查失败记录和未完成批次')
            run_step('publish.py', env, logger, '--date', job['date'])
            seen_path = state / 'seen.json'
            seen = set(json.loads(seen_path.read_text(encoding='utf-8'))) if seen_path.exists() else set()
            seen.update(p['arxiv_id'] for p in raw['papers'])
            write_json(seen_path, sorted(seen))
            write_json(state / 'schedule.json', {'completed_date': job['date']})
            pending.unlink()
            logger.info('本批次完成，共 %d 篇', len(raw['papers']))
    except Exception as exc:
        logger.error('%s', redact(exc))
        raise
    finally:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=ROOT / 'config/profile.json')
    parser.add_argument('--state-dir', type=Path, default=ROOT / 'state')
    parser.add_argument('--allow-peak', action='store_true', help='仅本次允许高峰模型调用，可能增加费用；不修改定时配置')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare', action='store_true', help='为交互会话抓取并保留批次，不调用模型、不发布')
    modes.add_argument('--finish', action='store_true', help='校验会话生成的 papers.json 后渲染发布')
    modes.add_argument('--check', action='store_true', help='只检查配置，不联网、不推送')
    modes.add_argument('--dry-run', action='store_true', help='联网生成预览，不推送、不修改正式去重状态')
    modes.add_argument('--analyze-only', action='store_true', help='抓取、分析并保存正式待发批次，不推送')
    modes.add_argument('--reissue', action='store_true', help='手动重新分析并重发上一批，保留历史去重；会再次产生模型费用和群消息')
    modes.add_argument('--publish-only', action='store_true', help='只投递已生成批次，不抓取、不调用模型')
    args = parser.parse_args()
    if args.allow_peak and (args.check or args.prepare or args.finish or args.publish_only):
        parser.error('--allow-peak 仅用于预览、分析、正常运行或重新分析')
    profile_path, state = args.profile.resolve(), args.state_dir.resolve()
    try:
        profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
        validate(dict(profile, llm_enrich={'backend': 'none'}) if args.prepare or args.finish or args.publish_only else profile, publishing=not args.dry_run and not args.prepare and not args.analyze_only)
        if args.check:
            print('配置检查通过；CLI 登录、模型权限和网络仍需实际运行验证。')
        elif args.dry_run:
            with tempfile.TemporaryDirectory(prefix='daily-paper-radar-preview-') as folder:
                temp = Path(folder)
                if (state / 'seen.json').exists():
                    shutil.copy2(state / 'seen.json', temp / 'seen.json')
                # 预览中的收件箱也隔离，防止覆盖正式日报。
                profile['inbox_dir'] = str(temp / 'inbox')
                preview_profile = temp / 'profile.json'
                write_json(preview_profile, profile)
                pipeline(preview_profile, temp, True, allow_peak=args.allow_peak)
                state.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp / 'output/digest.md', state / 'preview.md')
                from render_digest import _read_papers, render_digest
                from sinks.feishu_bot import _build_card
                enriched = temp / 'output/papers.json'
                preview_papers, _ = _read_papers(enriched if enriched.exists() else temp / 'output/raw_papers.json')
                feishu_md = render_digest(preview_papers, beijing_today(), profile, mode='concise')
                (state / 'preview-feishu.md').write_text(feishu_md, encoding='utf-8')
                write_json(state / 'preview-feishu.json', _build_card(
                    f"{digest_title(profile)} · {beijing_today().isoformat()}", feishu_md, 'blue'))
                print(f'预览已保存：{state / "preview.md"}')
        else:
            action = 'prepare' if args.prepare else 'finish' if args.finish else 'analyze' if args.analyze_only else 'publish' if args.publish_only else 'reissue' if args.reissue else None
            pipeline(profile_path, state, action=action, allow_peak=args.allow_peak)
        return 0
    except Exception as exc:
        print(redact(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
