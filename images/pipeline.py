"""
Auto Image Pipeline — orchestrator.

Pipeline (simplified — Gemini is the sole image source):

  1. Cache          → return immediately on hit
  2. Gemini gen     → validate generated image
  3. No-image fallback → return None (always succeeds)

Core rule: "Image is an enhancement, never a hard dependency."

The pipeline NEVER:
- Raises an exception that would abort presentation generation
- Returns a broken/invalid image path
- Blocks indefinitely (timeouts enforced at provider level)

Wikipedia / Wikimedia search has been REMOVED.
Gemini image generation is now the primary and sole active source.

Usage:
    pipeline = ImagePipeline()
    path = await pipeline.resolve(intent, topic="Жасанды интеллект")
    # path is Path | None — None means "no image, render without"
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from images.intent import ImageIntent
from images.cache import ImageCache
from images.validator import validate_image
from images.gemini_generator import GeminiImageGenerator

logger = logging.getLogger(__name__)

# Temp directory for generated images before caching
_DOWNLOAD_TMP = "cache/images/tmp"


class ImagePipeline:
    """
    Orchestrates the image pipeline.

    Stateless between calls — safe to share as a singleton.
    All operations are non-blocking at the orchestration level;
    generation calls are done synchronously in executors to keep
    the async interface clean.
    """

    def __init__(
        self,
        cache: ImageCache | None = None,
        generator: GeminiImageGenerator | None = None,
        cache_dir: str = "cache/images",
        # provider param kept for backwards-compat with tests; ignored
        provider=None,
    ) -> None:
        self._cache     = cache     or ImageCache(cache_dir)
        self._generator = generator or GeminiImageGenerator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        intent: ImageIntent,
        topic: str = "",
    ) -> Optional[Path]:
        """
        Resolve an ImageIntent to a local image path.

        Returns:
            Path — valid, validated local image file
            None — image not needed OR pipeline failed at all stages

        Never raises.
        """
        if not intent.needed:
            logger.debug("ImagePipeline: intent.needed=False → no image")
            return None

        cache_key = intent.build_cache_key(topic)
        if not cache_key:
            logger.debug("ImagePipeline: empty cache key → no image")
            return None

        # --- Stage 1: Cache ---
        cached = await asyncio.get_event_loop().run_in_executor(
            None, self._cache.get, cache_key
        )
        if cached is not None:
            logger.info("ImagePipeline: cache hit for %r → %s", cache_key[:50], cached.name)
            return cached

        # --- Stage 2: Gemini generation ---
        gen_prompt = intent.build_generation_prompt()
        if gen_prompt:
            logger.info("ImagePipeline: generating image via Gemini for %r", cache_key[:50])
            path = await asyncio.get_event_loop().run_in_executor(
                None, self._generate_and_validate, gen_prompt, cache_key
            )
            if path is not None:
                return path

        # --- Stage 3: No-image fallback ---
        logger.info(
            "ImagePipeline: Gemini unavailable for %r → no-image fallback", cache_key[:50]
        )
        return None

    def resolve_sync(
        self,
        intent: ImageIntent,
        topic: str = "",
    ) -> Optional[Path]:
        """
        Synchronous version of resolve() for use in non-async contexts
        (e.g. unit tests, synchronous renderer calls).

        Never raises.
        """
        if not intent.needed:
            return None

        cache_key = intent.build_cache_key(topic)
        if not cache_key:
            return None

        # Stage 1: Cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Stage 2: Gemini
        gen_prompt = intent.build_generation_prompt()
        if gen_prompt:
            path = self._generate_and_validate(gen_prompt, cache_key)
            if path is not None:
                return path

        # Stage 3: Fallback
        return None

    # ------------------------------------------------------------------
    # Internal helpers — all return None on any failure
    # ------------------------------------------------------------------

    def _generate_and_validate(
        self, prompt: str, cache_key: str
    ) -> Optional[Path]:
        """Generate image via Gemini, validate, and cache."""
        try:
            tmp_dir = Path(_DOWNLOAD_TMP)
            tmp_dir.mkdir(parents=True, exist_ok=True)

            path = self._generator.generate(prompt, dest_dir=tmp_dir)
            if path is None:
                return None

            vr = validate_image(path)
            if vr.valid:
                logger.info("ImagePipeline: Gemini generated valid image")
                # Cache under the key so it is reused next time
                try:
                    self._cache_result(cache_key, path)
                    return self._cache.get(cache_key) or path
                except Exception:
                    return path

            logger.warning(
                "ImagePipeline: Gemini image invalid: %s", vr.reason
            )
            try:
                path.unlink()
            except OSError:
                pass

        except Exception as exc:
            logger.warning("ImagePipeline._generate_and_validate error: %s", exc)

        return None

    def _cache_result(self, cache_key: str, path: Path) -> None:
        """Cache the image at *path* under *cache_key*. Silently ignores errors."""
        try:
            suffix = path.suffix or ".jpg"
            self._cache.put(cache_key, path, suffix=suffix)
        except Exception as exc:
            logger.warning("ImagePipeline: cache write failed: %s", exc)
