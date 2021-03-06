import linkcheck
class TestLinks:
    def test_main(self):
        links = linkcheck.Links()
        assert len(links.unchecked) == 0
        assert links.empty()

        links.add('http://example.com/a')
        assert len(links.unchecked) == 1
        assert not links.empty()
        links.add_many([
            'http://example.com/b',
            'http://example.com/c',
        ])
        assert len(links.unchecked) == 3
        assert not links.empty()
        
        link = links.pop()
        assert not links.empty()
        assert link in links.all
        assert link not in links.unchecked

        links.pop()
        links.pop()
        assert links.empty()

class TestDomain:
    def test_main(self):
        domain = linkcheck.Domain.from_url('https://powerfulpython.com/about')
        assert domain.netloc == 'powerfulpython.com'
        assert domain.default_scheme == 'https'
        assert domain.url_in_domain('https://powerfulpython.com/about')
        assert domain.url_in_domain('http://powerfulpython.com')
        assert domain.url_in_domain('https://powerfulpython.com/x/y/z')
        assert not domain.url_in_domain('http://powerfulruby.com')
        assert not domain.url_in_domain('https://example.com/about')
        
class TestPage:
    def test_extract_hrefs(self):
        text = '''
        <html><body>
        <p>Here is <a href="https://example.com/a">a link</a></p>
        <ul>
        <li><a href="https://example.com/b">Link 2</a></li>
        <li><a href="/c">Link 3</a></li>
        <li><a href="d">Link 4</a></li>
        </ul></body></html>
        '''.strip()
        expected = [
            '/c',
            'd',
            'https://example.com/a',
            'https://example.com/b',
            ]
        assert expected == sorted(linkcheck.Page.extract_hrefs(text))

    def test_extract_urls(self):
        domain = linkcheck.Domain.from_url('https://example.com')
        page = linkcheck.Page('https://example.com/start', domain, None, None)
        hrefs = [
            '/c',
            '/d',
            'https://notyourdomain.com/a',
            'https://example.com/b',
            'x',
            '#foo',
        ]
        expected = sorted([
            'https://example.com/b',
            'https://example.com/c',
            'https://example.com/d',
            'https://example.com/start/x',
        ])
        actual = sorted(page.extract_urls(hrefs))
        assert expected == actual

    def test_normalize_url(self):
        domain = linkcheck.Domain.from_url('https://example.com')
        page = linkcheck.Page('https://example.com/start', domain, None, None)

        # skip mailto links
        assert None == page.normalize_url('mailto:a@example.com')
        
        # drop fragments
        assert None == page.normalize_url('#another')
        assert 'https://www2.example.com/something' == page.normalize_url('https://www2.example.com/something#else')
