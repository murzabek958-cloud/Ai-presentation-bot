"""
Image cache manager.

Uses the existing cache/output directory pattern from config.settings.
Cache key is deterministic: SHA-256 hash of the normalized query string.

Supports:
- cache hit  → returns validated path
- cache miss → returns None
- invalid cached file → removes and returns None (recovery)
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional

from images.validator import validate_image

logger = logging.getLogger(__name__)

# Default cache directory (matches existing cache/ pattern)
_DEFAULT_CACHE_DIR = "cache/images"


class ImageCache:
    """
    Persistent on-disk image cache keyed by search query / generation prompt.

    Thread-safe for reads; writes may race in the edge case of concurrent
    generation for the same key (last write wins — acceptable).
    """

    def __init__(self, cache_dir: str = _DEFAULT_CACHE_DIR) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ImageCache initialised at %s", self._dir)

    # ------------------------------------------------------------------
    # Key
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(query: str) -> str:
        """
        Return a deterministic, filesystem-safe cache key for *query*.
        Uses SHA-256 of the lowercased, stripped query.
        """
        normalised = query.strip().lower()
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, query: str) -> Optional[Path]:
        """
        Return the cached image path for *query*, or None on miss/invalid.

        If a cached file exists but fails validation, it is deleted
        and None is returned (cache recovery).
        """
        key  = self.make_key(query)
        hits = list(self._dir.glob(f"{key}.*"))
        if not hits:
            logger.debug("Cache miss: %r", query[:60])
            return None

        cached = hits[0]
        result = validate_image(cached)
        if result.valid:
            logger.debug("Cache hit: %r → %s", query[:60], cached.name)
            return cached

        # Invalid cached file — remove and report miss
        logger.warning(
            "Cache file invalid (%s) — removing: %s", result.reason, cached.name
        )
        try:
            cached.unlink()
        except OSError as exc:
            logger.warning("Could not remove invalid cache file: %s", exc)
        return None

    def put(self, query: str, source_path: str | Path, suffix: str = ".jpg") -> Path:
        """
        Copy *source_path* into the cache under the key for *query*.

        Returns the final cache path.
        Raises OSError if the copy fails.
        """
        key  = self.make_key(query)
        dest = self._dir / f"{key}{suffix}"
        shutil.copy2(str(source_path), str(dest))
        logger.debug("Cached image: %r → %s", query[:60], dest.name)
        return dest

    def has(self, query: str) -> bool:
        """Return True if a valid cached image exists for *query*."""
        return self.get(query) is not None

    def clear(self) -> int:
        """Remove all cached images. Returns count of deleted files."""
        removed = 0
        for f in self._dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        logger.info("Cache cleared: %d files removed", removed)
        return removed
