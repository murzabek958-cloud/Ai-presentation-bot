"""
presentation/compositions/hero.py
────────────────────────────────────────────────────────────────────────────
Phase 5 concrete handler for LayoutArchetype.HERO.

Replaces the PLACEHOLDER handler in CompositionSelector so that
VisualDesignSpec coordinates, fonts, and colors produced by Gemini are
applied directly to the PPTX slide instead of the legacy hardcoded layout.

Pipeline position
-----------------
    VisualDesignPlanner
            ↓
    VisualDesignSpec
            ↓
    renderer._slide_spec_index
            ↓
    builder._current_slide_spec      ← injected per slide by renderer
            ↓
    render_hero(pptx_slide, slide, directive, builder)
            ↓
    PPTX (exact Gemini coordinates)

Fallback guarantee
------------------
If builder._current_slide_spec is None (no visual_spec in pipeline, or
index lookup miss), render_hero() falls back to a clean, theme-consistent
hero layout using builder theme colors and TK tokens — identical quality
to the former PLACEHOLDER, but without double-rendering.

Public API
----------
    render_hero(pptx_slide, slide, directive, builder) -> None
    register() -> None
"""

from __future__ import annotations

import logging
from typing import Any

from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

from ai.schemas import SlideData, SlideLayout
from presentation.styles import TOKENS

logger = logging.getLogger(__name__)

TK = TOKENS

# ── alignment string → PP_ALIGN mapping ──────────────────────────────────
_ALIGN_MAP: dict[str, Any] = {
    "left":   PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right":  PP_ALIGN.RIGHT,
}

# ── slide dimensions (inches) — from builder.py constants ────────────────
_SLIDE_W = 13.33
_SLIDE_H = 7.5


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_color(value: str | None, fallback: str) -> str:
    """Return *value* if it looks like a hex color, else *fallback*."""
    if value and isinstance(value, str) and value.startswith("#") and len(value) >= 7:
        return value
    return fallback


def _safe_font(value: str | None, fallback: str) -> str:
    """Return *value* if non-empty, else *fallback*."""
    return value.strip() if value and value.strip() else fallback


def _safe_size(value: int | None, fallback: int) -> int:
    """Return *value* if positive int, else *fallback*."""
    if value and isinstance(value, int) and value > 0:
        return value
    return fallback


def _safe_coords(
    x: float, y: float, w: float, h: float
) -> tuple[float, float, float, float] | None:
    """
    Return (x, y, w, h) as Inches values when both dimensions are positive,
    else return None so the caller can skip the shape.
    """
    if w <= 0 or h <= 0:
        return None
    return Inches(x), Inches(y), Inches(w), Inches(h)


def _is_bold(font_weight: str | None) -> bool:
    return (font_weight or "").lower() == "bold"


def _alignment(alignment: str | None) -> Any:
    return _ALIGN_MAP.get((alignment or "").lower(), None)


def _find_elements(spec: Any, *types: str) -> list[Any]:
    """Return elements from spec.elements whose type is in *types*, sorted by z_index."""
    elements = getattr(spec, "elements", []) or []
    matched = [e for e in elements if getattr(e, "type", "") in types]
    matched.sort(key=lambda e: getattr(e, "z_index", 0))
    return matched


# ═══════════════════════════════════════════════════════════════════════════
# Spec-driven rendering helpers
# ═══════════════════════════════════════════════════════════════════════════

def _render_shape_element(pptx_slide: Any, el: Any, theme: Any) -> None:
    """Render a shape/divider element from ElementSpec."""
    from presentation.builder import _add_rect
    coords = _safe_coords(el.x, el.y, el.width, el.height)
    if coords is None:
        return
    ix, iy, iw, ih = coords
    fill   = _safe_color(getattr(el, "fill_color", None), theme.primary)
    border = getattr(el, "border_color", None)
    _add_rect(pptx_slide, ix, iy, iw, ih, fill,
              border if (border and border.startswith("#")) else None)


def _render_text_element(
    pptx_slide: Any,
    text: str,
    el: Any,
    default_size: int,
    default_color: str,
    default_font: str,
) -> None:
    """Render a text element (title/subtitle/body/card) using ElementSpec fields."""
    from presentation.builder import _add_text
    if not text:
        return
    coords = _safe_coords(el.x, el.y, el.width, el.height)
    if coords is None:
        return
    ix, iy, iw, ih = coords
    size  = _safe_size(getattr(el, "font_size", None), default_size)
    color = _safe_color(getattr(el, "font_color", None), default_color)
    font  = _safe_font(getattr(el, "font_family", None), default_font)
    bold  = _is_bold(getattr(el, "font_weight", None))
    align = _alignment(getattr(el, "alignment", None))
    _add_text(pptx_slide, text, ix, iy, iw, ih, size, color, font,
              bold=bold, align=align)


# ═══════════════════════════════════════════════════════════════════════════
# Fallback renderer (spec is None — theme-based hero)
# ═══════════════════════════════════════════════════════════════════════════

def _render_hero_fallback(
    pptx_slide: Any,
    slide: SlideData,
    builder: Any,
) -> None:
    """
    Theme-consistent HERO layout when no VisualDesignSpec is available.

    Renders a dark primary band (top ~52 % of slide) + title inside the
    band + subtitle below — mirrors the legacy hero_center variant without
    calling builder._render_title() to avoid double-rendering.
    """
    from presentation.builder import _add_rect, _add_text
    t = builder._theme
    c = slide.content

    # Background band
    band_h = Inches(3.85)
    _add_rect(pptx_slide, Inches(0), Inches(0),
              Inches(_SLIDE_W), band_h, t.primary)
    _add_rect(pptx_slide, Inches(0), band_h - Inches(0.06),
              Inches(_SLIDE_W), Inches(0.06), t.accent)

    # Title
    title_size = TK.heading_hero if len(slide.title) <= 80 else 32
    _add_text(pptx_slide, slide.title,
              Inches(0.75), Inches(0.75), Inches(11.83), Inches(2.8),
              title_size, t.text_light, t.font_heading, bold=True)

    # Subtitle
    subtitle = c.get("subtitle", "")
    if subtitle:
        sub_size = TK.subtitle_font_size if len(subtitle) <= 120 else 16
        _add_text(pptx_slide, subtitle,
                  Inches(0.75), Inches(4.1), Inches(11.0), Inches(1.5),
                  sub_size, t.text_dark, t.font_body)

    # Author
    author = c.get("author", "")
    if author:
        _add_text(pptx_slide, author,
                  Inches(0.75), Inches(6.6), Inches(5.0), Inches(0.65),
                  TK.author_font_size, t.secondary, t.font_body, italic=True)


# ═══════════════════════════════════════════════════════════════════════════
# Spec-driven renderer
# ═══════════════════════════════════════════════════════════════════════════

def _render_hero_from_spec(
    pptx_slide: Any,
    slide: SlideData,
    spec: Any,
    builder: Any,
) -> None:
    """
    Render HERO using Gemini VisualDesignSpec (SlideDesignSpec).

    Rendering order respects z_index so that Gemini's intended stacking
    is preserved:
        shapes/dividers (background decoration)
        subtitle / body
        title
    """
    from presentation.builder import _add_text
    t = builder._theme
    c = slide.content

    # ── 1. Background-level shapes and dividers (lowest z_index first) ──
    bg_elements = _find_elements(spec, "shape", "divider")
    for el in bg_elements:
        _render_shape_element(pptx_slide, el, t)

    # ── 2. Subtitle / body elements ──────────────────────────────────────
    subtitle = c.get("subtitle", "")
    for el in _find_elements(spec, "subtitle"):
        _render_text_element(
            pptx_slide, subtitle, el,
            default_size=TK.subtitle_font_size,
            default_color=t.text_dark,
            default_font=t.font_body,
        )

    body_text = c.get("body", "")
    for el in _find_elements(spec, "body"):
        _render_text_element(
            pptx_slide, body_text, el,
            default_size=TK.body_font_normal,
            default_color=t.text_dark,
            default_font=t.font_body,
        )

    # ── 3. Card elements ──────────────────────────────────────────────────
    for el in _find_elements(spec, "card"):
        _render_shape_element(pptx_slide, el, t)

    # ── 4. Title element (highest visual weight — render last) ───────────
    title_elements = _find_elements(spec, "title")
    if title_elements:
        el = title_elements[-1]  # use highest z_index title
        _render_text_element(
            pptx_slide, slide.title, el,
            default_size=TK.heading_hero,
            default_color=t.text_light,
            default_font=t.font_heading,
        )
    else:
        # No title element in spec — place a safe default
        _add_text(
            pptx_slide, slide.title,
            Inches(0.75), Inches(0.75), Inches(11.83), Inches(2.8),
            TK.heading_hero, t.text_light, t.font_heading, bold=True,
        )

    # ── 5. Author line (from slide content, not spec elements) ───────────
    author = c.get("author", "")
    if author:
        _add_text(
            pptx_slide, author,
            Inches(0.75), Inches(6.6), Inches(5.0), Inches(0.65),
            TK.author_font_size, t.secondary, t.font_body, italic=True,
        )

    logger.debug(
        "render_hero: spec-driven — slide_index=%d elements=%d "
        "title_els=%d subtitle_els=%d shape_els=%d",
        spec.slide_index,
        len(getattr(spec, "elements", [])),
        len(title_elements),
        len(_find_elements(spec, "subtitle")),
        len(bg_elements),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Public handler — CompositionHandler protocol
# ═══════════════════════════════════════════════════════════════════════════

def render_hero(
    pptx_slide: Any,
    slide: SlideData,
    directive: Any,
    builder: Any,
) -> None:
    """
    Phase 5 HERO composition handler.

    Reads builder._current_slide_spec (set by PresentationRenderer just
    before this call) to apply Gemini's exact visual specification.
    Falls back to a theme-consistent hero layout when spec is absent.

    Parameters
    ----------
    pptx_slide  : python-pptx Slide (already created, background applied).
    slide       : SlideData with title / content fields.
    directive   : SlideDesignDirective (spacing, accent overrides).
    builder     : PPTXBuilder instance (theme + helper methods).
    """
    spec = getattr(builder, "_current_slide_spec", None)

    if spec is None:
        logger.debug(
            "render_hero: no SlideDesignSpec for slide index=%d "
            "— using fallback layout",
            slide.index,
        )
        _render_hero_fallback(pptx_slide, slide, builder)
        return

    try:
        _render_hero_from_spec(pptx_slide, slide, spec, builder)
    except Exception as exc:
        logger.error(
            "render_hero: spec-driven render raised for slide index=%d: %s "
            "— falling back to theme layout",
            slide.index, exc, exc_info=True,
        )
        _render_hero_fallback(pptx_slide, slide, builder)


# ═══════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════

def register() -> None:
    """
    Register render_hero as the IMPLEMENTED handler for LayoutArchetype.HERO.

    Called by presentation.compositions.register_all_handlers() at startup.
    Must NOT be called at module import time.

    register() is idempotent: calling it more than once simply overwrites
    the registry entry with the same values (register_handler uses dict
    assignment, so no side effects from duplicate calls).
    """
    from presentation.composition_selector import CompositionSelector
    from ai.slide_design_schema import LayoutArchetype

    CompositionSelector.register_handler(
        archetype=LayoutArchetype.HERO,
        handler=render_hero,
        layout=SlideLayout.TITLE,
        description="Phase 5 HERO: Gemini VisualDesignSpec coordinates + theme fallback",
    )
    logger.info("render_hero registered for LayoutArchetype.HERO")
