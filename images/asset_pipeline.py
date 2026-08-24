"""
images/asset_pipeline.py
────────────────────────────────────────────────────────────────────────────
Visual Asset Pipeline — generates and resolves image assets defined in
a VisualDesignSpec produced by VisualDesignPlanner.

Role in the pipeline
--------------------
    VisualDesignSpec  (from VisualDesignPlanner)
              ↓
    ImageAssetPipeline.resolve_all(spec)
              ↓
    AssetResolutionResult
      .resolved   : dict[asset_id → Path]  (successfully resolved)
      .failed     : dict[asset_id → str]   (failure reason)
              ↓
    Composition Engine / Renderer / PPTXBuilder

Fallback chain (PER ASSET)
---------------------------
    1. Generated image  (Gemini image generation)
         ↓ failure: API error / timeout / quota / empty response
    2. Existing local asset from cache
         ↓ unavailable
    3. Placeholder (solid color rectangle — composition engine draws it)
         ↓
    Continue rendering — never abort

CRITICAL RULES
--------------
- ONE asset failure NEVER stops the pipeline.
- The presentation ALWAYS completes even if ALL assets fail.
- Each failure emits WARNING log + records reason in AssetResolutionResult.failed.
- The composition engine must handle missing asset_id gracefully (use fallback_color).

Logging format (per specification)
------------------------------------
    Visual assets requested: N
    Images generated: N
    Images failed: N
    Fallback assets used: N
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from images.gemini_generator import GeminiImageGenerator
from images.cache import ImageCache
from images.validator import validate_image

logger = logging.getLogger(__name__)

# Temp directory for generated images
_ASSET_CACHE_DIR = "cache/images/assets"


# ═══════════════════════════════════════════════════════════════════════════
# Result containers
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AssetResolutionResult:
    """
    Outcome of ImageAssetPipeline.resolve_all().

    Attributes
    ----------
    resolved : dict[asset_id → Path]
        Assets that were successfully generated or found in cache.
    failed   : dict[asset_id → str]
        Assets that could not be resolved; value is the failure reason.
    generated : int
        Number of assets produced via Gemini image generation.
    from_cache : int
        Number of assets served from existing cache.
    fallback_colors_used : int
        Number of assets that fell back to solid-color placeholder.
    """
    resolved: dict[str, Path] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    generated: int = 0
    from_cache: int = 0
    fallback_colors_used: int = 0

    @property
    def total_requested(self) -> int:
        return len(self.resolved) + len(self.failed)

    @property
    def success_count(self) -> int:
        return len(self.resolved)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    def log_summary(self) -> None:
        logger.info(
            "ImageAssetPipeline summary — "
            "Visual assets requested: %d  "
            "Images generated: %d  "
            "From cache: %d  "
            "Images failed: %d  "
            "Fallback assets used: %d",
            self.total_requested,
            self.generated,
            self.from_cache,
            self.failure_count,
            self.fallback_colors_used,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Asset spec (local import to avoid circular dependency)
# ═══════════════════════════════════════════════════════════════════════════

def _extract_assets_from_spec(spec: Any) -> list[Any]:
    """
    Extract all SlideAsset objects from a VisualDesignSpec.

    Works with both VisualDesignSpec objects and plain dicts.
    Returns list of objects with: id, prompt, aspect_ratio, fallback_color.
    """
    assets: list[Any] = []

    slides = getattr(spec, "slides", None)
    if slides is None and isinstance(spec, dict):
        slides = spec.get("slides", [])

    if slides is None:
        return assets

    for slide in slides:
        slide_assets = getattr(slide, "assets", None)
        if slide_assets is None and isinstance(slide, dict):
            slide_assets = slide.get("assets", [])
        if slide_assets:
            assets.extend(slide_assets)

        # Also check background for generated_image type
        bg = getattr(slide, "background", None)
        if bg is None and isinstance(slide, dict):
            bg = slide.get("background", {})

        if bg:
            bg_type = getattr(bg, "type", None) or (bg.get("type") if isinstance(bg, dict) else None)
            if bg_type == "generated_image":
                bg_prompt = (
                    getattr(bg, "image_prompt", None)
                    or (bg.get("image_prompt") if isinstance(bg, dict) else None)
                )
                bg_asset_id = (
                    getattr(bg, "asset_id", None)
                    or (bg.get("asset_id") if isinstance(bg, dict) else None)
                )
                if bg_prompt and not bg_asset_id:
                    # Create synthetic asset entry for background
                    slide_idx = (
                        getattr(slide, "slide_index", "?")
                        if not isinstance(slide, dict)
                        else slide.get("slide_index", "?")
                    )

                    class _SyntheticAsset:
                        def __init__(self, id_: str, prompt_: str) -> None:
                            self.id = id_
                            self.prompt = prompt_
                            self.aspect_ratio = "16:9"
                            self.fallback_color = "#1E3A5F"
                            self.purpose = "background"

                    assets.append(_SyntheticAsset(
                        id_=f"bg_{slide_idx}",
                        prompt_=bg_prompt,
                    ))

    return assets


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute from object or dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ═══════════════════════════════════════════════════════════════════════════
# ImageAssetPipeline
# ═══════════════════════════════════════════════════════════════════════════

class ImageAssetPipeline:
    """
    Resolves all visual assets defined in a VisualDesignSpec.

    Per-asset fallback chain:
      1. Cache hit → return immediately
      2. Gemini image generation → validate → cache → return
      3. Log warning → record failure → use fallback_color in composition

    The pipeline NEVER raises. Every asset either resolves to a Path or
    records a failure reason. The presentation generation continues.

    Usage::

        pipeline = ImageAssetPipeline()
        result = await pipeline.resolve_all(visual_spec)

        # Check if an asset resolved:
        path = result.resolved.get("hero_01")  # Path | None
        if path is None:
            # Use fallback_color from the SlideAsset spec
            pass
    """

    def __init__(
        self,
        generator: GeminiImageGenerator | None = None,
        cache: ImageCache | None = None,
        cache_dir: str = _ASSET_CACHE_DIR,
    ) -> None:
        self._generator = generator or GeminiImageGenerator()
        self._cache = cache or ImageCache(cache_dir)
        self._cache_dir = cache_dir

    async def resolve_all(self, spec: Any) -> AssetResolutionResult:
        """
        Resolve all assets in a VisualDesignSpec.

        Parameters
        ----------
        spec : VisualDesignSpec (or compatible dict)
            The design spec produced by VisualDesignPlanner.

        Returns
        -------
        AssetResolutionResult — never raises.
        """
        result = AssetResolutionResult()
        assets = _extract_assets_from_spec(spec)

        if not assets:
            logger.info("ImageAssetPipeline: no visual assets requested")
            result.log_summary()
            return result

        logger.info(
            "ImageAssetPipeline: resolving %d visual asset(s)",
            len(assets),
        )

        for asset in assets:
            asset_id = _get_attr(asset, "id", f"asset_{len(result.resolved)}")
            await self._resolve_single(asset, asset_id, result)

        result.log_summary()
        return result

    async def _resolve_single(
        self,
        asset: Any,
        asset_id: str,
        result: AssetResolutionResult,
    ) -> None:
        """
        Attempt to resolve a single asset through the fallback chain.
        Records outcome in `result`. Never raises.
        """
        prompt = _get_attr(asset, "prompt", "")
        aspect_ratio = _get_attr(asset, "aspect_ratio", "16:9")

        # ── Step 1: Cache check ───────────────────────────────────────────
        try:
            from images.intent import ImageIntent
            if prompt:
                cached = self._cache.get(prompt)
                if cached and cached.exists():
                    logger.info(
                        "ImageAssetPipeline: cache hit for asset %r", asset_id
                    )
                    result.resolved[asset_id] = cached
                    result.from_cache += 1
                    return
        except Exception as exc:
            logger.debug("ImageAssetPipeline: cache check error for %r: %s", asset_id, exc)

        # ── Step 2: Gemini image generation ──────────────────────────────
        if prompt:
            try:
                import asyncio
                path = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._generator.generate(
                        prompt=prompt,
                        dest_dir=self._cache_dir,
                        filename_hint=asset_id,
                    ),
                )

                if path and path.exists():
                    # Validate the generated image
                    vr = validate_image(path)
                    if vr.valid:
                        # Store in cache
                        try:
                            self._cache.put(prompt, path)
                        except Exception:
                            pass  # Cache write failure is non-fatal
                        result.resolved[asset_id] = path
                        result.generated += 1
                        logger.info(
                            "ImageAssetPipeline: generated asset %r → %s",
                            asset_id,
                            path.name,
                        )
                        return
                    else:
                        logger.warning(
                            "ImageAssetPipeline: generated image invalid for %r: %s",
                            asset_id,
                            vr.reason,
                        )
                else:
                    logger.warning(
                        "ImageAssetPipeline: generation returned no file for %r",
                        asset_id,
                    )

            except Exception as exc:
                logger.warning(
                    "ImageAssetPipeline: generation failed for asset %r: %s",
                    asset_id,
                    exc,
                )

        # ── Step 3: Fallback — solid color placeholder ────────────────────
        # Record failure; composition engine uses fallback_color
        fallback_color = _get_attr(asset, "fallback_color", "#1E3A5F")
        reason = f"image generation failed — fallback_color={fallback_color}"
        result.failed[asset_id] = reason
        result.fallback_colors_used += 1
        logger.warning(
            "WARNING: image generation failed for asset %r. "
            "Falling back to composition-only rendering (color=%s)",
            asset_id,
            fallback_color,
        )

    def resolve_all_sync(self, spec: Any) -> AssetResolutionResult:
        """
        Synchronous wrapper around resolve_all().
        Use only in tests or scripts.
        """
        import asyncio
        return asyncio.run(self.resolve_all(spec))
