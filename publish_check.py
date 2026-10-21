#!/usr/bin/env python3
"""Public release checks. No credentials, browser sessions, remote writes, or retries.

Default: fetch production HTML/XML; --local: read dist HTML/XML.
Expected page inventory always comes from built HTML files in --dir (default dist).
Internal links: all a/link href and media/script src in those HTML documents,
including nav/footer and noindex utility pages (except the intentional 404 page).
Queries are stripped for availability; fragments are checked against target IDs.
No JS execution, CSS url() crawling, authenticated API calls, or external link audit.

Overlap: visible HTML <main> text only, excludes nav/header/footer/aside,
script/style/noscript/template/textarea, hidden/aria-hidden elements. Hidden-by-CSS
cannot be inferred from raw HTML. Unicode words, casefold, curly apostrophes
normalized; regex is recorded in the JSON report. An 8-word window counts once
per owned-page position if found in the reference set. Directional coverage,
not Jaccard or unique-window percentage. Threshold defaults to strictly less than 15%; configurable with --max-overlap.
--local still fetches the public reference unless --reference-file is supplied.
Snapshots, SHA256 hashes, extracted texts, tokens and numerator/denominator are
saved together for independent reproduction. Competitor text is never printed.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ORIGIN = ''
REFERENCE = ''
TOKENIZER = r"\b\w+(?:'\w+)*\b"
OMIT = {'script','style','noscript','template','textarea','nav','header','footer','aside'}
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.stack=[]; self.main=[]; self.body=[]; self.refs=[]; self.ids=set()
        self.schema=[]; self.ld=None; self.canonical=None; self.noindex=False
        self.has_main=False; self.feed=False
        self.feed_html(raw)
    def feed_html(self, raw):
        super().feed(raw); super().close()
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if a.get('id'): self.ids.add(a['id'])
        if tag=='a' and a.get('name'): self.ids.add(a['name'])
        if tag in {'a','link'} and 'href' in a: self.refs.append(a['href'])
        if tag in {'img','script','video','audio','source','iframe'} and a.get('src'): self.refs.append(a['src'])
        if tag=='video' and a.get('poster'): self.refs.append(a['poster'])
        if tag=='link':
            if a.get('rel')=='canonical':self.canonical=a.get('href')
            if a.get('type')=='application/rss+xml':self.feed=True
        if tag=='meta' and a.get('name')=='robots':self.noindex='noindex' in a.get('content','').lower()
        if tag=='script' and a.get('type','').lower()=='application/ld+json': self.ld=[]
        if tag=='main':self.has_main=True
        parent_hidden=any(x[1] for x in self.stack)
        hidden=parent_hidden or 'hidden' in a or a.get('aria-hidden')=='true' or tag in OMIT
        if tag not in VOID:self.stack.append((tag,hidden))
        if tag in {'p','br','div','li','h1','h2','h3','section','article','tr','td','th'}:self.main.append(' ');self.body.append(' ')
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self, tag):
        if tag=='script' and self.ld is not None:self.schema.append(''.join(self.ld));self.ld=None
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];break
        self.main.append(' ');self.body.append(' ')
    def handle_data(self, data):
        if self.ld is not None:self.ld.append(data)
        if not any(x[1] for x in self.stack):
            if any(x[0]=='main' for x in self.stack):self.main.append(data)
            if any(x[0]=='body' for x in self.stack):self.body.append(data)
    def text(self, main=False):return ' '.join(''.join(self.main if main else self.body).split())

def sha(data):return hashlib.sha256(data).hexdigest()
def nodes(value):
    if isinstance(value,list):
        for item in value:yield from nodes(item)
    elif isinstance(value,dict):
        yield value
        if '@graph' in value:yield from nodes(value['@graph'])

def main():
    global ORIGIN, REFERENCE
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--site-url',required=True,help='Public origin to audit, e.g. https://example.com')
    parser.add_argument('--reference-url',required=True,help='Public comparison homepage (used only for measurement)')
    parser.add_argument('--require-text',action='append',required=True,help='Required body-copy fact; repeat for multiple facts')
    parser.add_argument('--forbid-text',action='append',default=[],help='Forbidden literal phrase anywhere in HTML; repeat as needed')
    parser.add_argument('--feed-path',help='Optional RSS feed path to validate with sitemap coverage')
    parser.add_argument('--feed-min-items',type=int,default=0)
    parser.add_argument('--max-overlap',type=float,default=15,help='Strict upper bound for directional 8-gram coverage, default 15 percent')
    parser.add_argument('--local',action='store_true')
    parser.add_argument('--dir',type=Path,default=Path.cwd()/'dist',help='Expected built inventory; with --local also the HTML/XML source')
    parser.add_argument('--reference-file',type=Path,help='Explicit recorded public reference HTML; otherwise fetch current reference')
    parser.add_argument('--output',type=Path,help='Report/snapshot directory (default: new OS temp directory)')
    args=parser.parse_args(); ORIGIN=args.site_url.rstrip('/'); REFERENCE=args.reference_url
    origin_parts=urllib.parse.urlsplit(ORIGIN)
    if origin_parts.scheme not in {'http','https'} or not origin_parts.hostname or origin_parts.path or origin_parts.query or origin_parts.fragment:parser.error('--site-url must be an HTTP(S) origin without a path/query/fragment')
    allowed_hosts={origin_parts.hostname, origin_parts.hostname.removeprefix('www.'), 'www.'+origin_parts.hostname.removeprefix('www.')}
    if not 0<args.max_overlap<=100:parser.error('--max-overlap must be >0 and <=100')
    if args.feed_min_items<0:parser.error('--feed-min-items cannot be negative')
    root=args.dir.resolve();out=(args.output or Path(tempfile.mkdtemp(prefix='geo-publish-check-'))).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'started_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'mode':'local dist' if args.local else 'production HTTP','inventory':str(root),'sections':[],'scope':{'links':'a/link href + img/script/video/audio/source/iframe src + video poster; all built HTML including nav/footer and noindex utility pages; excludes intentional 404, CSS url(), runtime JS, external/mailto/tel/data links','availability':'GET for HTML/XML; HEAD for linked non-HTML resources; fragments checked; query values do not affect availability','overlap':'8-gram owned-position coverage; main only; excludes nav/footer/header/aside/script/style/noscript/template/textarea/hidden/aria-hidden; no CSS layout execution','tokenizer':TOKENIZER,'token_normalization':'HTML entities decoded, curly apostrophes -> ASCII, Unicode casefold','expected_inventory':'built dist HTML canonical paths whose robots meta does not contain noindex; source text for default checks is fetched live'}}
    cache={};documents={};inventory={};indexed=set()
    def save_report(): (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def fail(message):raise RuntimeError(message)
    def path_file(path):
        path=urllib.parse.unquote(path)
        candidate=root/('index.html' if path=='/' else path.lstrip('/'))
        if not candidate.suffix:candidate=candidate.with_suffix('.html')
        if not candidate.resolve().is_relative_to(root):fail('Path escapes built directory')
        return candidate
    def fetch(path,body=True):
        # Public URLs only; no browser cookies or authorization headers.
        url=ORIGIN+path if path.startswith('/') else path
        if args.local and url.startswith(ORIGIN+'/'):
            p=path_file(urllib.parse.urlsplit(url).path)
            if not p.is_file():fail('Missing local target: '+str(p.relative_to(root)))
            return 200,p.read_bytes(),url
        request=urllib.request.Request(url,method='GET' if body else 'HEAD',headers={'User-Agent':'GeoToolkitPublishCheck/1.0'})
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                data=response.read() if body else b'';status=response.status;final=response.url
        except urllib.error.HTTPError as e:fail('HTTP '+str(e.code)+' '+url)
        # Blocking challenge, not normal sign-in UI. No retry is performed.
        if body and (re.search(rb'<title>\s*(?:Just a moment|Verify you are human|Attention Required)',data,re.I) or b'/cdn-cgi/challenge-platform/' in data):fail('CAPTCHA/security challenge; stop and ask user: '+url)
        if status!=200:fail('Expected 200, got '+str(status)+' '+url)
        return status,data,final
    def load(path):
        if path not in cache:cache[path]=fetch(path)
        return cache[path][1]
    def urls_from(xml):
        tree=ET.fromstring(xml)
        result=[e.text for e in tree.iter() if e.tag.rsplit('}',1)[-1]=='loc']
        if not result or len(result)!=len(set(result)):fail('Empty sitemap or duplicate loc entries')
        if any(not u.startswith(ORIGIN+'/') for u in result):fail('Unexpected sitemap origin')
        return set(result)
    def section(number,label,fn):
        print(f'[{number}/6] {label}',flush=True)
        try:
            details=fn();report['sections'].append({'number':number,'label':label,'ok':True,'details':details});print('PASS '+json.dumps(details,ensure_ascii=False),flush=True);save_report()
        except Exception as e:
            report['sections'].append({'number':number,'label':label,'ok':False,'error':str(e)});save_report();print('FAIL '+str(e)+'\nReport: '+str(out/'report.json'),file=sys.stderr,flush=True);sys.exit(1)
    def status_check():
        if not root.is_dir():fail('Build the audited website first and pass --dir')
        for p in sorted(root.rglob('*.html')):
            if p.name=='404.html':continue
            local=Document(p.read_text());relative=p.relative_to(root).as_posix();path='/' if relative=='index.html' else '/'+str(Path(relative).with_suffix(''))
            if local.canonical and local.canonical.startswith(ORIGIN+'/'):path=urllib.parse.urlsplit(local.canonical).path
            inventory[path]=local
            if not local.noindex:
                canonical=local.canonical or ORIGIN+path
                if not canonical.startswith(ORIGIN+'/'):fail('Unexpected canonical: '+canonical)
                indexed.add(canonical)
        urls=urls_from(load('/sitemap.xml'));report['sitemap_urls']=sorted(urls)
        paths=sorted(set(inventory)|{urllib.parse.urlsplit(u).path for u in urls})
        def read(path):
            data=load(path);doc=Document(data.decode('utf-8'));return path,doc
        for path,doc in concurrent.futures.ThreadPoolExecutor(max_workers=6).map(read,paths):documents[path]=doc
        return {'sitemap_urls_200':len(urls),'html_documents_200':len(documents),'source':report['mode']}
    section(1,'HTTP 状态 / public pages',status_check)
    def schema_check():
        count=0;types={}
        for path,doc in documents.items():
            if ORIGIN+path in indexed and not doc.schema:fail('Missing JSON-LD: '+path)
            for raw in doc.schema:
                data=json.loads(raw);count+=1
                for node in nodes(data):
                    kind=node.get('@type',[]);kind=[kind] if isinstance(kind,str) else kind
                    for t in kind:types[t]=types.get(t,0)+1
        home=[n for b in documents['/'].schema for n in nodes(json.loads(b))]
        if not any(n.get('@type')=='Organization' for n in home):fail('Homepage missing Organization')
        return {'json_ld_blocks_parsed':count,'types_top_level_graph_nodes':types,'scope':'all fetched root public HTML; schema has no nav/footer word-count relevance'}
    section(2,'JSON-LD schema',schema_check)
    def links_check():
        targets={};occurrences=0
        for path,doc in documents.items():
            for ref in doc.refs:
                parsed=urllib.parse.urlsplit(urllib.parse.urljoin(ORIGIN+path,html.unescape(ref)))
                if parsed.scheme not in {'http','https'} or parsed.hostname not in allowed_hosts:continue
                if parsed.path.startswith('/api/'):fail('Unexpected API request in public href/src (not probed): '+ref)
                key=parsed.path or '/';targets.setdefault(key,set()).add(urllib.parse.unquote(parsed.fragment));occurrences+=1
        def check(item):
            path,fragments=item
            if path in documents:doc=documents[path]
            else:
                is_html=not Path(path).suffix or path.endswith('.html')
                if is_html:doc=Document(load(path).decode('utf-8'))
                else:fetch(path,body=False);doc=None
            for fragment in fragments:
                if fragment and doc and fragment not in doc.ids:fail('Broken fragment: '+path+'#'+fragment)
            return path
        list(concurrent.futures.ThreadPoolExecutor(max_workers=6).map(check,sorted(targets.items())))
        return {'invalid':0,'unique_internal_paths':len(targets),'internal_reference_occurrences':occurrences,'scope':report['scope']['links']}
    section(3,'内链与资源 / internal targets',links_check)
    def facts_check():
        combined='\n'.join(d.text() for d in documents.values())
        raw='\n'.join(load(path).decode('utf-8') for path in documents)
        required={text:combined.casefold().count(text.casefold()) for text in args.require_text}
        forbidden={text:raw.casefold().count(text.casefold()) for text in args.forbid_text}
        if any(not n for n in required.values()) or any(forbidden.values()):fail('Fact guard failed: '+json.dumps({'required_body_counts':required,'forbidden_full_html_counts':forbidden}))
        return {'required_body_counts':required,'forbidden_full_html_counts':forbidden,'required_scope':'body excluding nav/header/footer/aside/scripts/hidden; HTML only, no JS execution','forbidden_scope':'complete HTML including nav/footer/hidden/JSON-LD'}
    section(4,'产品事实 / retention and price',facts_check)
    def overlap_check():
        owned_raw=load('/');owned=Document(owned_raw.decode('utf-8'))
        if args.reference_file:reference_raw=args.reference_file.read_bytes();reference_source=str(args.reference_file.resolve())
        else:reference_raw=fetch(REFERENCE)[1];reference_source=REFERENCE
        reference=Document(reference_raw.decode('utf-8'))
        if not owned.has_main or not reference.has_main:fail('Cannot measure overlap: missing main element')
        def tokens(doc):return re.findall(TOKENIZER,doc.text(main=True).replace('’',"'").replace('‘',"'").casefold(),re.UNICODE)
        own=tokens(owned);ref=tokens(reference);windows=[tuple(own[i:i+8]) for i in range(len(own)-7)];other={tuple(ref[i:i+8]) for i in range(len(ref)-7)}
        if not windows or not other:fail('Not enough main text for 8-gram comparison')
        numerator=sum(w in other for w in windows);denominator=len(windows);percent=100*numerator/denominator
        metrics={'n':8,'strict_threshold_percent':args.max_overlap,'coverage_percent':round(percent,6),'matched_owned_positions':numerator,'total_owned_positions':denominator,'owned_tokens':len(own),'reference_tokens':len(ref),'owned_source':report['mode']+' homepage','reference_source':reference_source,'owned_html_sha256':sha(owned_raw),'reference_html_sha256':sha(reference_raw),'tokenizer':TOKENIZER,'scope':report['scope']['overlap']}
        (out/'owned-home.html').write_bytes(owned_raw);(out/'reference-home.html').write_bytes(reference_raw)
        (out/'owned-main.txt').write_text(owned.text(main=True)+'\n');(out/'reference-main.txt').write_text(reference.text(main=True)+'\n')
        (out/'overlap-tokens.json').write_text(json.dumps({'owned':own,'reference':ref,'metrics':metrics},ensure_ascii=False,indent=2)+'\n');report['overlap']=metrics;save_report()
        if percent>=args.max_overlap:fail('8-gram must be below configured threshold: '+json.dumps(metrics,ensure_ascii=False))
        return metrics
    section(5,'首页 8-gram 重合度 / main-only',overlap_check)
    def sitemap_check():
        one=urls_from(load('/sitemap.xml'));two=urls_from(load('/sitemap-pages.xml'))
        if one!=two:fail('Sitemap sets differ: '+str(sorted(one^two)))
        if one!=indexed:fail('Sitemap vs indexable dist inventory differs: '+str(sorted(one^indexed)))
        rss_count=None
        if args.feed_path:
            feed=ET.fromstring(load(args.feed_path));items=feed.findall('./channel/item');rss_count=len(items)
            if rss_count<args.feed_min_items:fail('RSS fewer than configured minimum entries')
            for item in items:
                if any(not item.findtext(k) for k in ['title','link','description','pubDate']):fail('Incomplete RSS entry')
                if item.findtext('link') not in one:fail('RSS URL not in sitemap')
            if not all(documents[urllib.parse.urlsplit(u).path].feed for u in one):fail('Missing RSS discovery on a sitemap page')
        return {'sitemaps_equal':True,'urls_each':len(one),'indexable_inventory_pages':len(indexed),'noindex_utility_pages_excluded_from_sitemap':len(inventory)-len(indexed),'rss_entries':rss_count,'inventory_scope':report['scope']['expected_inventory']}
    section(6,'sitemap 一致性与覆盖 / RSS',sitemap_check)
    report['ok']=True;report['finished_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat();save_report()
    print('ALL GREEN — report: '+str(out/'report.json'),flush=True)

if __name__=='__main__':main()
