import importlib.util
from pathlib import Path

MONITOR = Path(__file__).resolve().parent.parent / "agents" / "monitor" / "monitor.py"


def _load_monitor():
    spec = importlib.util.spec_from_file_location("monitor_mod", MONITOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_topic_feed_list_prepends_topic_feed():
    monitor = _load_monitor()
    baseline = [
        {"url": "https://a.example/rss", "category": "tech", "enabled": True},
        {"url": "https://b.example/rss", "category": "hardware", "enabled": False},
    ]
    feeds, note = monitor.build_feed_list("Hardware & GPUs", baseline)

    assert feeds[0]["category"] == "topic"
    assert "Hardware%20%26%20GPUs" in feeds[0]["url"]
    assert feeds[0]["url"].startswith("https://news.google.com/rss/search?q=")


def test_topic_feed_list_keeps_enabled_backfill_only():
    monitor = _load_monitor()
    baseline = [
        {"url": "https://a.example/rss", "category": "tech", "enabled": True},
        {"url": "https://b.example/rss", "category": "crypto", "enabled": False},
        {"url": "https://c.example/rss", "category": "hardware"},  # enabled defaults to on
    ]
    feeds, note = monitor.build_feed_list("GPUs", baseline)

    urls = [f["url"] for f in feeds]
    assert len(feeds) == 3
    assert "https://a.example/rss" in urls
    assert "https://c.example/rss" in urls
    assert "https://b.example/rss" not in urls
    assert "2 backfill feeds" in note