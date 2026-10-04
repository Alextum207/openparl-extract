"""Thin client for the public OpenParlData REST API (no auth)."""
import ssl
import time
from collections.abc import Iterator

import httpx
import truststore

from openparl_extract.config import load_config

OFFSET_CAP = 100_000  # API refuses offsets beyond this


class OpenParlDataClient:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None,
                 delay: float = 0.2, timeout: float = 60):
        self.delay = delay
        self.http = httpx.Client(base_url=base_url or load_config().api_base, transport=transport,
                                 timeout=timeout, follow_redirects=True,
                                 verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),  # OS cert store (fixes Windows)
                                 headers={"User-Agent": "openparl-extract/0.1"})

    def _get(self, url: str, **params) -> httpx.Response:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in (0, 1):  # retry once on 5xx / timeout
            time.sleep(self.delay)
            try:
                r = self.http.get(url, params=params)
            except httpx.TimeoutException:
                if attempt:
                    raise
                continue
            if r.status_code >= 500 and not attempt:
                continue
            r.raise_for_status()
            return r
        raise AssertionError("unreachable")

    def list_affairs(self, body_key: str | None = None, limit: int = 50, offset: int = 0,
                     expand_docs: bool = False) -> dict:
        return self._get("/v1/affairs/", limit=limit, offset=offset, body_key=body_key,
                         expand="docs" if expand_docs else None).json()

    def iter_affairs(self, body_key: str | None = None, page_size: int = 50,
                     max_records: int | None = None, expand_docs: bool = False) -> Iterator[dict]:
        offset = n = 0
        while offset < OFFSET_CAP:
            page = self.list_affairs(body_key, page_size, offset, expand_docs)
            for a in page["data"]:
                if max_records is not None and n >= max_records:
                    return
                n += 1
                yield a
            if not page["meta"]["has_more"] or not page["data"]:
                return
            offset += page_size

    def get_affair(self, affair_id: int | str, expand: str | None = "docs,events,contributors") -> dict:
        # comma-separated expand verified live; relations come back as {"data": [...], "meta": {...}}
        # ponytail: relations are capped at 100 rows (meta.has_more); follow meta.next_page if an affair exceeds it
        return self._get(f"/v1/affairs/{affair_id}", expand=expand).json()

    def list_bodies(self) -> list[dict]:
        out, offset = [], 0
        while True:
            page = self._get("/v1/bodies/", limit=3000, offset=offset).json()
            out += page["data"]
            if not page["meta"]["has_more"] or not page["data"]:
                return out
            offset += len(page["data"])

    def download_pdf(self, url: str) -> bytes:
        data = self._get(url).content
        if not data.startswith(b"%PDF"):
            raise ValueError(f"not a PDF: {url}")
        return data
