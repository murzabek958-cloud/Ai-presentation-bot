"""
Gemini image generation fallback.

Uses the existing google-genai client and the configured Gemini API key.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class GeminiImageGenerator:
    """Generate presentation images using Gemini image models."""

    _IMAGE_MODEL = "gemini-3.1-flash-image"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.gemini_api_key

    def generate(
        self,
        prompt: str,
        dest_dir: str | Path = "cache/images",
        filename_hint: str = "gemini",
    ) -> Optional[Path]:

        if not prompt.strip():
            logger.debug("GeminiImageGenerator: empty prompt — skipping")
            return None

        if not self._api_key:
            logger.warning(
                "GeminiImageGenerator: no API key — cannot generate"
            )
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            logger.warning(
                "GeminiImageGenerator: google-genai unavailable: %s",
                exc,
            )
            return None

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        try:
            client = genai.Client(api_key=self._api_key)

            response = client.models.generate_content(
                model=self._IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

            if not response.candidates:
                logger.warning(
                    "GeminiImageGenerator: no candidates in response"
                )
                return None

            for candidate in response.candidates:
                content = candidate.content

                if content is None or not content.parts:
                    continue

                for part in content.parts:
                    inline_data = getattr(part, "inline_data", None)

                    if inline_data is None:
                        continue

                    raw_bytes = getattr(inline_data, "data", None)

                    if not raw_bytes:
                        continue

                    key = hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest()[:16]

                    safe_hint = "".join(
                        c if c.isalnum() or c in "-_" else "_"
                        for c in filename_hint
                    )[:40]

                    out_path = (
                        dest
                        / f"gemini_{safe_hint}_{key}.png"
                    )

                    out_path.write_bytes(raw_bytes)

                    logger.info(
                        "GeminiImageGenerator: generated %s (%d bytes)",
                        out_path.name,
                        len(raw_bytes),
                    )

                    return out_path

            logger.warning(
                "GeminiImageGenerator: response contained no image data"
            )
            return None

        except Exception as exc:
            logger.warning(
                "GeminiImageGenerator: generation failed: %s",
                exc,
            )
            return None
