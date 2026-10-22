"""将 GitHub Actions 配置生成临时 profile；凭据始终只存在于环境变量。"""
from __future__ import annotations
import json
import os
from runtime import ROOT, write_json


def build_profile(env):
    profile = json.loads((ROOT / 'config/_template.json').read_text(encoding='utf-8'))
    # 云端未填主题时生成通用精选；不继承模板的演示关键词。
    profile['keywords'] = [s.strip() for s in env.get('PAPER_KEYWORDS', '').split(',') if s.strip()]
    profile['focus_description'] = env.get('PAPER_FOCUS', '').strip()
    profile['paper_preferences'] = env.get('PAPER_PREFERENCES', '').strip()
    from digest_language import digest_language, digest_title
    profile['digest_language'] = env.get('DIGEST_LANGUAGE', '').strip() or 'zh'
    digest_language(profile)
    profile['digest_title'] = env.get('DIGEST_TITLE', '').strip()
    profile['digest_title'] = digest_title(profile)
    def number(name, default, minimum=1, maximum=1000):
        value = int(env.get(name) or default)
        if not minimum <= value <= maximum:
            raise ValueError(f'{name} 必须在 {minimum}–{maximum} 之间')
        return value
    def boolean(name, default):
        value = (env.get(name) or str(default)).lower()
        if value not in ('true', 'false'):
            raise ValueError(f'{name} 必须为 true 或 false')
        return value == 'true'
    hf = profile['sources']['huggingface']
    hf.update(enabled=boolean('HF_ENABLED', True), lookback_days=number('HF_LOOKBACK_DAYS', 3, 1, 14),
              min_upvotes=number('HF_MIN_UPVOTES', 0, 0), max_papers=number('HF_MAX_PAPERS', 20))
    profile['sources']['arxiv']['enabled'] = boolean('ARXIV_ENABLED', False)
    if env.get('ARXIV_CATEGORIES', '').strip():
        profile['categories'] = [x.strip() for x in env['ARXIV_CATEGORIES'].split(',') if x.strip()]
    profile['paper_metadata'] = {'enabled': boolean('PAPER_METADATA_ENABLED', True)}
    profile['source_gate'].update(enabled=boolean('SOURCE_GATE_ENABLED', False),
        pdf_affiliation_fallback=boolean('PDF_AFFILIATION_FALLBACK', True),
        max_qs_rank=number('MAX_QS_RANK', 100, 1, 100),
        unknown_policy=env.get('UNKNOWN_INSTITUTION_POLICY') or 'reject',
        code_policy=env.get('CODE_POLICY') or 'prefer',
        max_metadata_candidates=number('MAX_METADATA_CANDIDATES', 100, 1, 500))
    profile['render']['max_low'] = number('MAX_LOW_PAPERS', 5, 0, 20)
    profile['render']['max_detailed'] = number('MAX_DETAILED_PAPERS', 10, 1, 20)
    profile['llm_enrich']['backend'] = 'api'
    profile['llm_enrich']['api'].update(concurrency=number('LLM_CONCURRENCY', 4, 1, 16),
                                      max_papers=number('LLM_MAX_PAPERS', 100),
                                      request_timeout_s=number('LLM_TIMEOUT_SECONDS', 60, 1, 600))
    sink = {'type': 'feishu_bot', 'enabled': True, 'webhook_env': 'FEISHU_WEBHOOK'}
    if env.get('FEISHU_SECRET', '').strip():
        sink['secret_env'] = 'FEISHU_SECRET'
    profile['sinks'] = [sink]
    if env.get('FEISHU_DOC_ID', '').strip():
        profile['sinks'].append({'type': 'feishu_doc', 'enabled': True, 'body': 'full',
                                 'document_id_env': 'FEISHU_DOC_ID',
                                 'app_id_env': 'FEISHU_APP_ID', 'app_secret_env': 'FEISHU_APP_SECRET'})
    return profile


if __name__ == '__main__':
    write_json(ROOT / 'config/profile.actions.json', build_profile(os.environ))
    print('云端配置已生成；密钥未写入文件。')
