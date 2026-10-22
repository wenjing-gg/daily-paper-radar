"""日报语言只影响内容与展示，不改变配置字段名及日志语言。"""


def digest_language(profile):
    language = profile.get('digest_language', 'zh')
    if language not in ('zh', 'en'):
        raise ValueError('digest_language 仅支持 zh（中文）或 en（英文）')
    return language


def digest_title(profile):
    return profile.get('digest_title') or ('Daily Paper Radar' if digest_language(profile) == 'en' else '论文日报')
