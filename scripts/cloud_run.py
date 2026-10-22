"""将云端分析与投递分开；定时分析超过推送时间后自动补发已生成日报。"""
import argparse
import json
from datetime import datetime, timezone, timedelta
import os
import subprocess
import sys
from runtime import ROOT, write_json
from llm_budget import assert_offpeak, us_standard_time, PeakWindowError


def read_state(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def tick(command, env, state, clock=None, run=None):
    """串行工作流内恢复当天任务；已生成只投递，已完成不重复分析。"""
    clock = clock or (lambda: datetime.now(timezone.utc))
    run = run or (lambda flags: subprocess.run(command + flags, check=True))
    now = clock()
    local = now.astimezone(timezone(timedelta(hours=8)))
    today = local.date().isoformat()
    print(f'定时检查：UTC={now.isoformat()}；北京时间={local.isoformat()}；'
          f'cron={env.get("RADAR_SCHEDULE", "manual")}', flush=True)
    pending = read_state(state / 'pending.json')
    if not pending:
        if read_state(state / 'schedule.json').get('completed_date') == today:
            print('当天批次已完成；不抓取、不调用模型、不重复投递。', flush=True)
            return
        # 升级兼容：旧版本没有完成标记，但完成后才写 seen 并删除 pending。
        raw = read_state(state / 'output/raw_papers.json')
        stamp = raw.get('generated_at')
        papers = raw.get('papers', [])
        seen = set(read_state(state / 'seen.json'))
        if (stamp and papers and (state / 'output/digest.md').exists()
                and datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(local.tzinfo).date() == local.date()
                and all(p['arxiv_id'] in seen for p in papers)):
            write_json(state / 'schedule.json', {'completed_date': today})
            print('已识别旧版本当天成功批次；不重复分析或投递。', flush=True)
            return
    if not pending or pending.get('phase') != 'rendered':
        earliest = (9 if us_standard_time(now) else 8, 10)
        if (local.hour, local.minute) < earliest:
            print('尚未到当天 arXiv 发布后的分析窗口，等待下一次检查。', flush=True)
            return
        try:
            assert_offpeak(env, now)
        except PeakWindowError as exc:
            if late_publish_due(dict(env, ALLOW_LATE_PUBLISH='true'), now):
                print('::warning::已超过北京时间推送目标，但日报尚未生成；'
                      '当前高峰保护阻止分析，本次没有发送日报。绿色检查不代表投递成功。', flush=True)
            print(f'{exc}；保留状态，等待下一次允许分析的检查。', flush=True)
            return
        run(['--analyze-only'])
    if late_publish_due(dict(env, ALLOW_LATE_PUBLISH='true'), clock()):
        run(['--publish-only'])
    else:
        print('日报已生成，尚未到北京时间推送时间，保留待发批次。', flush=True)


def late_publish_due(env, now=None):
    """仅定时分析可补发；补发已生成正文不涉及放宽模型计费保护。"""
    if env.get('ALLOW_LATE_PUBLISH') != 'true':
        return False
    value = env.get('PUBLISH_TIME_BEIJING') or '09:30'
    try:
        hour, minute = map(int, value.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ValueError('PUBLISH_TIME_BEIJING 必须是 HH:MM 北京时间') from None
    local = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=8)))
    return (local.hour, local.minute) >= (hour, minute)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['tick', 'preview', 'analyze', 'publish', 'all', 'check', 'reissue', 'resend_bot'])
    operation = parser.parse_args().operation
    if os.environ.get('ALLOW_PEAK_RUN') == 'true':
        print('本次手动运行允许高峰模型调用；仓库的定时低峰保护设置不变。', flush=True)
        os.environ['LLM_OFFPEAK_ONLY'] = 'false'
    if operation in ('preview', 'analyze', 'all', 'reissue'):
        assert_offpeak()  # 抓取前先检查；每次 API 请求还会重新检查。
    if operation == 'resend_bot':
        env = dict(os.environ, DAILY_PAPER_RADAR_PROFILE=str(ROOT / 'config/profile.actions.json'))
        subprocess.run([sys.executable, str(ROOT / 'scripts/publish.py'), '--resend-bot'], env=env, check=True)
        return
    command = [sys.executable, str(ROOT / 'scripts/run_daily.py'), '--profile', str(ROOT / 'config/profile.actions.json')]
    if operation == 'tick':
        tick(command, os.environ, ROOT / 'state')
        return
    flags = {'preview': ['--dry-run'], 'analyze': ['--analyze-only'],
             'publish': ['--publish-only'], 'all': [], 'reissue': ['--reissue'], 'check': ['--check']}
    subprocess.run(command + flags[operation], check=True)
    if operation == 'analyze' and late_publish_due(os.environ):
        print('定时分析完成时已到推送时间，立即补发本批日报；不额外调用模型。', flush=True)
        subprocess.run(command + ['--publish-only'], check=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
