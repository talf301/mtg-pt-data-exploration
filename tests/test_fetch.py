from pathlib import Path
import httpx
import pytest
from mtg_scrape.fetch import Fetcher


def test_cache_hit_skips_network(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/foo"
    # Pre-populate cache
    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0)
    cache_path = fetcher._cache_path_for(url)
    cache_path.write_text("<html>cached</html>", encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("network should not be called on cache hit")

    monkeypatch.setattr(httpx, "get", boom)

    assert fetcher.get(url) == "<html>cached</html>"


def test_miss_calls_network_and_writes_cache(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/bar"

    calls = []

    class FakeResp:
        status_code = 200
        text = "<html>fresh</html>"
        def raise_for_status(self): pass

    def fake_get(u, **kwargs):
        calls.append(u)
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0)
    result = fetcher.get(url)

    assert result == "<html>fresh</html>"
    assert calls == [url]
    assert fetcher._cache_path_for(url).read_text(encoding="utf-8") == "<html>fresh</html>"


def test_rate_limit_sleeps_between_calls(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FakeResp:
        status_code = 200
        text = "ok"
        def raise_for_status(self): pass

    monkeypatch.setattr(httpx, "get", lambda u, **k: FakeResp())

    sleeps = []
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: sleeps.append(s))
    clock = iter([0.0, 0.0, 0.2, 0.2])  # second call 0.2s after first
    monkeypatch.setattr("mtg_scrape.fetch.time.monotonic", lambda: next(clock))

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=1.0)
    fetcher.get("https://example.com/a")
    fetcher.get("https://example.com/b")

    # First call: no sleep (no prior request). Second call: sleeps ~0.8s.
    assert len(sleeps) == 1
    assert 0.7 < sleeps[0] <= 1.0


def test_retry_then_success(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FlakyResp:
        def __init__(self, status):
            self.status_code = status
            self.text = "ok"
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=self)

    seq = iter([FlakyResp(503), FlakyResp(200)])
    monkeypatch.setattr(httpx, "get", lambda u, **k: next(seq))
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: None)

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0, max_retries=3)
    assert fetcher.get("https://example.com/flaky") == "ok"


def test_4xx_not_retried(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FakeResp:
        status_code = 404
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("not found", request=None, response=self)

    calls = []
    def fake_get(u, **k):
        calls.append(u)
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: None)

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0, max_retries=3)
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get("https://example.com/missing")
    assert len(calls) == 1, f"4xx should not retry, but got {len(calls)} calls"


def test_5xx_retried_then_fails(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FakeResp:
        status_code = 503
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("server error", request=None, response=self)

    calls = []
    monkeypatch.setattr(httpx, "get", lambda u, **k: (calls.append(u), FakeResp())[1])

    sleeps = []
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: sleeps.append(s))

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0, max_retries=3)
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get("https://example.com/dead")
    assert len(calls) == 3, "5xx should retry up to max_retries"
    # 2 sleeps between 3 attempts; no sleep after the final attempt
    assert sleeps == [1, 2], f"expected backoffs [1, 2], got {sleeps}"
