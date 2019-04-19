#!/usr/bin/env python3

import argparse
import typing
from urllib.parse import urlparse
import os
import logging
import sys

import requests
import lxml.html # type: ignore

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

The program's exit code will be:
 - 0 if all detected links are valid
 - 1 if at least one detected link is invalid
 - 2+ on some other error.

In quiet mode (the default), linkcheck prints out the URLs of any
detected broken links - one per line. If no broken links are found,
there is no output.  In verbose mode (-v or --verbose options), both
healthy and broken links are printed out, under different headers.
        
        '''.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    parser.add_argument('url',
                        help='Base URL to begin search')
    parser.add_argument('-v', '--verbose', default=False, action='store_true',
                        help='More verbose output')
    return parser.parse_args()

class Domain:
    '''
    Represents a single website domain name

    '''
    netloc: str
    def __init__(self, default_scheme: str, netloc: str):
        assert not '://' in default_scheme, f'invalid netloc: {default_scheme}'
        self.default_scheme = default_scheme
        self.netloc = netloc
    @classmethod
    def from_url(cls, url: str) -> 'Domain':
        parts = urlparse(url)
        return cls(parts.scheme, parts.netloc)
    def url_in_domain(self, url: str) -> bool:
        return self.netloc == urlparse(url).netloc

class Links:
    all: set
    checked: set
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
    def add_many(self, links: typing.Iterator[str]) -> None:
        'Add many unchecked links'
        for link in links:
            self.add(link)
    def empty(self) -> bool:
        'True iff there are no unchecked links left'
        return len(self.unchecked) == 0
    
class Page:
    url: str
    domain: Domain
    _resp: requests.Response
    def __init__(self, url, domain):
        assert domain.url_in_domain(url), (url, domain.netloc)
        self.url = url
        self.domain = domain
        self._resp = None
    @property
    def response(self) -> requests.Response:
        if self._resp is None:
            logging.info('Fetching url: %s', url)
            self._resp = requests.get(url)
            logging.debug('Status code for url: %d %s', self._resp.status_code, url)
        return self._resp
    
    def url_is_valid(self) -> bool:
        return self.response.status_code >= 200 and self.response.status_code < 300
    
    def urls(self, domain: Domain) -> typing.Generator[str, None, None]:
        assert self.url_is_valid()
        yield from self.extract_urls(self.extract_hrefs(self.response.text))

    def normalize_url(self, href: str) -> typing.Optional[str]:
        '''
        Return a full URL from the href, based on the current page URL.

        Returns None no such valid URL exists, or otherwise we'd want to skip. Cases include:
         - mailto: links
         - urls that already have a #fragment
        '''
        def is_skippable(url):
            return url.lower().startswith('mailto:')
        if self.is_full_url(href):
            return href
        elif href.startswith('/'):
            return f'{self.domain.default_scheme}://{self.domain.netloc}{href}'
        elif is_skippable(href):
            return None
        elif href.startswith('#'):
            if '#' in self.url:
                return None # don't need to re-check urls with different fragments
            return self.url + href
        else:
            if not self.url.endswith('/'):
                href = '/' + href
            return self.url + href

    def extract_urls(self, hrefs: typing.Iterator[str]) -> typing.Generator[str, None, None]:
        for href in hrefs:
            if self.is_full_url(href):
                if self.domain.url_in_domain(href):
                    yield href
                continue
            url = self.normalize_url(href)
            if url is None:
                logging.debug('Skipping href: %s', href)
                continue
            yield url

    @staticmethod
    def is_full_url(url: str) -> bool:
        return url.startswith('http://') or url.startswith('https://')
    
    @staticmethod
    def extract_hrefs(text: str) -> typing.Generator[str, None, None]:
        tree = lxml.html.document_fromstring(text)
        for elem in tree.cssselect('a'):
            if 'href' in elem.attrib:
                yield elem.attrib['href']

class Report:
    bad_urls: set
    def __init__(self, links: Links):
        self.links = links
        self.bad_urls = set()
    def add_bad(self, url: str) -> None:
        self.bad_urls.add(url)
    def print(self, verbose: bool) -> None:
        if verbose:
            self._print_verbose()
        else:
            self._print_quiet()
    def exit_code(self) -> int:
        return 0 if len(self.bad_urls) == 0 else 1
    def _print_quiet(self):
        for url in sorted(self.bad_urls):
            print(url)
    def _print_verbose(self):
        print('GOOD LINKS:')
        for url in sorted(self.links.all):
            print(url)
        print('\nBAD LINKS:')
        for url in sorted(self.bad_urls):
            print(url)

class LazyRenderSorted:
    def __init__(self, coll: typing.Iterator):
        self.coll = coll

    def __str__(self) -> str:
        return str(sorted(self.coll))

if __name__ == '__main__':
    args = get_args()
    links = Links()
    links.add(args.url)
    domain = Domain.from_url(args.url)
    report = Report(links)
    while not links.empty():
        url = links.pop()
        page = Page(url, domain)
        logging.debug('Checking url: %s', url)
        if page.url_is_valid():
            logging.debug('found new urls: %s', LazyRenderSorted(page.urls(domain)))
            links.add_many(page.urls(domain))
        else:
            logging.debug('Invalid url: %s', url)
            report.add_bad(url)

    report.print(args.verbose)
    sys.exit(report.exit_code())
