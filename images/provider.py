"""
Image provider abstraction.

ImageProvider defines the interface for any image provider.
WikimediaProvider has been REMOVED — Gemini image generation is now
the sole active image source.

A NullProvider is kept as the default so the pipeline interface
remains intact without any external HTTP dependencies.

ImageProvider is replaceable — swap the concrete class without
changing the pipeline.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    """A successfully located image from a provider."""
    url: str
    local_path: Optional[Path] = None   # set after download
    width: int = 0
    height: int = 0
    source: str = ""                    # provider name
    license: str = ""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ImageProvider(ABC):
    """
    Abstract image provider.

    Subclasses implement:
     - search(query, max_results) → list[ImageResult]  (metadata only, no download)
     - download(result, dest_dir)  → Path | None        (download + return path)
    """

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[ImageResult]:
        """
        Search for images matching *query*.
        Returns a list of ImageResult objects (not yet downloaded).
        Returns [] on failure — never raises.
        """
        ...

    @abstractmethod
    def download(self, result: ImageResult, dest_dir: str | Path) -> Optional[Path]:
        """
        Download the image described by *result* into *dest_dir*.
        Returns the local Path on success, None on failure.
        Never raises.
        """
        ...

    def search_and_download(
        self,
        query: str,
        dest_dir: str | Path,
        max_candidates: int = 5,
    ) -> Optional[Path]:
        """
        Convenience: search then download the first valid result.
        Tries up to *max_candidates* results before giving up.
        """
        results = self.search(query, max_results=max_candidates)
        if not results:
            logger.info("Provider %s: no results for %r", self.__class__.__name__, query[:60])
            return None

        for r in results:
            path = self.download(r, dest_dir)
            if path is not None:
                return path
            logger.debug("Download failed for %s — trying next", r.url[:80])

        return None


# ---------------------------------------------------------------------------
# NullProvider — default when no external search is desired
# ---------------------------------------------------------------------------

class NullProvider(ImageProvider):
    """
    A no-op provider that always returns empty results.

    Used as the default provider now that Wikipedia/Wikimedia search has
    been removed.  Gemini image generation handles all image acquisition.
    """

    def search(self, query: str, max_results: int = 5) -> list[ImageResult]:
        logger.debug("NullProvider: search called for %r — returning []", query[:60])
        return []

    def download(self, result: ImageResult, dest_dir: str | Path) -> Optional[Path]:
        logger.debug("NullProvider: download called — returning None")
        return None


# ---------------------------------------------------------------------------
# Default provider factory
# ---------------------------------------------------------------------------

def get_default_provider() -> ImageProvider:
    """Return the default ImageProvider instance (NullProvider)."""
    return NullProvider()
