"""The persistent page store."""
from vlrgg.net.store import PageStore


def test_store_round_trips_html(tmp_path):
    store = PageStore(tmp_path / "nested" / "pages.sqlite3")
    page = "<html>" + "Привет, vlr.gg " * 1000 + "</html>"

    store.put("https://www.vlr.gg/1", page)

    assert store.get("https://www.vlr.gg/1") == page
    assert store.get("https://www.vlr.gg/2") is None
    assert len(store) == 1
    # stored compressed, not as-is
    assert (tmp_path / "nested" / "pages.sqlite3").stat().st_size < len(page.encode("utf-8"))


def test_disabled_store_keeps_nothing():
    store = PageStore(None)

    store.put("https://www.vlr.gg/1", "<html></html>")

    assert not store.enabled
    assert store.get("https://www.vlr.gg/1") is None
    assert len(store) == 0
