#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import argparse
import typing
from urllib.parse import urlparse
import os
import logging
import sys
from dataclasses import dataclass
import abc

import requests
import lxml.html # type: ignore
import aiohttp

logging.basicConfig(
    format='%(levelname)s:%(asctime)s:%(message)s',
    level = os.environ.get('LINKCHECK_LOGLEVEL', 'WARNING'),
    )

def positive_int(raw):
    val = int(raw)
    if val <= 0:
        raise ValueError(f'Non-positive value {val}')
    return val

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
    parser.add_argument('--limit', default=None, type=positive_int,
                        help='Stop crawling after this many URLs')
    parser.add_argument('--engine', default=DEFAULT_ENGINE, choices=ENGINES.keys(),
                        help='Use specific crawling engine')
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
    def from_url(cls, url: str) -> Domain:
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

@dataclass        
class Page:
    url: str
    domain: Domain
    status: int
    text: str
    
    def _post__init__(self):
        assert self.domain.url_in_domain(self.url), (self.url, self.domain.netloc)

    def url_is_valid(self) -> bool:
        return self.status >= 200 and self.status < 300
    
    def urls(self, domain: Domain) -> typing.Generator[str, None, None]:
        assert self.url_is_valid()
        yield from self.extract_urls(self.extract_hrefs(self.text))

    def normalize_url(self, href: str) -> typing.Optional[str]:
        '''
        Return a full URL from the href, based on the current page URL.

        Returns None no such valid URL exists, or otherwise we'd want to skip. Cases include:
         - mailto: links
         - urls that already have a #fragment
        '''
        def is_skippable(url):
            return url.lower().startswith('mailto:')
        def drop_fragment(url):
            pos = url.find('#')
            if pos > 0:
                return url[:pos]
            return url
        if self.is_full_url(href):
            return drop_fragment(href)
        elif href.startswith('/'):
            return drop_fragment(f'{self.domain.default_scheme}://{self.domain.netloc}{href}')
        elif is_skippable(href):
            return None
        elif href.startswith('#'):
            # drop fragments
            return None
        else:
            if not self.url.endswith('/'):
                href = '/' + href
            return drop_fragment(self.url + href)

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
    good_urls: set
    
    def __init__(self, links: Links):
        self.links = links
        self.bad_urls = set()
        self.good_urls = set()
        
    def add_bad(self, url: str) -> None:
        self.bad_urls.add(url)
        
    def add_good(self, url: str) -> None:
        self.good_urls.add(url)
        
    def print(self, verbose: bool) -> None:
        if verbose:
            self._print_verbose()
        else:
            self._print_quiet()
            
    def _print_quiet(self):
        for url in sorted(self.bad_urls):
            print(url)
            
    def _print_verbose(self):
        print('GOOD LINKS:')
        for url in sorted(self.good_urls):
            print(url)
        print('\nBAD LINKS:')
        for url in sorted(self.bad_urls):
            print(url)

class LazyRenderSorted:
    def __init__(self, coll: typing.Iterator):
        self.coll = coll

    def __str__(self) -> str:
        return str(sorted(self.coll))

class EngineBase(metaclass=abc.ABCMeta):
    def __init__(self, root_url: str, limit: typing.Union[None, int]):
        self.limit = limit
        self.domain = Domain.from_url(root_url)
        self.links = Links()
        self.links.add(root_url)
        self.report = Report(self.links)

    @abc.abstractmethod
    def run(self) -> None:
        pass

    @abc.abstractmethod
    def mk_page(self, url: str, response) -> Page:
        pass
    
    def exit_code(self) -> int:
        return 0 if len(self.report.bad_urls) == 0 else 1

class SequentialEngine(EngineBase):
    def mk_page(self, url: str, response) -> Page:
        return Page(url, self.domain, response.status_code, response.text)
    
    def run(self) -> None:
        count = 0
        while not self.links.empty():
            url = self.links.pop()
            count += 1
            response = self.fetch_url(url, self.domain)
            page = self.mk_page(url, response)
            logging.debug('Checking url: %s', url)
            if page.url_is_valid():
                logging.debug('found new urls: %s', LazyRenderSorted(page.urls(self.domain)))
                self.links.add_many(page.urls(self.domain))
                self.report.add_good(url)
            else:
                logging.debug('Invalid url: %s', url)
                self.report.add_bad(url)
            if self.limit and count >= self.limit:
                break
    @staticmethod
    def fetch_url(url, domain) -> requests.Response:
        logging.info('Fetching url: %s', url)
        response = requests.get(url)
        logging.debug('Status code for url: %d %s', response.status_code, url)
        return response

class AsyncEngine(EngineBase):
    concurrency = 5
    
    async def mk_page(self, url: str, response) -> Page:
        return Page(url, self.domain, response.status, await response.text())
    
    def run(self) -> None:
        asyncio.run(self.run_async())
        
    async def run_async(self) -> None:
        count = 0
        while not self.links.empty():
            url = self.links.pop()
            count += 1
            response = await self.fetch_url(url, self.domain)
            page = await self.mk_page(url, response)
            logging.debug('Checking url: %s', url)
            if page.url_is_valid():
                logging.debug('found new urls: %s', LazyRenderSorted(page.urls(self.domain)))
                self.links.add_many(page.urls(self.domain))
                self.report.add_good(url)
            else:
                logging.debug('Invalid url: %s', url)
                self.report.add_bad(url)
            if self.limit and count >= self.limit:
                break

    @staticmethod
    async def fetch_url(url, domain):
        logging.info('Fetching url: %s', url)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            response = await session.get(url)
        logging.debug('Status code for url: %d %s', response.status, url)
        return response

ENGINES = {
    'sequential' : SequentialEngine,
    'async'      : AsyncEngine,
    }
DEFAULT_ENGINE = 'sequential'
assert DEFAULT_ENGINE in ENGINES

if __name__ == '__main__':
    args = get_args()
    Engine = ENGINES[args.engine]
    engine = Engine(args.url, args.limit)
    engine.run()
    engine.report.print(args.verbose)
    sys.exit(engine.exit_code())
