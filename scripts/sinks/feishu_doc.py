"""按日期将完整日报追加到飞书新版文档末尾，分段保存写入回执。"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from runtime import STATE, write_json

BASE = 'https://open.feishu.cn/open-apis'
CHUNK_SIZE = 40


def document_id(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urllib.parse.urlsplit(value)
        if not (parsed.hostname or '').endswith('.feishu.cn'):
            raise ValueError('归档文档必须是飞书新版文档链接或文档 ID')
        match = re.fullmatch(r'/(?:docx|wiki)/([A-Za-z0-9]+)', parsed.path.rstrip('/'))
        if not match:
            raise ValueError('请使用 /docx/ 新版文档或 /wiki/ 知识库文档链接；不支持旧版 /docs/ 链接')
        value = match[1]
    if not re.fullmatch(r'[A-Za-z0-9]+', value):
        raise ValueError('飞书文档 ID 无效')
    return value


def request(path, payload=None, token=None):
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method='POST' if payload is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            data = json.load(exc)
        except Exception:
            raise RuntimeError(f'飞书文档请求失败（HTTP {exc.code}），请检查应用权限和文档授权') from None
        if data.get('code') == 0:
            raise RuntimeError(f'飞书文档请求失败（HTTP {exc.code}）') from None
    except Exception:
        raise RuntimeError('飞书文档请求失败，请检查网络、应用权限和文档授权后重试') from None
    if data.get('code') != 0:
        code = data.get('code')
        raise RuntimeError(f'飞书文档接口拒绝请求（错误码 {code if isinstance(code, int) else "未知"}），请检查应用发布状态、权限及文档授权')
    return data


def text_elements(line):
    """保留当前日报中的加粗和超链接；不把 Markdown 语法原样写进文档。"""
    result = []
    pattern = r'\[([^\]]+)\]\((https?://[^\s)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*'
    cursor = 0
    def add(content, style=None):
        for start in range(0, len(content), 1500):
            run = {'content': content[start:start+1500]}
            if style:
                run['text_element_style'] = style
            result.append({'text_run': run})
    for match in re.finditer(pattern, line):
        add(line[cursor:match.start()])
        if match[1]:
            add(match[1], {'link': {'url': match[2]}})
        elif match[3]:
            add(match[3], {'bold': True})
        else:
            add(match[4], {'italic': True})
        cursor = match.end()
    add(line[cursor:])
    return result


def blocks(title, markdown):
    result = [{'block_type': 3, 'heading1': {'elements': text_elements(title)}}]
    for index, line in enumerate(markdown.splitlines()):
        line = line.strip()
        if not line or line == '---' or (index == 0 and line.startswith('**')):
            continue
        kind, key = (4, 'heading2') if re.match(r'^\*\*\d+\. ', line) else (2, 'text')
        elements = text_elements(line)
        # 每块最多 1500 字，长输入切分而非截断。
        current, count = [], 0
        for element in elements:
            length = len(element['text_run']['content'])
            if current and count + length > 1500:
                result.append({'block_type': kind, key: {'elements': current}})
                current, count = [], 0
            current.append(element)
            count += length
        if current:
            result.append({'block_type': kind, key: {'elements': current}})
    return result


def send(title, markdown, sink_cfg, profile, today):
    target = os.environ.get(sink_cfg.get('document_id_env', 'FEISHU_DOC_ID'), '').strip()
    doc = document_id(target)
    app_id = os.environ.get(sink_cfg.get('app_id_env', 'FEISHU_APP_ID'), '').strip()
    app_secret = os.environ.get(sink_cfg.get('app_secret_env', 'FEISHU_APP_SECRET'), '').strip()
    if not app_id or not app_secret:
        raise RuntimeError('文档归档缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET')
    token = None
    if target.startswith('https://') and urllib.parse.urlsplit(target).path.startswith('/wiki/'):
        token = request('/auth/v3/tenant_access_token/internal', {'app_id': app_id, 'app_secret': app_secret})['tenant_access_token']
        node = request('/wiki/v2/spaces/get_node?' + urllib.parse.urlencode({'token': doc}), token=token).get('data', {}).get('node', {})
        if node.get('obj_type') != 'docx':
            raise ValueError('知识库节点必须是新版文档，不能是表格或其他文件类型')
        doc = document_id(node.get('obj_token', ''))
    content = blocks(title, markdown)
    fingerprint = hashlib.sha256(json.dumps([doc, title, content], ensure_ascii=False).encode()).hexdigest()
    receipt_path = STATE / 'output/doc_delivery.json'
    receipts = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
    completed = set(receipts.get(fingerprint, []))
    for offset in range(0, len(content), CHUNK_SIZE):
        part = offset // CHUNK_SIZE
        if part in completed:
            continue
        if token is None:
            token = request('/auth/v3/tenant_access_token/internal', {'app_id': app_id, 'app_secret': app_secret})['tenant_access_token']
        # 确定性的客户端幂等标识：响应丢失后重试同一段仍使用同一个值。
        nonce = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{doc}:{fingerprint}:{part}'))
        query = urllib.parse.urlencode({'document_revision_id': -1, 'client_token': nonce})
        request(f'/docx/v1/documents/{doc}/blocks/{doc}/children?{query}',
                {'children': content[offset:offset+CHUNK_SIZE], 'index': -1}, token)
        completed.add(part)
        receipts[fingerprint] = sorted(completed)
        write_json(receipt_path, receipts)
        if offset + CHUNK_SIZE < len(content):
            time.sleep(0.4)
    return {'blocks': len(content), 'parts': len(completed)}
