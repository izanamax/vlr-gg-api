"""Small helpers over selectolax nodes shared by every page parser."""
import re

from selectolax.parser import HTMLParser, Node

from vlrgg.config import VLR_URL
from vlrgg.errors import UpstreamFailed

_SPACES = re.compile(r"\s+")


def parse(html: str) -> HTMLParser:
    return HTMLParser(html)


def squash(value: str | None) -> str:
    return _SPACES.sub(" ", value or "").strip()


def text(node: Node | None, sep: str = " ") -> str:
    """All text under ``node``, whitespace collapsed."""
    if node is None:
        return ""
    return squash(node.text(deep=True, separator=sep))


def own_text(node: Node | None) -> str:
    """Text directly inside ``node``, without its child elements."""
    if node is None:
        return ""
    return squash(" ".join(part.text_content or "" for part in node.iter(include_text=True) if part.tag == "-text"))


def find(node: Node | HTMLParser | None, selector: str) -> Node | None:
    """First descendant matching ``selector``; selectolax would also return ``node`` itself."""
    if node is None:
        return None
    if isinstance(node, HTMLParser):
        return node.css_first(selector)
    return next((found for found in node.css(selector) if found.mem_id != node.mem_id), None)


def find_text(node: Node | HTMLParser | None, selector: str) -> str:
    return text(find(node, selector))


def attr(node: Node | None, name: str) -> str:
    if node is None:
        return ""
    return (node.attributes.get(name) or "").strip()


def children(node: Node | None) -> list[Node]:
    """Element children, text and comments left out."""
    if node is None:
        return []
    return [child for child in node.iter() if child.tag not in ("-text", "_comment", "-comment")]


def next_element(node: Node) -> Node | None:
    sibling = node.next
    while sibling is not None and sibling.tag in ("-text", "_comment", "-comment"):
        sibling = sibling.next
    return sibling


def classes(node: Node | None) -> set[str]:
    return set(attr(node, "class").split())


def href_id(href: str, kind: str) -> int | None:
    """``/team/2059/team-vitality`` with kind "team" -> 2059."""
    found = re.search(rf"/{kind}/(\d+)", href or "")
    return int(found.group(1)) if found else None


def match_id_of(href: str) -> int | None:
    """``/754737/loud-vs-...`` (or without the leading slash) -> 754737."""
    found = re.match(r"^/?(\d+)(?:[/?]|$)", href or "")
    return int(found.group(1)) if found else None


def absolute(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return VLR_URL + url
    if not url.startswith("http"):
        return f"{VLR_URL}/{url}"
    return url


def image(node: Node | None) -> str | None:
    """Absolute src of the first image under ``node``; vlr.gg's no-logo placeholder reads as none."""
    src = attr(find(node, "img"), "src") if node is not None and node.tag != "img" else attr(node, "src")
    if not src or src.endswith(("/tmp/vlr.png", "/ph/sil.png")):
        return None
    return absolute(src)


def flag_code(node: Node | None) -> str | None:
    """Country code of the first ``.flag`` under ``node`` (``mod-us`` -> "us")."""
    flag = node if node is not None and "flag" in classes(node) else find(node, ".flag")
    for name in classes(flag):
        if name.startswith("mod-") and name not in ("mod-16", "mod-dark"):
            return name.removeprefix("mod-")
    return None


def agent_of(img: Node | None) -> str | None:
    """Agent key from an agent icon: ``/img/vlr/game/agents/kayo.png`` -> "kayo"."""
    found = re.search(r"/agents/([a-z0-9]+)\.", attr(img, "src"))
    return found.group(1) if found else None


def require(node: Node | HTMLParser | None, selector: str, page: str) -> Node:
    """The first match, or a 502: the page is not what this parser knows."""
    found = find(node, selector)
    if found is None:
        raise UpstreamFailed(f"vlr.gg {page} has no {selector}; its layout may have changed")
    return found
