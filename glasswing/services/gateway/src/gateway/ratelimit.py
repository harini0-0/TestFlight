"""Per-client rate limit. Redis when REDIS_URL is set, otherwise an in-process window."""

from __future__ import annotations

import os
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse


class MemoryRateLimiter:
    def __init__(self, limit: int = 600, window: int = 60) -> None:
        self.limit = limit
        self.window = window
        self.buckets: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = [stamp for stamp in self.buckets[key] if now - stamp < self.window]
        if len(hits) >= self.limit:
            self.buckets[key] = hits
            return False
        hits.append(now)
        self.buckets[key] = hits
        return True


class RedisRateLimiter:
    def __init__(self, url: str, limit: int = 600, window: int = 60) -> None:
        parsed = urlparse(url)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 6379
        self.limit = limit
        self.window = window

    def allow(self, key: str) -> bool:
        token = f"rl:{key}"
        count = int(_redis(self.host, self.port, ["INCR", token]))
        if count == 1:
            _redis(self.host, self.port, ["EXPIRE", token, str(self.window)])
        return count <= self.limit


def build_limiter() -> MemoryRateLimiter | RedisRateLimiter:
    limit = int(os.environ.get("GLASSWING_RATE_LIMIT", "600"))
    url = os.environ.get("REDIS_URL", "").strip()
    if url:
        return RedisRateLimiter(url, limit=limit)
    return MemoryRateLimiter(limit=limit)


def _encode(parts: list[str]) -> bytes:
    body = f"*{len(parts)}\r\n".encode()
    for part in parts:
        raw = part.encode()
        body += f"${len(raw)}\r\n".encode() + raw + b"\r\n"
    return body


def _redis(host: str, port: int, parts: list[str]) -> str:
    with socket.create_connection((host, port), timeout=0.5) as sock:
        sock.sendall(_encode(parts))
        data = b""
        while b"\r\n" not in data:
            chunk = sock.recv(256)
            if not chunk:
                break
            data += chunk
    line = data.decode().strip()
    if line.startswith(":"):
        return line[1:]
    if line.startswith("+"):
        return line[1:]
    if line.startswith("-"):
        raise RuntimeError(line)
    return line
