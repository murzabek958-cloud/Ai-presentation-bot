"""
presentation/spec_renderer.py
────────────────────────────────────────────────────────────────────────────
SpecRenderer — Gemini VisualDesignSpec-тегі assets-ті builder-ге жеткізеді.

Production-safe тәсіл
---------------------
builder.py-дың _render_* методтары (timeline, stats, chart, comparison т.б.)
барлық layout логикасын, bullet list-тер, card grid-тер, spine рects, oval
dots-тарды жасайды. SpecRenderer ЕШҚАШАН осы shapes-тарды жоймайды.

Gemini визуалды ықпалы 2 жолмен жетеді:
  1. visual_spec_bridge → SlideDesignDirective →
       background_override        (prepare_slide → slide background)
       archetype                  (CompositionSelector dispatch)
       title_font_size_override   (_add_slide_title font size)
       title_color_override       (_add_slide_title text color)
       accent_color_override      (_add_slide_title rule color)
       text_alignment, spacing    (directive fields)

  2. SpecRenderer.inject_assets() →
       IMAGE_TEXT slides: visual_spec asset path → image_paths dict

SpecRenderer жасайтын жалғыз нәрсе — image_paths-ті толықтыру.
Builder layout-тары толығымен сақталады.

Coordinate system
-----------------
VisualDesignSpec: x, y, width, height — float inches
builder.py:       Inches(x) — EMU (1 inch = 914400 EMU)
=> Inches(spec.x) тікелей жұмыс істейді, конверсия қажет емес.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class SpecRenderer:
    """
    Production-safe bridge: VisualDesignSpec assets → image_paths.

    Builder layout логикасын (timeline, stats, comparison, chart т.б.)
    БҰЗБАЙДЫ. Тек IMAGE_TEXT slides үшін resolved asset path-тарды
    image_paths dict-ке қосады.

    Usage::
        spec_renderer = SpecRenderer(visual_spec, asset_result.resolved)
        image_paths = spec_renderer.inject_assets(plan.slides, image_paths)
        # Enriched image_paths → renderer.render(image_paths=image_paths)
    """

    def __init__(
        self,
        visual_spec: Any,
        resolved_assets: dict[str, Path] | None = None,
    ) -> None:
        self._spec   = visual_spec
        self._assets = resolved_assets or {}

    def inject_assets(
        self,
        plan_slides: list[Any],
        existing_image_paths: dict[int, str],
    ) -> dict[int, str]:
        """
        Merge resolved visual assets into image_paths for IMAGE_TEXT slides.

        Non-destructive: existing image_paths entries are never overwritten.
        Only adds assets for slides that have no image yet.

        Parameters
        ----------
        plan_slides          : list[SlideData] from PresentationPlan.slides.
        existing_image_paths : dict[slide_index → str path] from
                               _fetch_image_paths_for_slides().

        Returns
        -------
        dict[slide_index → str path] — existing + newly injected paths.
        """
        if not self._spec or not self._assets:
            return existing_image_paths

        from ai.schemas import SlideLayout

        merged = dict(existing_image_paths)

        # Build index: slide_index → SlideDesignSpec
        spec_slides = _get(self._spec, "slides") or []
        spec_index: dict[int, Any] = {}
        for ss in spec_slides:
            idx = _get(ss, "slide_index")
            if idx is not None:
                spec_index[idx] = ss

        for slide in plan_slides:
            idx = _get(slide, "index")
            if idx is None or idx in merged:
                continue  # already has image

            layout = _get(slide, "layout")
            if layout != SlideLayout.IMAGE_TEXT:
                continue  # only IMAGE_TEXT embeds pictures

            slide_spec = spec_index.get(idx)
            if slide_spec is None:
                continue

            # Find hero_visual or illustration asset for this slide
            for asset in (_get(slide_spec, "assets") or []):
                asset_id = _get(asset, "id")
                purpose  = _get(asset, "purpose", "")
                if purpose in ("hero_visual", "illustration", "content") and asset_id:
                    path = self._assets.get(asset_id)
                    if path is not None:
                        merged[idx] = str(path)
                        logger.info(
                            "SpecRenderer: injected asset %r → IMAGE_TEXT slide %d",
                            asset_id, idx,
                        )
                        break

        return merged
