"""统一 LLM 环境变量与 OpenAI / Anthropic 原生协议适配。"""
from __future__ import annotations
import os
from urllib.parse import urlsplit, urlunsplit


def resolve_settings(cfg):
    base = os.environ.get('LLM_BASE_URL', '').strip().rstrip('/')
    model = os.environ.get('LLM_MODEL_NAME', '').strip()
    if not base or not model:
        raise ValueError('请在 .env 或环境变量中填写 LLM_BASE_URL 和 LLM_MODEL_NAME')
    if cfg.get('require_api_key', True) and not os.environ.get('LLM_API_KEY', '').strip():
        raise ValueError('请在 .env 或环境变量中填写 LLM_API_KEY')
    parts = urlsplit(base)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('LLM_BASE_URL 必须是 HTTP(S) 地址，不能包含凭据、查询参数或片段')
    path = parts.path.rstrip('/')
    explicit = 'anthropic' if path.endswith('/messages') else 'openai' if path.endswith('/chat/completions') else None
    protocol = cfg.get('protocol', 'auto')
    if protocol not in ('auto', 'openai', 'anthropic'):
        raise ValueError('api.protocol 必须为 auto、openai 或 anthropic')
    if protocol == 'auto':
        protocol = explicit or ('anthropic' if parts.hostname == 'api.anthropic.com' else 'openai')
    if explicit and explicit != protocol:
        raise ValueError('LLM_BASE_URL 的接口路径与 api.protocol 冲突')
    if not explicit:
        suffix = '/messages' if protocol == 'anthropic' else '/chat/completions'
        # 根域名自动补 v1；自定义路径视作完整 API 前缀，避免破坏 /api/v4 等网关路径。
        path = (path or '/v1') + suffix
    endpoint = urlunsplit((parts.scheme, parts.netloc, path, '', ''))
    max_tokens = int(cfg.get('max_tokens', 4096))
    if max_tokens < 1:
        raise ValueError('api.max_tokens 必须为正整数')
    return {'base_url': base, 'endpoint': endpoint, 'model': model, 'protocol': protocol, 'max_tokens': max_tokens}


def build_request(cfg, system, user):
    settings = resolve_settings(cfg)
    # 部分网关（如 Cloudflare 前置的中转站）拦截 Python 默认 UA（HTTP 403 code 1010），补浏览器 UA。
    headers = {'Content-Type': 'application/json',
               'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 daily-paper-radar/1.0'}
    key = os.environ.get('LLM_API_KEY', '').strip()
    payload = {'model': settings['model']}
    if settings['protocol'] == 'anthropic':
        if key:
            headers['x-api-key'] = key
        headers['anthropic-version'] = '2023-06-01'
        payload.update(system=system, messages=[{'role': 'user', 'content': user}], max_tokens=settings['max_tokens'])
    else:
        if key:
            headers['Authorization'] = f'Bearer {key}'
        payload['messages'] = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if cfg.get('temperature') is not None:
        payload['temperature'] = cfg['temperature']
    return settings, headers, payload


def response_text(data, protocol):
    if not isinstance(data, dict):
        raise ValueError('模型响应不是 JSON 对象')
    if protocol == 'anthropic':
        if data.get('stop_reason') in ('max_tokens', 'refusal'):
            raise ValueError('Anthropic 输出被截断或拒绝，请检查模型配置')
        blocks = data.get('content', [])
        text = ''.join(b.get('text', '') for b in blocks if isinstance(b, dict) and b.get('type') == 'text')
    else:
        choices = data.get('choices') or []
        if not choices:
            raise ValueError('OpenAI 兼容响应缺少 choices')
        choice = choices[0]
        if choice.get('finish_reason') in ('length', 'content_filter'):
            raise ValueError('OpenAI 兼容输出被截断或过滤')
        text = choice.get('message', {}).get('content')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('模型未返回可用的文本分析')
    return text
