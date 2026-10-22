"""在模型调用之前按有来源的一作机构筛选，保留可审计原因。"""
import json
import re
import unicodedata
from runtime import ROOT


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^\w]+', ' ', text.casefold()).split())


def matches(text, aliases):
    text = ' ' + normalize(text) + ' '
    for alias in aliases:
        needle = normalize(alias)
        if not needle:
            continue
        for match in re.finditer(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', text):
            # 避免把 Indiana University of Pennsylvania 认作宾大、
            # 把 Chinese University of Hong Kong 认作港大等名称包含关系。
            prefix = text[:match.start()].strip()
            if 'university' in needle:
                previous = prefix.split()[-1:] or ['']
                if previous[0] in {'indiana', 'chinese', 'city', 'state', 'national'}:
                    continue
            return True
    return False


def load_policy(cfg):
    def read(name, default):
        path = ROOT / cfg.get(name, default)
        return json.loads(path.read_text(encoding='utf-8'))
    ranking = read('ranking_file', 'config/qs_top100.json')
    teams = read('teams_file', 'config/trusted_teams.json')['teams']
    limit = int(cfg.get('max_qs_rank', 100))
    if not 1 <= limit <= 100:
        raise ValueError('source_gate.max_qs_rank 必须为 1–100，当前快照仅覆盖前100')
    if cfg.get('code_policy', 'prefer') not in ('prefer', 'required', 'off'):
        raise ValueError('source_gate.code_policy 必须为 prefer、required 或 off')
    if cfg.get('unknown_policy', 'reject') not in ('reject', 'keep'):
        raise ValueError('source_gate.unknown_policy 必须为 reject 或 keep')
    if not ranking.get('universities') or not ranking.get('edition') or not ranking.get('source'):
        raise ValueError('QS 排名快照无效，停止分析，不能静默跳过筛选')
    return ranking, teams, limit


def decide(paper, cfg, policy):
    ranking, teams, limit = policy
    org = paper.get('first_author_affiliation', '')
    result = {'accepted': False, 'reason': '', 'institution': '',
              'ranking_edition': ranking['edition'], 'ranking_source': ranking['source'],
              'affiliation_source': paper.get('affiliation_source', ''),
              'affiliation_check': paper.get('affiliation_check', paper.get('metadata_status', 'not_checked')),
              'code_status': 'link_found_unverified' if paper.get('code_urls') else 'not_found'}
    if not org or not paper.get('affiliation_source'):
        result.update(accepted=cfg.get('unknown_policy', 'reject') == 'keep', reason='unverified_affiliation')
    else:
        university = next((u for u in ranking['universities'] if u['rank'] <= limit and matches(org, u['aliases'])), None)
        team = next((t for t in teams if matches(org, t['aliases'])), None)
        if university:
            result.update(accepted=True, reason='qs_top', institution=university['name'], rank=university['rank'])
        elif team:
            result.update(accepted=True, reason='trusted_team', institution=team['name'])
        elif matches(org, ['Independent Researcher', 'Independent Research', 'Unaffiliated']):
            result['reason'] = 'independent_affiliation'
        else:
            result['reason'] = 'outside_allowed_institutions'
    if result['accepted'] and cfg.get('code_policy', 'prefer') == 'required' and not paper.get('code_urls'):
        result.update(accepted=False, reason='no_code_link')
    return result


def apply_gate(papers, cfg):
    if not cfg.get('enabled', False):
        return papers, {'enabled': False}
    policy = load_policy(cfg)
    decisions, accepted = [], []
    for paper in papers:
        decision = decide(paper, cfg, policy)
        decisions.append({'arxiv_id': paper['arxiv_id'], **decision})
        if decision['accepted']:
            accepted.append({**paper, 'source_gate': decision})
    if cfg.get('code_policy', 'prefer') == 'prefer':
        accepted.sort(key=lambda p: not bool(p.get('code_urls')))
    return accepted, {'enabled': True, 'ranking_edition': policy[0]['edition'],
                      'evaluated': len(papers), 'accepted': len(accepted),
                      'rejected': len(papers) - len(accepted), 'decisions': decisions}
