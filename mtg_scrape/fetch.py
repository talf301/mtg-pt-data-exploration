"""HTTP GET with on-disk cache and polite rate limiting."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

_DEFAULT_HEADERS = {
    "User-Agent": "mtg-pt-data-exploration/0.1 (personal data exploration; contact: github.com/talf301)",
}


@dataclass
class Fetcher:
    cache_dir: Path
    min_interval_s: float = 1.0
    max_retries: int = 3
    timeout_s: float = 30.0
    _last_request_at: float | None = None  # monotonic timestamp; None = no prior request

    def _cache_path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def get(self, url: str) -> str:
        cache_path = self._cache_path_for(url)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        # Rate-limit: sleep until min_interval_s has elapsed since last request.
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = httpx.get(url, headers=_DEFAULT_HEADERS, timeout=self.timeout_s, follow_redirects=True)
                resp.raise_for_status()
                self._last_request_at = time.monotonic()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(resp.text, encoding="utf-8")
                return resp.text
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else 0
                if status != 429 and status < 500:
                    raise  # not transient, don't retry
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        assert last_exc is not None
        raise last_exc
