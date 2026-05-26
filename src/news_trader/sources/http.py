from __future__ import annotations

from urllib.request import Request, urlopen


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> str:
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

