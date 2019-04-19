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
        assert domain.url_in_domain('https://powerfulpython.com/about')
        assert domain.url_in_domain('http://powerfulpython.com')
        assert domain.url_in_domain('https://powerfulpython.com/x/y/z')
        assert not domain.url_in_domain('http://powerfulruby.com')
        assert not domain.url_in_domain('https://example.com/about')
        
class TestPage:
    def test_extract_urls(self):
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
        assert expected == sorted(linkcheck.Page.extract_urls(text))
        
    
