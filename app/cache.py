"""Bounded application cache with an optional shared Upstash tier."""
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx


class Cache:
    def __init__(self, namespace: str, *, shared: bool = True):
        self.namespace = namespace
        self.shared = shared
        self.entries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.lock = threading.Lock()
        self.client = httpx.Client(timeout=1.0, follow_redirects=False)
        self.refresh_locks = [threading.Lock() for _ in range(64)]

    def key_lock(self, key: str):
        return self.refresh_locks[hash(key) % len(self.refresh_locks)]

    def _command(self, *command: str):
        if not self.shared:
            return None
        endpoint = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        if not endpoint.startswith("https://") or not token:
            return None
        try:
            response = self.client.post(endpoint, headers={"Authorization": f"Bearer {token}"}, json=command)
            response.raise_for_status()
            return response.json().get("result")
        except (httpx.HTTPError, ValueError):
            return None

    def _remember(self, key: str, entry: dict[str, Any]):
        with self.lock:
            self.entries[key] = entry
            self.entries.move_to_end(key)
            if len(self.entries) > 500:
                self.entries.popitem(last=False)

    def get(self, key: str):
        now = time.time()
        with self.lock:
            entry = self.entries.get(key)
            if entry:
                self.entries.move_to_end(key)
        if not entry or entry["fresh_until"] <= now:
            raw = self._command("GET", f"world-tech:{self.namespace}:{key}")
            if raw:
                try:
                    shared = json.loads(raw)
                    if isinstance(shared, dict) and isinstance(shared.get("value"), dict) and all(
                        isinstance(shared.get(field), (int, float)) for field in ("fresh_until", "expires")
                    ):
                        entry = shared
                        self._remember(key, entry)
                except (ValueError, TypeError):
                    pass
        if entry and entry["expires"] > now:
            return entry["value"], entry["fresh_until"] <= now
        return None, False

    def put(self, key: str, value: dict, ttl: int, stale: int = 0):
        now = time.time()
        entry = {"value": value, "fresh_until": now + ttl, "expires": now + ttl + stale}
        self._remember(key, entry)
        self._command("SET", f"world-tech:{self.namespace}:{key}", json.dumps(entry), "EX", str(ttl + stale))

    def clear(self):
        with self.lock:
            self.entries.clear()
