"""Search results and the news feed."""
import re

from selectolax.parser import HTMLParser

from vlrgg.parse.dom import absolute, attr, children, classes, find, find_text, image, next_element, text
from vlrgg.parse.values import none_if_blank, to_date
from vlrgg.schemas import NewsItem, SearchHit, SearchResults


def search_results(query: str, html: str) -> SearchResults:
    """Hits grouped under the page's "teams", "events" and "players" labels."""
    tree = HTMLParser(html)
    groups: dict[str, list[SearchHit]] = {"players": [], "teams": [], "events": []}
    for label in tree.css(".wf-label.mod-large"):
        kind = text(label).lower()
        card = next_element(label)
        if kind not in groups or card is None:
            continue
        for item in card.css("a.search-item"):
            found = re.search(r"/search/r/\w+/(\d+)", attr(item, "href"))
            groups[kind].append(SearchHit(
                id=int(found.group(1)) if found else None,
                name=find_text(item, ".search-item-title"),
                image=image(find(item, ".search-item-thumb")),
                description=none_if_blank(text(find(item, ".search-item-desc")).rstrip(" ⋅")),
            ))
    return SearchResults(query=query, **groups)


_NEWS_DATE = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}")
_NEWS_AUTHOR = re.compile(r"\bby\s+(\S+)")


def news(html: str) -> list[NewsItem]:
    items = []
    for item in HTMLParser(html).css("a.wf-module-item"):
        href = attr(item, "href")
        if not re.match(r"^/\d+/", href):
            continue
        body = find(item, "div")
        lines = [child for child in children(body) if "ge-text-light" not in classes(child)]
        meta = find_text(body, ".ge-text-light")
        day = _NEWS_DATE.search(meta)
        author = _NEWS_AUTHOR.search(meta)
        items.append(NewsItem(
            title=text(lines[0]) if lines else "",
            description=none_if_blank(text(lines[1])) if len(lines) > 1 else None,
            date=to_date(day.group()) if day else None,
            author=author.group(1) if author else None,
            url=absolute(href) or "",
        ))
    return items
