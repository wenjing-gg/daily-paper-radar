"""按用户提供的计费时段限制 API 请求；不推断服务商实际价格。"""
from datetime import datetime, timedelta, timezone
import os
import re
from zoneinfo import ZoneInfo


class PeakWindowError(RuntimeError):
    """计费窗口暂不允许请求；配置错误仍应让任务失败。"""


def us_standard_time(now):
    """2007 年起的美东规则；用于云端冬令时例外，Windows 无需时区包。"""
    now = now.astimezone(timezone.utc)
    def sunday(month, occurrence, hour):
        first = datetime(now.year, month, 1, hour, tzinfo=timezone.utc)
        return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (occurrence - 1))
    return not sunday(3, 2, 7) <= now < sunday(11, 1, 6)


def freshness_priority(env):
    return (env.get('ARXIV_FRESHNESS_PRIORITY') or 'false').lower() == 'true'


def assert_offpeak(env=None, now=None):
    env = os.environ if env is None else env
    enabled = (env.get('LLM_OFFPEAK_ONLY') or 'true').lower()
    if enabled not in ('true', 'false'):
        raise RuntimeError('LLM_OFFPEAK_ONLY 必须为 true 或 false')
    if enabled == 'false':
        return
    name = env.get('LLM_BILLING_TIMEZONE') or 'Asia/Shanghai'
    # Windows 的标准 Python 未必带 IANA 数据；中国计费时区无需额外依赖。
    zone = timezone(timedelta(hours=8)) if name == 'Asia/Shanghai' else ZoneInfo(name)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    guard = int(env.get('LLM_PEAK_GUARD_MINUTES') or 10)
    if not 0 <= guard <= 120:
        raise RuntimeError('LLM_PEAK_GUARD_MINUTES 必须在 0–120 之间')
    if freshness_priority(env) and name == 'Asia/Shanghai' and us_standard_time(current):
        end = datetime.strptime(env.get('WINTER_PEAK_UNTIL') or '10:30', '%H:%M')
        minute = current.hour * 60 + current.minute
        if 9 * 60 <= minute and minute + guard < end.hour * 60 + end.minute:
            return  # 用户明确选择“当天新论文优先”的冬令时高峰例外。
    weekdays = {int(x.strip()) for x in (env.get('LLM_PEAK_WEEKDAYS') or '1,2,3,4,5').split(',')}
    if not weekdays or not weekdays <= set(range(1, 8)):
        raise RuntimeError('LLM_PEAK_WEEKDAYS 需使用 1–7，英文逗号分隔')
    holidays = {s.strip() for s in (env.get('LLM_OFFPEAK_HOLIDAYS') or '').split(',') if s.strip()}
    windows = []
    for window in (env.get('LLM_PEAK_WINDOWS') or '09:00-12:00,14:00-18:00').split(','):
        match = re.fullmatch(r'(\d{2}):(\d{2})-(\d{2}):(\d{2})', window.strip())
        if not match:
            raise RuntimeError('LLM_PEAK_WINDOWS 格式应为 09:00-12:00,14:00-18:00')
        sh, sm, eh, em = map(int, match.groups())
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            raise RuntimeError('高峰时段的时分无效')
        start, end = sh * 60 + sm, eh * 60 + em
        if start >= end:
            raise RuntimeError('单个高峰区间不能跨日，请拆成同日区间')
        windows.append((start, end))
    # 连同安全余量跨午夜检查，避免在下个高峰开始前发起长请求。
    for offset in range(guard + 1):
        point = current + timedelta(minutes=offset)
        if point.isoweekday() not in weekdays or point.date().isoformat() in holidays:
            continue
        minute = point.hour * 60 + point.minute
        if any(start <= minute < end for start, end in windows):
            raise PeakWindowError('当前处于或即将进入配置的 LLM 高峰时段，已阻止 API 调用；请在空闲时段重跑分析')
