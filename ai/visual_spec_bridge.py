"""
ai/visual_spec_bridge.py
────────────────────────────────────────────────────────────────────────────
Bridge: VisualDesignSpec  →  PresentationDesignPlan

Мәселе
------
VisualDesignPlanner Gemini-ден толық visual design specification алады:
  - composition_type  (e.g. "hero_split", "three_cards")
  - background.color  (e.g. "#1A2B3C")
  - title_width_ratio, spacing, text_alignment (elements-тен)
  - font_heading, font_body
  - visual_direction, color_strategy

Бірақ renderer.render() тек PresentationDesignPlan қабылдайды, ол
SlideDesignDirective тізімінен тұрады. visual_spec renderer-ге жетпейді.

Шешім
-----
visual_spec_to_design_plan(visual_spec, plan) функциясы:
  1. VisualDesignSpec.slides → SlideDesignDirective тізімі
  2. composition_type → LayoutArchetype (string mapping, no enum import needed)
  3. background.color → background_override
  4. elements → text_alignment, title_width_ratio
  5. font_heading, font_body → global_font_heading, global_font_body
  6. PresentationDesignPlan қайтарады — renderer pipeline қабылдайды

Priority
--------
USER EXPLICIT CONSTRAINT (DesignIntent)
        ↓
VISUAL DESIGN SPEC (Gemini Creative Director output)
        ↓
DESIGN INTELLIGENCE (archetype dispatch)
        ↓
RENDERER DEFAULTS

Осы bridge арқылы visual_spec мазмұны толығымен renderer-ге жетеді:
  background_override → builder.prepare_slide() → slide background
  archetype           → CompositionSelector → layout handler
  text_alignment      → SlideDesignDirective.text_alignment
  title_width_ratio   → SlideDesignDirective.title_width_ratio
  spacing             → SlideDesignDirective.spacing
  font_heading/body   → PresentationDesignPlan.global_font_*

Fallback
--------
Кез-келген slide үшін bridge сәтсіз болса — safe_default_directive()
қолданылады. Pipeline ешқашан тоқтамайды.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ai.visual_design_planner import VisualDesignSpec, SlideDesignSpec
    from ai.schemas import PresentationPlan


# ═══════════════════════════════════════════════════════════════════════════
# composition_type → LayoutArchetype string mapping
# ═══════════════════════════════════════════════════════════════════════════
# Gemini VisualDesignPlanner composition_type мәндерін LayoutArchetype
# string value-ларына map жасайды.
# Enum import жасамаймыз — circular dependency болмас үшін string қолданамыз.

_COMPOSITION_TO_ARCHETYPE: dict[str, str] = {
    # Title / hero
    "hero":                     "hero",
    "hero_split":               "hero_split",
    "hero_image_overlay":       "hero_image_overlay",
    # Section
    "section_divider":          "section_divider",
    # Content single-column
    "title_text":               "title_text",
    "title_bullets":            "title_bullets",
    "large_statement":          "large_statement",
    "editorial":                "editorial",
    # Two-column
    "two_columns_equal":        "two_columns_equal",
    "two_columns_asymmetric":   "two_columns_asymmetric",
    "card_duo":                 "card_duo",
    "icon_columns":             "icon_columns",
    # Image + text
    "image_left_text_right":    "image_left_text_right",
    "image_right_text_left":    "image_right_text_left",
    "full_bleed":               "full_bleed",
    "image_sidebar":            "image_sidebar",
    # Data / metrics
    "three_cards":              "three_cards",
    "four_cards":               "four_cards",
    "big_number":               "big_number",
    "horizontal_metrics":       "horizontal_metrics",
    "chart_focus":              "chart_focus",
    # Structured
    "timeline_horizontal":      "timeline_horizontal",
    "timeline_vertical":        "timeline_vertical",
    "process_steps":            "process_steps",
    "comparison_split":         "comparison_split",
    "comparison_table":         "comparison_table",
    "agenda":                   "agenda",
    # Quote
    "quote_centered":           "quote_centered",
    "quote_side":               "quote_side",
    "large_typography":         "large_typography",
    # Closing
    "closing":                  "closing",
    "minimal_final":            "minimal_final",
}

# SpacingDensity string values
_SPACING_VALUES = {"spacious", "normal", "dense"}

# TextAlignment string values
_ALIGNMENT_MAP = {
    "left":   "left",
    "center": "center",
    "right":  "right",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute or dict access."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ═══════════════════════════════════════════════════════════════════════════
# Per-slide conversion
# ═══════════════════════════════════════════════════════════════════════════

def _slide_spec_to_directive_kwargs(slide_spec: Any) -> dict[str, Any]:
    """
    Extract SlideDesignDirective constructor kwargs from a SlideDesignSpec.

    Returns a plain dict — no Pydantic import needed here.
    """
    kwargs: dict[str, Any] = {}

    slide_index = _get(slide_spec, "slide_index")
    if slide_index is None:
        return kwargs
    kwargs["slide_index"] = slide_index

    # ── archetype ────────────────────────────────────────────────────────
    composition_type = _get(slide_spec, "composition_type", "")
    archetype_str = _COMPOSITION_TO_ARCHETYPE.get(composition_type)
    if archetype_str:
        kwargs["archetype_str"] = archetype_str  # bridge-internal key
    else:
        logger.debug(
            "visual_spec_bridge: unknown composition_type %r for slide %d — "
            "archetype left to DesignIntelligence",
            composition_type,
            slide_index,
        )

    # ── background_override ──────────────────────────────────────────────
    bg = _get(slide_spec, "background")
    if bg is not None:
        bg_type = _get(bg, "type", "solid")
        if bg_type == "solid":
            color = _get(bg, "color")
            if color and isinstance(color, str) and color.startswith("#"):
                kwargs["background_override"] = color
        elif bg_type == "gradient":
            # Use gradient_start as the slide background color
            color = _get(bg, "gradient_start")
            if color and isinstance(color, str) and color.startswith("#"):
                kwargs["background_override"] = color

    # ── text_alignment (from first title/body element) ───────────────────
    elements = _get(slide_spec, "elements") or []
    for elem in elements:
        elem_type = _get(elem, "type", "")
        if elem_type in ("title", "body"):
            align = _get(elem, "alignment", "")
            mapped = _ALIGNMENT_MAP.get(str(align).lower())
            if mapped:
                kwargs["text_alignment"] = mapped
            break

    # ── title_width_ratio ────────────────────────────────────────────────
    # Derive from title element width (slide is 13.33 inches wide)
    _SLIDE_WIDTH_INCHES = 13.33
    for elem in elements:
        if _get(elem, "type") == "title":
            width = _get(elem, "width")
            if width and isinstance(width, (int, float)) and width > 0:
                ratio = round(float(width) / _SLIDE_WIDTH_INCHES, 3)
                ratio = max(0.2, min(1.0, ratio))  # clamp to [0.2, 1.0]
                kwargs["title_width_ratio"] = ratio
            break

    # ── spacing ──────────────────────────────────────────────────────────
    # SlideDesignSpec has no spacing field directly; derive from margin_top
    margin_top = _get(slide_spec, "margin_top", 0.4)
    if isinstance(margin_top, (int, float)):
        if margin_top >= 0.7:
            kwargs["spacing"] = "spacious"
        elif margin_top <= 0.25:
            kwargs["spacing"] = "dense"
        # else: leave default "normal"

    # ── notes (design_notes as directive notes) ──────────────────────────
    design_notes = _get(slide_spec, "design_notes", "")
    if design_notes:
        kwargs["notes"] = str(design_notes)[:300]

    return kwargs


# ═══════════════════════════════════════════════════════════════════════════
# Main bridge function
# ═══════════════════════════════════════════════════════════════════════════

def visual_spec_to_design_plan(
    visual_spec: Any,
    plan: Any,
    existing_design_plan: Any = None,
) -> Any:
    """
    Convert VisualDesignSpec → PresentationDesignPlan.

    VisualDesignSpec-тегі барлық дизайн мәліметтерін
    (composition, background, alignment, title_width_ratio, spacing, fonts)
    renderer pipeline қолданатын PresentationDesignPlan форматына түрлендіреді.

    Parameters
    ----------
    visual_spec          : VisualDesignPlanner шығарған VisualDesignSpec.
    plan                 : PresentationPlan (slide index тізімі үшін).
    existing_design_plan : DesignIntelligence шығарған PresentationDesignPlan.
                           Егер берілсе, visual_spec override жасайды:
                           archetype бар болса — ауыстырады,
                           жоқ болса — existing_design_plan-ның archetype сақталады.

    Returns
    -------
    PresentationDesignPlan — always valid, never raises.
    """
    # Import inside function — avoid circular deps and missing-module errors
    try:
        from ai.slide_design_schema import (
            PresentationDesignPlan,
            SlideDesignDirective,
            LayoutArchetype,
            TextAlignment,
            SpacingDensity,
            safe_default_directive,
        )
    except ImportError as exc:
        logger.error(
            "visual_spec_bridge: cannot import slide_design_schema: %s — "
            "returning existing_design_plan as-is",
            exc,
        )
        return existing_design_plan

    slides = _get(plan, "slides") or []

    # Build index: slide_index → SlideDesignSpec
    spec_slides = _get(visual_spec, "slides") or []
    spec_index: dict[int, Any] = {}
    for ss in spec_slides:
        idx = _get(ss, "slide_index")
        if idx is not None:
            spec_index[idx] = ss

    # Existing directives index (if provided)
    existing_index: dict[int, Any] = {}
    if existing_design_plan is not None:
        for d in (_get(existing_design_plan, "directives") or []):
            existing_index[_get(d, "slide_index")] = d

    directives: list[Any] = []

    for slide in slides:
        slide_index = _get(slide, "index")
        if slide_index is None:
            continue

        slide_spec = spec_index.get(slide_index)
        existing_d = existing_index.get(slide_index)

        # Start from existing directive or safe default
        if existing_d is not None:
            base = existing_d
        else:
            base = safe_default_directive(slide.layout, slide_index, has_image=False)

        if slide_spec is None:
            directives.append(base)
            continue

        # Extract kwargs from visual_spec slide
        try:
            kwargs = _slide_spec_to_directive_kwargs(slide_spec)
        except Exception as exc:
            logger.warning(
                "visual_spec_bridge: _slide_spec_to_directive_kwargs failed "
                "for slide %d: %s — using base directive",
                slide_index, exc,
            )
            directives.append(base)
            continue

        if not kwargs:
            directives.append(base)
            continue

        # Build updated directive
        try:
            # Start from base fields
            d_kwargs: dict[str, Any] = {
                "slide_index":      slide_index,
                "image_treatment":  base.image_treatment,
                "image_position":   base.image_position,
                "text_alignment":   base.text_alignment,
                "title_width_ratio":base.title_width_ratio,
                "accent_shape":     base.accent_shape,
                "accent_position":  base.accent_position,
                "spacing":          base.spacing,
                "background_override": base.background_override,
                "notes":            base.notes,
            }

            # ── archetype ────────────────────────────────────────────────
            archetype_str = kwargs.pop("archetype_str", None)
            if archetype_str:
                try:
                    d_kwargs["archetype"] = LayoutArchetype(archetype_str)
                except ValueError:
                    logger.debug(
                        "visual_spec_bridge: invalid archetype string %r for slide %d",
                        archetype_str, slide_index,
                    )
                    d_kwargs["archetype"] = base.archetype
            else:
                d_kwargs["archetype"] = base.archetype

            # ── background_override ──────────────────────────────────────
            if "background_override" in kwargs:
                d_kwargs["background_override"] = kwargs["background_override"]

            # ── text_alignment ───────────────────────────────────────────
            if "text_alignment" in kwargs:
                try:
                    d_kwargs["text_alignment"] = TextAlignment(kwargs["text_alignment"])
                except ValueError:
                    pass

            # ── title_width_ratio ────────────────────────────────────────
            if "title_width_ratio" in kwargs:
                d_kwargs["title_width_ratio"] = kwargs["title_width_ratio"]

            # ── spacing ──────────────────────────────────────────────────
            if "spacing" in kwargs:
                try:
                    d_kwargs["spacing"] = SpacingDensity(kwargs["spacing"])
                except ValueError:
                    pass

            # ── notes ────────────────────────────────────────────────────
            if "notes" in kwargs:
                d_kwargs["notes"] = kwargs["notes"]


            # ── Gemini visual modifiers → new SlideDesignDirective fields ─────
            # title_font_size_override: elements[type=title].font_size
            # title_color_override:     elements[type=title].font_color
            # accent_color_override:    presentation.accent_color
            for _elem in (_get(slide_spec, "elements") or []):
                if _get(_elem, "type") == "title":
                    _fs = _get(_elem, "font_size")
                    if _fs and isinstance(_fs, (int, float)) and 8 <= _fs <= 96:
                        d_kwargs["title_font_size_override"] = int(_fs)
                    _fc = _get(_elem, "font_color")
                    if _fc and isinstance(_fc, str) and _fc.startswith("#"):
                        d_kwargs["title_color_override"] = _fc
                    break
            _pres = _get(visual_spec, "presentation")
            if _pres is not None:
                _ac = _get(_pres, "accent_color")
                if _ac and isinstance(_ac, str) and _ac.startswith("#"):
                    d_kwargs["accent_color_override"] = _ac

            directive = SlideDesignDirective(**d_kwargs)
            directives.append(directive)

            logger.debug(
                "visual_spec_bridge: slide %d → archetype=%s bg=%s "
                "align=%s title_w=%.2f spacing=%s",
                slide_index,
                d_kwargs.get("archetype"),
                d_kwargs.get("background_override"),
                d_kwargs.get("text_alignment"),
                d_kwargs.get("title_width_ratio") or 0,
                d_kwargs.get("spacing"),
            )

        except Exception as exc:
            logger.error(
                "visual_spec_bridge: SlideDesignDirective construction failed "
                "for slide %d: %s — using base directive",
                slide_index, exc,
            )
            directives.append(base)

    # ── Global fonts from visual_spec.presentation ──────────────────────
    presentation = _get(visual_spec, "presentation")
    g_font_heading = _get(presentation, "heading_font") if presentation else None
    g_font_body    = _get(presentation, "body_font")    if presentation else None
    g_spacing_str  = _get(presentation, "global_spacing", "normal") if presentation else "normal"

    # Prefer existing plan's fonts if visual_spec didn't set them
    if existing_design_plan is not None:
        g_font_heading = g_font_heading or _get(existing_design_plan, "global_font_heading")
        g_font_body    = g_font_body    or _get(existing_design_plan, "global_font_body")

    try:
        g_spacing = SpacingDensity(g_spacing_str) if g_spacing_str in _SPACING_VALUES else SpacingDensity.NORMAL
    except ValueError:
        g_spacing = SpacingDensity.NORMAL

    # design_rationale
    visual_direction = _get(presentation, "visual_direction", "") if presentation else ""
    rationale_parts = [visual_direction]
    if existing_design_plan:
        rationale_parts.append(_get(existing_design_plan, "design_rationale", ""))
    design_rationale = " | ".join(p for p in rationale_parts if p)

    try:
        merged_plan = PresentationDesignPlan(
            directives=directives,
            global_font_heading=g_font_heading or None,
            global_font_body=g_font_body or None,
            global_spacing=g_spacing,
            design_rationale=design_rationale[:500],
        )
    except Exception as exc:
        logger.error(
            "visual_spec_bridge: PresentationDesignPlan construction failed: %s — "
            "returning existing_design_plan",
            exc,
        )
        return existing_design_plan

    logger.info(
        "visual_spec_bridge: merged VisualDesignSpec → PresentationDesignPlan "
        "directives=%d font_heading=%r font_body=%r spacing=%s",
        len(directives),
        g_font_heading,
        g_font_body,
        g_spacing,
    )
    return merged_plan
