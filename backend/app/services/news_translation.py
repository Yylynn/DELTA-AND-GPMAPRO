"""轻量级新闻标题翻译，结果持久化后复用。

翻译是展示层增强：任何网络或响应格式错误都只会返回 None，
不得阻断新闻雷达、传导分析或快照保存。
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx


def _contains_chinese(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


class HeadlineTranslator:
    def __init__(self, cache_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self.cache_path = cache_path
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            self._cache: dict[str, str] = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            self._cache = {}

    def _persist(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)

    def translate(self, title: str) -> str | None:
        value = title.strip()
        if not value:
            return None
        if _contains_chinese(value):
            return value
        with self._lock:
            cached = self._cache.get(value)
        if cached:
            return cached
        translated: str | None = None
        try:
            response = httpx.get(
                "https://api.mymemory.translated.net/get",
                params={"q": value[:500], "langpair": "en|zh-CN"},
                headers={"User-Agent": "DELTA-News-Headline-Translator/0.1"},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            if int(payload.get("responseStatus", 0)) == 200:
                translated = str(payload.get("responseData", {}).get("translatedText") or "").strip()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            translated = None
        if not translated or not _contains_chinese(translated):
            return None
        with self._lock:
            self._cache[value] = translated
            try:
                self._persist()
            except OSError:
                pass
        return translated

    def translate_many(self, titles: list[str]) -> dict[str, str]:
        unique = list(dict.fromkeys(title.strip() for title in titles if title and title.strip()))
        output: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(unique))), thread_name_prefix="headline-zh") as pool:
            futures = {pool.submit(self.translate, title): title for title in unique}
            for future in as_completed(futures):
                try:
                    translated = future.result()
                except Exception:
                    translated = None
                if translated:
                    output[futures[future]] = translated
        return output
