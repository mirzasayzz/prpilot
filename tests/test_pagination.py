"""Link header pagination tests.

GitHub list endpoints paginate with a Link response header such
as:

    <https://api.github.com/...?page=2>; rel="next",
    <https://api.github.com/...?page=5>; rel="last"

Important scope note: github/client.py as read does NOT use this
yet. Its get_pull_request_files fetches one page only, with
per_page=100, so a pull request with more than 100 files is
truncated today. The helpers below define the parsing and
aggregation logic that should be wired into that client; these
tests cover the helper logic, they do not claim the client
already paginates. Wiring the helper into github/client.py is a
follow-up change, not part of this test file.

No network calls: fetch_page is a fake supplied by each test.
"""

import re

_LINK_PART = re.compile(r'\s*<([^>]+)>\s*;\s*rel="?([^";,\s]+)"?')


def parse_link_header(header):
    """Parse a Link header into a dict of rel name to URL."""
    links = {}
    if not header:
        return links
    for part in header.split(","):
        match = _LINK_PART.search(part)
        if match:
            url, rel = match.group(1), match.group(2)
            links[rel] = url
    return links


def fetch_all_pages(fetch_page, first_url, max_pages=100):
    """Aggregate items across pages, following rel="next".

    fetch_page(url) returns (items, link_header). Stops when
    there is no next link, when a URL repeats, or at max_pages,
    so a bad header cannot loop forever.
    """
    items = []
    seen = set()
    url = first_url
    pages = 0
    while url and url not in seen and pages < max_pages:
        seen.add(url)
        pages += 1
        page_items, link_header = fetch_page(url)
        items.extend(page_items)
        url = parse_link_header(link_header).get("next")
    return items


def test_parse_single_next_link():
    header = '<https://api.github.com/repos/o/r/pulls/1/files?page=2>; rel="next"'
    assert parse_link_header(header) == {
        "next": "https://api.github.com/repos/o/r/pulls/1/files?page=2"
    }


def test_parse_multiple_links():
    header = (
        '<https://example.test/?page=2>; rel="next", '
        '<https://example.test/?page=5>; rel="last", '
        '<https://example.test/?page=1>; rel="first"'
    )
    parsed = parse_link_header(header)
    assert parsed["next"] == "https://example.test/?page=2"
    assert parsed["last"] == "https://example.test/?page=5"
    assert parsed["first"] == "https://example.test/?page=1"


def test_parse_empty_and_malformed():
    assert parse_link_header("") == {}
    assert parse_link_header(None) == {}
    assert parse_link_header("not a link header") == {}
    assert parse_link_header('<https://example.test/?page=2>') == {}


def test_single_page_aggregation():
    def fetch_page(url):
        assert url == "https://example.test/?page=1"
        return (["a", "b"], "")

    assert fetch_all_pages(fetch_page, "https://example.test/?page=1") == ["a", "b"]


def test_all_pages_aggregated_in_order():
    pages = {
        "https://example.test/?page=1": (
            ["a"],
            '<https://example.test/?page=2>; rel="next"',
        ),
        "https://example.test/?page=2": (
            ["b", "c"],
            '<https://example.test/?page=3>; rel="next"',
        ),
        "https://example.test/?page=3": (["d"], ""),
    }

    def fetch_page(url):
        return pages[url]

    assert fetch_all_pages(fetch_page, "https://example.test/?page=1") == [
        "a",
        "b",
        "c",
        "d",
    ]


def test_looping_next_link_stops():
    calls = []

    def fetch_page(url):
        calls.append(url)
        return (["x"], '<https://example.test/?page=1>; rel="next"')

    assert fetch_all_pages(fetch_page, "https://example.test/?page=1") == ["x"]
    assert calls == ["https://example.test/?page=1"]


def test_max_pages_caps_runaway_pagination():
    def fetch_page(url):
        number = int(url.rsplit("=", 1)[1])
        return (
            [number],
            '<https://example.test/?page=%d>; rel="next"' % (number + 1),
        )

    result = fetch_all_pages(
        fetch_page, "https://example.test/?page=1", max_pages=3
    )
    assert result == [1, 2, 3]
