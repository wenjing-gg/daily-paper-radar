"""从论文作者栏提取明确的一作机构，并保留摘要中的代码链接。"""
from html.parser import HTMLParser
import re
import urllib.request


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)

    def find(self, cls):
        result = [self] if cls in self.attrs.get('class', '').split() else []
        for c in self.children:
            if isinstance(c, Node):
                result.extend(c.find(cls))
        return result

    def links(self):
        result = [self.attrs.get('href', '')]
        for child in self.children:
            if isinstance(child, Node):
                result.extend(child.links())
        return result


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def code_links(text):
    # 只识别代码托管平台的仓库地址，不把任意链接猜成项目代码。
    return list(dict.fromkeys(s.rstrip('.') for s in re.findall(r'https://(?:github\.com|gitlab\.com)/[\w.-]+/[\w.-]+', text)))


def parse_metadata(html, author):
    doc = Document()
    doc.feed(html)
    result = {}
    # 只读取出版元数据，不从模板名称或参考文献猜测会议。
    def venue_meta(node):
        if node.tag == 'meta' and node.attrs.get('name', '').lower() in {'citation_conference_title', 'citation_journal_title'}:
            value = node.attrs.get('content', '').strip()
            if value and 'arxiv' not in value.lower():
                return value
        for child in node.children:
            if isinstance(child, Node):
                value = venue_meta(child)
                if value:
                    return value
        return ''
    venue = venue_meta(doc.root)
    if venue:
        result['venue'] = venue
    authors = doc.root.find('ltx_role_author')
    if authors:
        first = authors[0]
        names = first.find('ltx_personname')
        normalize = lambda s: re.sub(r'[^\w]', '', s).casefold()
        if len(names) == 1 and normalize(names[0].text()) == normalize(author):
            orgs = [re.sub(r'^Affiliation\s*:\s*', '', n.text().strip()) for n in first.find('ltx_role_affiliation')]
            orgs = [' '.join(s.split()) for s in orgs if s.strip()]
            if orgs:
                result['first_author_affiliation'] = '；'.join(dict.fromkeys(orgs))
    # 仅在摘要范围内取链接，不误收参考文献中其他工作的仓库。
    abstracts = doc.root.find('ltx_abstract')
    result['code_urls'] = code_links(' '.join(n.text() + ' ' + ' '.join(n.links()) for n in abstracts))
    return result


def enrich_metadata(paper):
    out = dict(paper)
    links = list(paper.get('code_urls', [])) + code_links(paper.get('summary', ''))
    aid = paper.get('arxiv_id', '')
    if not re.fullmatch(r'\d{4}\.\d{4,5}', aid):
        return out
    url = f'https://arxiv.org/html/{aid}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'daily-paper-radar/2.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read(2_000_000).decode('utf-8', errors='replace')
        metadata = parse_metadata(html, paper.get('authors', '').split(',')[0].strip())
        links += metadata.pop('code_urls', [])
        out.update(metadata)
        if metadata.get('venue'):
            out['venue_source'] = url
        if metadata.get('first_author_affiliation'):
            out['affiliation_source'] = url
        out['metadata_status'] = 'checked'
    except Exception:
        # 辅助信息不可用时仍推送论文，不能把网络失败当成“没有机构/代码”。
        out['metadata_status'] = 'unavailable'
    out['code_urls'] = list(dict.fromkeys(links))
    return out
