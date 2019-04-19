#!/usr/bin/env python3

import argparse
import typing
from urllib.parse import urlparse
import os
import logging
import sys

import requests
import lxml.html

logging.basicConfig(
    format='%(levelname)s:%(asctime)s:%(message)s',
    level = os.environ.get('LINKCHECK_LOGLEVEL', 'WARNING'),
    )

def get_args():
    parser = argparse.ArgumentParser(
        description='Check website for broken links',
        epilog='''

Linkcheck is a command-line tool for finding broken links in a website.

It's designed for CI pipelines, and other forms of devops/sysadmin automation.
        
        '''.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    parser.add_argument('url',
                        help='Base URL to begin search')
    return parser.parse_args()

class Links:
    def __init__(self):
        self.all = set()
        self.checked = set()
    @property
    def unchecked(self) -> set:
        return self.all - self.checked
    def pop(self) -> str:
        'Choose one unchecked link, marking it as checked'
        link = self.unchecked.pop()
        self.checked.add(link)
        return link
    def add(self, link: str) -> None:
        'Add an unchecked link'
        self.all.add(link)
    def add_many(self, links: typing.Sequence[str]) -> None:
        'Add many unchecked links'
        for link in links:
            self.add(link)
    def empty(self) -> bool:
        'True iff there are no unchecked links left'
        return len(self.unchecked) == 0
    
class Domain:
    '''
    Represents a single website domain name

    '''
    netloc: str
    def __init__(self, netloc: str):
        self.netloc = netloc
    @classmethod
    def from_url(cls, url):
        return cls(urlparse(url).netloc)
    def url_in_domain(self, url):
        return self.netloc == urlparse(url).netloc

class Page:
    def __init__(self, url):
        self.url = url
        self._resp = None
    @property
    def response(self):
        if self._resp is None:
            logging.debug('Fetching url: %s', url)
            self._resp = requests.get(url)
            logging.debug('Status code for url: %d %s', self._resp.status_code, url)
        return self._resp
    def url_is_valid(self):
        return self.response.status_code >= 200 and self.response.status_code < 300
    def urls(self, domain):
        assert self.url_is_valid()
        for url in self.extract_urls(self.response.text):
            if domain.url_in_domain(url):
                yield url
    @staticmethod
    def extract_urls(text):
        tree = lxml.html.document_fromstring(text)
        for elem in tree.cssselect('a'):
            if 'href' in elem.attrib:
                yield elem.attrib['href']

class Report:
    def __init__(self):
        self.bad_urls = set()
    def add_bad(self, url):
        self.bad_urls.add(url)
    def print(self):
        for url in sorted(self.bad_urls):
            print(url)
    def exit_code(self):
        return 0 if len(self.bad_urls) == 0 else 1

if __name__ == '__main__':
    args = get_args()
    links = Links()
    links.add(args.url)
    domain = Domain(args.url)
    report = Report()
    while not links.empty():
        url = links.pop()
        page = Page(url)
        logging.debug('Checking url: %s', url)
        if page.url_is_valid():
            logging.debug('found new urls: %s', list(page.urls(domain)))
            links.add_many(page.urls(domain))
        else:
            logging.debug('Invalid url: %s', url)
            report.add_bad(url)

    report.print()
    sys.exit(report.exit_code())
