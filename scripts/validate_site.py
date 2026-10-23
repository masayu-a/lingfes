#!/usr/bin/env python3
"""Validate built static HTML/CSS, links, anchor targets, and lack of scripts."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote,urlsplit
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_site import PUBLIC,assert_no_scripts,read_json,validate

class LinkScanner(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=set();self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids: raise ValueError(f'duplicate id {attrs["id"]}')
            self.ids.add(attrs['id'])
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])


def main():
    validate(read_json('site-2027.json'),read_json('program-2027.json'))
    assert_no_scripts()
    pages={}
    for path in PUBLIC.rglob('*.html'):
        scan=LinkScanner();scan.feed(path.read_text(encoding='utf-8'));pages[path.resolve()]=scan
    for file,scan in pages.items():
        for href in scan.links:
            bits=urlsplit(href)
            if bits.scheme or bits.netloc or href.startswith('//'): continue
            rel=unquote(bits.path)
            if rel:
                target=(file.parent/rel).resolve()
                if target.is_dir():target=target/'index.html'
            else:target=file
            if not target.exists():raise ValueError(f'Broken relative href in {file.relative_to(PUBLIC)}: {href}')
            if bits.fragment and target in pages and unquote(bits.fragment) not in pages[target].ids:
                raise ValueError(f'Missing fragment in {file.relative_to(PUBLIC)}: {href}')
    print(f'OK: {len(pages)} HTML files, internal links and anchors; no JavaScript or public JSON.')

if __name__=='__main__':main()
