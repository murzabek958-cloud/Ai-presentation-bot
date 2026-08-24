"""
ai/visual_design_planner.py
────────────────────────────────────────────────────────────────────────────
Gemini Visual Design Planner — Creative Director / Art Director layer.

Role in the pipeline
--------------------
    PresentationPlan  (content already resolved)
    DesignIntent      (explicit user constraints)
              ↓
    VisualDesignPlanner.plan()
              ↓
    VisualDesignSpec  (full per-slide design specification)
              ↓
    ImageAssetPipeline  (generate / resolve assets)
              ↓
    Composition Engine / Renderer / PPTXBuilder

Key difference from DesignIntelligence (ai/design_intelligence.py)
-------------------------------------------------------------------
DesignIntelligence makes Gemini choose a *pre-defined archetype* from a
fixed menu.  This module makes Gemini act as a true Creative Director:
Gemini freely plans every visual detail (coordinates, sizes, fonts, colors,
asset prompts, background strategy) and the Composition Engine executes
that plan.  Pre-defined archetypes remain available as *primitives*, not
as the primary design decision.

Fallback guarantee
------------------
If Gemini fails at any point the method returns a VisualDesignSpec built
from safe defaults.  The pipeline NEVER stops due to design planning failure.

Image generation fallback chain
--------------------------------
    Generated image
          ↓ failure
    Existing / local asset
          ↓ unavailable
    Solid background / shape
          ↓
    Continue rendering (no image)

Priority order for user constraints
-------------------------------------
    USER EXPLICIT CONSTRAINT  (DesignIntent)
          ↓
    DESIGN SPECIFICATION      (Gemini output)
          ↓
    COMPOSITION ENGINE
          ↓
    RENDERER DEFAULTS
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from config.settings import settings
from ai.design_intent import DesignIntent
from ai.schemas import PresentationPlan, SlideData, SlideLayout

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Schema — VisualDesignSpec
# ═══════════════════════════════════════════════════════════════════════════

class BackgroundSpec(BaseModel):
    """Background specification for a single slide."""
    type: str = "solid"                 # "solid" | "gradient" | "generated_image" | "transparent"
    color: str | None = None            # "#RRGGBB" for solid
    gradient_start: str | None = None   # "#RRGGBB"
    gradient_end: str | None = None     # "#RRGGBB"
    gradient_angle: int | None = None   # 0–360
    image_prompt: str | None = None     # for type="generated_image"
    asset_id: str | None = None         # reference to assets list


class ElementSpec(BaseModel):
    """A single visual element on a slide."""
    type: str                           # "title"|"subtitle"|"body"|"image"|"shape"|"divider"|"card"
    x: float = 0.5                      # inches from left
    y: float = 0.5                      # inches from top
    width: float = 12.0                 # inches
    height: float = 1.5                 # inches
    # Text properties
    font_family: str | None = None
    font_size: int | None = None
    font_weight: str | None = None      # "regular" | "bold" | "light"
    font_color: str | None = None       # "#RRGGBB"
    alignment: str | None = None        # "left" | "center" | "right"
    # Image properties
    asset_id: str | None = None         # references SlideAsset.id
    # Shape properties
    fill_color: str | None = None       # "#RRGGBB"
    border_color: str | None = None     # "#RRGGBB"
    border_radius: float | None = None  # corner radius in pt
    # Layout hints (for composition engine)
    z_index: int = 0                    # drawing order; higher = on top
    opacity: float = 1.0               # 0.0–1.0


class SlideAsset(BaseModel):
    """A visual asset required by a slide (to be generated or resolved)."""
    id: str                             # unique within the slide, e.g. "hero_01"
    type: str                           # "generated_image" | "icon" | "chart"
    purpose: str                        # "hero_visual"|"background"|"illustration"|"decoration"
    prompt: str | None = None           # image generation prompt
    aspect_ratio: str = "16:9"          # "16:9" | "1:1" | "4:3" | "9:16"
    fallback_color: str = "#1E3A5F"     # solid color used if generation fails


class SlideDesignSpec(BaseModel):
    """Complete visual design specification for a single slide."""
    slide_index: int
    purpose: str = "content"            # "title"|"section"|"content"|"data"|"closing"

    # Composition
    composition_type: str = "title_text"
    visual_balance: str = "50/50"       # e.g. "60/40", "70/30"
    visual_hierarchy: str = "title"     # dominant element: "title"|"image"|"metric"

    # Background
    background: BackgroundSpec = Field(default_factory=BackgroundSpec)

    # Elements
    elements: list[ElementSpec] = Field(default_factory=list)

    # Assets to generate/resolve
    assets: list[SlideAsset] = Field(default_factory=list)

    # Typography overrides (slide-level)
    font_heading: str | None = None
    font_body: str | None = None

    # Spacing / margins
    margin_top: float = 0.4
    margin_left: float = 0.5
    margin_right: float = 0.5
    margin_bottom: float = 0.4

    # Constraints carried from user
    forbidden_colors: list[str] = Field(default_factory=list)

    # Designer notes
    design_notes: str = ""


class PresentationVisualDirection(BaseModel):
    """Presentation-level visual strategy."""
    visual_direction: str = ""
    style: str = "modern"
    color_strategy: str = ""
    typography_strategy: str = ""
    primary_color: str = "#1E3A5F"
    accent_color: str = "#E67E22"
    background_color: str = "#FFFFFF"
    heading_font: str = "Calibri"
    body_font: str = "Calibri"
    global_spacing: str = "normal"      # "spacious"|"normal"|"dense"
    design_rationale: str = ""


class VisualDesignSpec(BaseModel):
    """
    Full visual design specification for a presentation.

    Produced by VisualDesignPlanner and consumed by the Composition Engine.
    """
    presentation: PresentationVisualDirection = Field(
        default_factory=PresentationVisualDirection
    )
    slides: list[SlideDesignSpec] = Field(default_factory=list)

    # Pipeline metadata
    generated_by_gemini: bool = False
    fallback_used: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Default spec builders
# ═══════════════════════════════════════════════════════════════════════════

_LAYOUT_DEFAULTS: dict[SlideLayout, dict[str, Any]] = {
    SlideLayout.TITLE: {
        "composition_type": "hero",
        "visual_hierarchy": "title",
        "visual_balance": "center",
        "purpose": "title",
    },
    SlideLayout.TITLE_TEXT: {
        "composition_type": "title_text",
        "visual_hierarchy": "title",
        "visual_balance": "70/30",
        "purpose": "content",
    },
    SlideLayout.IMAGE_TEXT: {
        "composition_type": "image_left_text_right",
        "visual_hierarchy": "image",
        "visual_balance": "50/50",
        "purpose": "content",
    },
    SlideLayout.TWO_COLUMNS: {
        "composition_type": "two_columns_equal",
        "visual_hierarchy": "title",
        "visual_balance": "50/50",
        "purpose": "content",
    },
    SlideLayout.COMPARISON: {
        "composition_type": "comparison_split",
        "visual_hierarchy": "title",
        "visual_balance": "50/50",
        "purpose": "content",
    },
    SlideLayout.TIMELINE: {
        "composition_type": "timeline_horizontal",
        "visual_hierarchy": "title",
        "visual_balance": "80/20",
        "purpose": "content",
    },
    SlideLayout.STATISTICS: {
        "composition_type": "three_cards",
        "visual_hierarchy": "metric",
        "visual_balance": "center",
        "purpose": "data",
    },
    SlideLayout.CHART: {
        "composition_type": "chart_focus",
        "visual_hierarchy": "title",
        "visual_balance": "70/30",
        "purpose": "data",
    },
    SlideLayout.QUOTE: {
        "composition_type": "quote_centered",
        "visual_hierarchy": "title",
        "visual_balance": "center",
        "purpose": "content",
    },
    SlideLayout.CONCLUSION: {
        "composition_type": "closing",
        "visual_hierarchy": "title",
        "visual_balance": "center",
        "purpose": "closing",
    },
    SlideLayout.AGENDA: {
        "composition_type": "agenda",
        "visual_hierarchy": "title",
        "visual_balance": "60/40",
        "purpose": "content",
    },
}


def _safe_slide_spec(slide: SlideData, direction: PresentationVisualDirection) -> SlideDesignSpec:
    """Build a safe default SlideDesignSpec for a slide."""
    defaults = _LAYOUT_DEFAULTS.get(slide.layout, {
        "composition_type": "title_text",
        "visual_hierarchy": "title",
        "visual_balance": "70/30",
        "purpose": "content",
    })

    bg = BackgroundSpec(
        type="solid",
        color=direction.background_color,
    )

    # Default elements: title + body text block
    elements = [
        ElementSpec(
            type="title",
            x=0.5,
            y=0.5,
            width=12.33,
            height=1.2,
            font_family=direction.heading_font,
            font_size=32,
            font_weight="bold",
            font_color=direction.primary_color,
            alignment="left",
            z_index=1,
        ),
        ElementSpec(
            type="body",
            x=0.5,
            y=2.0,
            width=12.33,
            height=4.5,
            font_family=direction.body_font,
            font_size=18,
            font_weight="regular",
            font_color="#333333",
            alignment="left",
            z_index=1,
        ),
    ]

    return SlideDesignSpec(
        slide_index=slide.index,
        purpose=defaults["purpose"],
        composition_type=defaults["composition_type"],
        visual_balance=defaults["visual_balance"],
        visual_hierarchy=defaults["visual_hierarchy"],
        background=bg,
        elements=elements,
        font_heading=direction.heading_font,
        font_body=direction.body_font,
        design_notes="safe default — Gemini design planning skipped",
    )


def _safe_design_spec(
    plan: PresentationPlan,
    design_intent: DesignIntent | None = None,
    reason: str = "unknown",
) -> VisualDesignSpec:
    """Build a fully safe VisualDesignSpec as ultimate fallback."""
    logger.warning("VisualDesignPlanner: using safe defaults. Reason: %s", reason)

    bg_color = "#FFFFFF"
    primary = "#1E3A5F"
    accent = "#E67E22"

    if design_intent and not design_intent.is_empty():
        bg_color = design_intent.background_color or bg_color
        primary  = design_intent.primary_color   or primary
        accent   = design_intent.accent_color    or accent

    direction = PresentationVisualDirection(
        style=plan.style,
        primary_color=primary,
        accent_color=accent,
        background_color=bg_color,
        heading_font=getattr(design_intent, "font_heading", None) or "Calibri",
        body_font=getattr(design_intent, "font_body", None) or "Calibri",
    )

    slides = [_safe_slide_spec(s, direction) for s in plan.slides]

    return VisualDesignSpec(
        presentation=direction,
        slides=slides,
        generated_by_gemini=False,
        fallback_used=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Prompt construction
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a Creative Director and Art Director for slide presentations.

Your task: produce a complete visual design specification for a presentation.
You do NOT write slide content. You design how each slide will LOOK visually.

You must return a JSON object matching this schema exactly:

{
  "presentation": {
    "visual_direction": "<2-3 sentence design concept>",
    "style": "<academic|modern|minimal>",
    "color_strategy": "<describe palette rationale>",
    "typography_strategy": "<describe font pairing rationale>",
    "primary_color": "#RRGGBB",
    "accent_color": "#RRGGBB",
    "background_color": "#RRGGBB",
    "heading_font": "<font name>",
    "body_font": "<font name>",
    "global_spacing": "<spacious|normal|dense>",
    "design_rationale": "<overall design direction>"
  },
  "slides": [
    {
      "slide_index": <int>,
      "purpose": "<title|section|content|data|closing>",
      "composition_type": "<see allowed types below>",
      "visual_balance": "<e.g. 60/40 or center>",
      "visual_hierarchy": "<title|image|metric>",
      "background": {
        "type": "<solid|gradient|generated_image|transparent>",
        "color": "#RRGGBB",
        "gradient_start": "#RRGGBB or null",
        "gradient_end": "#RRGGBB or null",
        "gradient_angle": <int or null>,
        "image_prompt": "<prompt if type=generated_image, else null>",
        "asset_id": "<id if referencing an asset, else null>"
      },
      "elements": [
        {
          "type": "<title|subtitle|body|image|shape|divider|card>",
          "x": <float inches>,
          "y": <float inches>,
          "width": <float inches>,
          "height": <float inches>,
          "font_family": "<font or null>",
          "font_size": <int or null>,
          "font_weight": "<regular|bold|light or null>",
          "font_color": "#RRGGBB or null",
          "alignment": "<left|center|right or null>",
          "asset_id": "<references assets[].id or null>",
          "fill_color": "#RRGGBB or null",
          "border_color": "#RRGGBB or null",
          "z_index": <int>,
          "opacity": <float 0.0-1.0>
        }
      ],
      "assets": [
        {
          "id": "<unique string>",
          "type": "<generated_image|icon|chart>",
          "purpose": "<hero_visual|background|illustration|decoration>",
          "prompt": "<detailed image generation prompt>",
          "aspect_ratio": "<16:9|1:1|4:3>",
          "fallback_color": "#RRGGBB"
        }
      ],
      "font_heading": "<font or null>",
      "font_body": "<font or null>",
      "margin_top": <float>,
      "margin_left": <float>,
      "margin_right": <float>,
      "margin_bottom": <float>,
      "forbidden_colors": [],
      "design_notes": "<brief rationale>"
    }
  ]
}

ALLOWED COMPOSITION TYPES:
  Title slides: hero, hero_split, hero_image_overlay
  Section: section_divider
  Content: title_text, title_bullets, large_statement, editorial
  Two-column: two_columns_equal, two_columns_asymmetric, card_duo, icon_columns
  Image+text: image_left_text_right, image_right_text_left, full_bleed, image_sidebar
  Data: three_cards, four_cards, big_number, horizontal_metrics, chart_focus
  Structured: timeline_horizontal, timeline_vertical, process_steps,
              comparison_split, comparison_table, agenda
  Quote: quote_centered, quote_side, large_typography
  Closing: closing, minimal_final

SLIDE DIMENSIONS: 13.33 inches wide × 7.5 inches tall (16:9 widescreen)

DESIGN PRINCIPLES:
1. You decide the full visual layout. Do NOT just pick an archetype from a menu.
   Think like a real Art Director: where exactly does each element go?
   What size? What color? What font weight?

2. Visual variety: never use the same composition_type more than 2 slides in a row.

3. Hierarchy: every slide has ONE dominant element (title/image/metric).
   All other elements are subordinate.

4. If a slide has image_query, design an image element and add an asset entry
   with a detailed generation prompt.

5. Asset prompts must be specific and visual:
   Good: "abstract dark blue ocean wave texture, soft gradients, no text, 4K"
   Bad: "ocean"

6. For data slides (statistics), consider: big_number for 1 stat,
   three_cards for 3 stats, four_cards for 4 stats.

7. Background can be: solid (default), gradient (elegant), generated_image
   (immersive, use sparingly), or transparent.

8. CRITICAL: Honor explicit user constraints. If user said "red background",
   background_color must be red on title and section slides.
   If user said "no green", add "#00FF00" family to forbidden_colors.
   User constraints ALWAYS win over your design preferences.

9. Font recommendations for safe rendering:
   Professional: Calibri, Arial, Helvetica
   Modern: Montserrat, Open Sans
   Academic: Georgia, Times New Roman

10. Return ONLY valid JSON. No markdown, no code fences, no prose.
"""


def _build_user_prompt(
    plan: PresentationPlan,
    design_intent: DesignIntent | None,
) -> str:
    """Build the user-turn prompt for Gemini Visual Design Planner."""
    lines: list[str] = []

    lines.append("PRESENTATION TO DESIGN:")
    lines.append(f"  Topic: {plan.topic}")
    lines.append(f"  Style: {plan.style}")
    lines.append(f"  Slide count: {plan.slide_count}")
    lines.append(f"  Language: {plan.metadata.language}")
    lines.append("")

    if design_intent and not design_intent.is_empty():
        lines.append("EXPLICIT USER DESIGN CONSTRAINTS (HIGHEST PRIORITY — NEVER OVERRIDE):")
        if design_intent.background_color:
            lines.append(f"  background_color: {design_intent.background_color}")
        if design_intent.primary_color:
            lines.append(f"  primary_color: {design_intent.primary_color}")
        if design_intent.accent_color:
            lines.append(f"  accent_color: {design_intent.accent_color}")
        if design_intent.font_heading:
            lines.append(f"  font_heading: {design_intent.font_heading}")
        if design_intent.font_body:
            lines.append(f"  font_body: {design_intent.font_body}")
        if design_intent.style_hint:
            lines.append(f"  style_hint: {design_intent.style_hint}")
        if design_intent.density_hint:
            lines.append(f"  density_hint: {design_intent.density_hint}")
        lines.append("  ↑ These constraints propagate to ALL slides. Do not ignore them.")
        lines.append("")

    lines.append("SLIDES (content summary):")
    for slide in plan.slides:
        has_img = slide.image_query is not None
        lines.append(f"  [{slide.index}] layout_hint={slide.layout.value}  title={slide.title!r}")
        if slide.image_query:
            lines.append(f"       image_query={slide.image_query!r}")
        lines.append(f"       has_image_query={has_img}")
        # Summarize content briefly
        c = slide.content
        if c:
            summary_keys = ["body", "subtitle", "stats", "events", "quote", "items"]
            for k in summary_keys:
                if k in c:
                    val = c[k]
                    if isinstance(val, str):
                        lines.append(f"       {k}: {val[:60]}")
                    elif isinstance(val, list):
                        lines.append(f"       {k}: {len(val)} item(s)")
                    break
        lines.append("")

    lines.append(f"Design ALL {plan.slide_count} slides. Return ONLY the JSON object.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Response parsing
# ═══════════════════════════════════════════════════════════════════════════

def _apply_user_constraints(
    spec: VisualDesignSpec,
    design_intent: DesignIntent | None,
) -> VisualDesignSpec:
    """
    Enforce user constraints over Gemini output.
    USER EXPLICIT CONSTRAINT always has highest priority.
    """
    if design_intent is None or design_intent.is_empty():
        return spec

    p = spec.presentation

    if design_intent.background_color:
        p.background_color = design_intent.background_color
        # Apply to title/section slides
        for s in spec.slides:
            if s.purpose in ("title", "section", "closing"):
                if s.background.type == "solid":
                    s.background.color = design_intent.background_color

    if design_intent.primary_color:
        p.primary_color = design_intent.primary_color

    if design_intent.accent_color:
        p.accent_color = design_intent.accent_color

    if design_intent.font_heading:
        p.heading_font = design_intent.font_heading
        for s in spec.slides:
            s.font_heading = design_intent.font_heading

    if design_intent.font_body:
        p.body_font = design_intent.font_body
        for s in spec.slides:
            s.font_body = design_intent.font_body

    return spec


def _parse_response(
    raw: str,
    plan: PresentationPlan,
    design_intent: DesignIntent | None,
) -> VisualDesignSpec:
    """
    Parse Gemini's raw JSON into a VisualDesignSpec.
    Falls back to safe defaults on any parse error.
    Never raises.
    """
    try:
        # Strip possible markdown fences
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("VisualDesignPlanner: JSON parse failed: %s", exc)
        return _safe_design_spec(plan, design_intent, f"JSON decode: {exc}")

    try:
        spec = VisualDesignSpec.model_validate(data)
    except Exception as exc:
        logger.error("VisualDesignPlanner: schema validation failed: %s", exc)
        # Partial recovery — try to salvage slides
        try:
            presentation_data = data.get("presentation", {})
            direction = PresentationVisualDirection.model_validate(presentation_data)
        except Exception:
            direction = PresentationVisualDirection(style=plan.style)

        slides: list[SlideDesignSpec] = []
        for raw_slide in data.get("slides", []):
            try:
                slides.append(SlideDesignSpec.model_validate(raw_slide))
            except Exception as inner:
                idx = raw_slide.get("slide_index", len(slides))
                logger.warning(
                    "VisualDesignPlanner: dropping malformed slide spec index=%s: %s",
                    idx, inner,
                )

        # Fill missing slides with safe defaults
        existing_indices = {s.slide_index for s in slides}
        for slide in plan.slides:
            if slide.index not in existing_indices:
                logger.info(
                    "VisualDesignPlanner: filling missing slide %d with safe default",
                    slide.index,
                )
                slides.append(_safe_slide_spec(slide, direction))

        slides.sort(key=lambda s: s.slide_index)
        spec = VisualDesignSpec(
            presentation=direction,
            slides=slides,
            generated_by_gemini=True,
            fallback_used=len(slides) < plan.slide_count,
        )

    # Ensure all slides present
    existing_indices = {s.slide_index for s in spec.slides}
    missing = [s for s in plan.slides if s.index not in existing_indices]
    if missing:
        logger.warning(
            "VisualDesignPlanner: %d slide(s) missing from Gemini response, adding defaults",
            len(missing),
        )
        for slide in missing:
            spec.slides.append(_safe_slide_spec(slide, spec.presentation))
        spec.slides.sort(key=lambda s: s.slide_index)
        spec.fallback_used = True

    # Apply user constraints on top (highest priority)
    spec = _apply_user_constraints(spec, design_intent)
    spec.generated_by_gemini = True

    return spec


# ═══════════════════════════════════════════════════════════════════════════
# VisualDesignPlanner
# ═══════════════════════════════════════════════════════════════════════════

class VisualDesignPlanner:
    """
    Calls Gemini as Creative Director to produce a full VisualDesignSpec.

    Unlike DesignIntelligence (which makes Gemini choose pre-defined
    archetypes), this planner makes Gemini design every visual detail:
    coordinates, sizes, colors, fonts, asset prompts, backgrounds.

    Usage::

        planner = VisualDesignPlanner()
        spec = await planner.plan(
            plan=presentation_plan,
            design_intent=intent,   # or None
        )
        # spec.slides[i] contains full per-slide visual specification
        # spec.slides[i].assets contains image generation requests

    Returns
    -------
    VisualDesignSpec — always fully populated, never raises.

    Logging
    -------
    Design specification generated
    Slides planned: N
    Visual assets requested: N
    Fallback used: bool
    """

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.45,
    ) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = model or settings.gemini_model
        self._temperature = temperature

    async def plan(
        self,
        plan: PresentationPlan,
        design_intent: DesignIntent | None = None,
    ) -> VisualDesignSpec:
        """
        Produce a VisualDesignSpec for the given PresentationPlan.

        Parameters
        ----------
        plan          : Validated PresentationPlan (content resolved).
        design_intent : Explicit user design preferences; None = none stated.

        Returns
        -------
        VisualDesignSpec — fully populated, user constraints enforced.
        Never raises.
        """
        user_prompt = _build_user_prompt(plan, design_intent)

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=self._temperature,
        )

        logger.info(
            "VisualDesignPlanner: requesting design for topic=%r  slides=%d",
            plan.topic,
            plan.slide_count,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )
        except Exception as exc:
            logger.error(
                "VisualDesignPlanner: Gemini API call failed for topic=%r: %s",
                plan.topic,
                exc,
            )
            return _safe_design_spec(plan, design_intent, f"API error: {exc}")

        raw: str | None = response.text
        if not raw:
            logger.error(
                "VisualDesignPlanner: empty Gemini response for topic=%r",
                plan.topic,
            )
            return _safe_design_spec(plan, design_intent, "empty Gemini response")

        spec = _parse_response(raw, plan, design_intent)

        # Logging summary
        total_assets = sum(len(s.assets) for s in spec.slides)
        logger.info(
            "VisualDesignPlanner: design specification generated. "
            "Slides planned: %d  Visual assets requested: %d  Fallback used: %s",
            len(spec.slides),
            total_assets,
            spec.fallback_used,
        )

        return spec

    def plan_sync(
        self,
        plan: PresentationPlan,
        design_intent: DesignIntent | None = None,
    ) -> VisualDesignSpec:
        """
        Synchronous wrapper around plan().

        Use only in tests or scripts — not in the async bot pipeline.
        """
        import asyncio
        return asyncio.run(self.plan(plan, design_intent=design_intent))
