"""
ai/design_intelligence.py
────────────────────────────────────────────────────────────────────────────
Gemini Design Intelligence — the art director layer.

Role in the pipeline
--------------------
    PresentationPlan (content)
    DesignIntent     (explicit user preferences)
              ↓
    DesignIntelligence.analyse()
              ↓
    PresentationDesignPlan   (validated composition directives)
              ↓
    CompositionSelector / Renderer
              ↓
    PPTXBuilder

Responsibility
--------------
This module is ONLY responsible for calling Gemini with a rich design
prompt and returning a validated PresentationDesignPlan.  It does NOT:
- render PPTX
- manipulate python-pptx objects
- download or process images
- modify any schema outside this file's return type
- change the renderer, builder, or handlers

Gemini's role
-------------
Gemini acts as a professional presentation art director.  It receives:
  • presentation topic and style
  • explicit DesignIntent (user color/font preferences)
  • per-slide content summary and layout type
  • image availability flags

Gemini returns one SlideDesignDirective per slide inside a
PresentationDesignPlan JSON.  The schema is enforced at the Gemini SDK
level when possible, and validated again by validate_design_plan() before
any downstream code sees it.

Fallback guarantee
------------------
If Gemini fails (API error, malformed JSON, schema violation) the method
returns a fully-defaulted PresentationDesignPlan — every slide gets a safe
default directive.  The pipeline never crashes due to a design intelligence
failure.

Temperature
-----------
0.4 — lower than the content planner (0.7) because design decisions should
be intentional and repeatable, not creative in the prose sense.  Enough
variation to produce diverse compositions across slides, but deterministic
enough for consistent quality.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from config.settings import settings
from ai.design_intent import DesignIntent
from ai.schemas import PresentationPlan, SlideData, SlideLayout
from ai.slide_design_schema import (
    AccentPosition,
    AccentShape,
    ImagePosition,
    ImageTreatment,
    LayoutArchetype,
    PresentationDesignPlan,
    SlideDesignDirective,
    SpacingDensity,
    TextAlignment,
    _COMPATIBLE_ARCHETYPES,
    safe_default_directive,
    validate_design_plan,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Internal prompt construction
# ═══════════════════════════════════════════════════════════════════════════

# ── Archetype reference for the prompt ───────────────────────────────────
# Groups compatible archetypes by SlideLayout so the prompt is compact and
# Gemini only sees valid options for each layout type.

_LAYOUT_ARCHETYPE_GUIDE: dict[str, list[str]] = {
    layout.value: sorted(arch.value for arch in archs)
    for layout, archs in _COMPATIBLE_ARCHETYPES.items()
}

_ARCHETYPE_DESCRIPTIONS: dict[str, str] = {
    # Title
    "hero":                   "Centred large title on solid colour background. Authoritative, clean.",
    "hero_split":             "Title/text on left, full-height image on right. Dynamic, editorial.",
    "hero_image_overlay":     "Full-bleed photo with dark overlay, title on top. Cinematic, immersive.",
    # Section
    "section_divider":        "Large section number + label. Creates visual breathing room.",
    # Single-column content
    "title_text":             "Heading + flowing body paragraph. Clear, readable, informative.",
    "title_bullets":          "Heading + concise bullet list. Structured, easy to scan.",
    "large_statement":        "One oversized statement sentence. Impactful, minimal.",
    "editorial":              "Heading left, body right in two unequal zones. Magazine-quality.",
    # Two columns
    "two_columns_equal":      "Symmetric 50/50 columns. Balanced, neutral.",
    "two_columns_asymmetric": "40/60 split — narrower column for context, wider for content.",
    "card_duo":               "Two rounded dark cards with icon and text. Bold, modern.",
    "icon_columns":           "Icon above each column. Visual, friendly, infographic.",
    # Image + text
    "image_left_text_right":  "Image occupies left half, text right. Natural Western reading flow.",
    "image_right_text_left":  "Text left, image right. Less conventional, adds visual interest.",
    "full_bleed":             "Photo fills entire slide, caption box overlaid. Atmospheric.",
    "image_sidebar":          "Narrow image strip on one side, wide text area. Subtle visual anchor.",
    # Data
    "three_cards":            "Three metric/stat cards in a row. Best for 3 KPIs.",
    "four_cards":             "2×2 grid of metric cards. Best for 4 KPIs.",
    "big_number":             "One giant metric dominates the slide. Maximum impact.",
    "horizontal_metrics":     "Metrics laid out in a horizontal band. Compact comparison.",
    "chart_focus":            "Chart centred with label below. Data-first composition.",
    # Structured
    "timeline_horizontal":    "Events along a horizontal axis. Chronological flow.",
    "timeline_vertical":      "Events stacked vertically. Good for more than 5 events.",
    "process_steps":          "Numbered circular steps 1→2→3→4. Process/methodology.",
    "comparison_split":       "Left vs right with distinct labels. Direct contrast.",
    "comparison_table":       "Feature × option matrix. Detailed multi-point comparison.",
    "agenda":                 "Numbered table of contents. Use only for agenda/TOC slides.",
    # Quote
    "quote_centered":         "Large centred quotation. Clean, classical.",
    "quote_side":             "Quote with attribution on the side. Asymmetric elegance.",
    "large_typography":       "Oversized type fills the slide. Typography as design.",
    # Closing
    "closing":                "Summary headline + call-to-action. Forward-looking.",
    "minimal_final":          "Just the topic line on a clean background. Understated close.",
}

_SYSTEM_PROMPT = """\
You are a professional presentation art director.

Your task is to produce a visual design plan for a slide presentation.
You do NOT write slide content — only design directives.

You must return a JSON object matching this exact schema:

{
  "directives": [
    {
      "slide_index": <integer>,
      "archetype": <string — one of the allowed archetypes for this layout>,
      "image_treatment": <"none"|"natural"|"dark_overlay"|"light_overlay"|"greyscale"|"blurred"|"full_height">,
      "image_position": <"none"|"left"|"right"|"top"|"bottom"|"full"|"inset">,
      "text_alignment": <"left"|"center"|"right">,
      "title_width_ratio": <float 0.2–1.0 or null>,
      "accent_shape": <"none"|"line_bottom"|"line_left"|"line_right"|"dot_grid"|"corner_bracket"|"full_side_bar">,
      "accent_position": <"none"|"title_bottom"|"slide_left"|"slide_right"|"slide_top"|"slide_bottom">,
      "spacing": <"spacious"|"normal"|"dense">,
      "background_override": <"#RRGGBB" or null>,
      "notes": <string — your brief rationale>
    }
  ],
  "global_font_heading": <string or null>,
  "global_font_body": <string or null>,
  "global_spacing": <"spacious"|"normal"|"dense">,
  "design_rationale": <string — overall design direction in 2–3 sentences>
}

DESIGN PRINCIPLES:

1. Visual hierarchy first.
   Every slide must have one dominant element (title, image, or metric) and
   one or two supporting elements.  Never treat all elements as equal.

2. Slide-to-slide variation.
   A 10-slide presentation should never have more than 3 consecutive slides
   with the same archetype.  Vary composition to create visual rhythm.

3. Image intent.
   If a slide has an image_query, you MUST set image_position to something
   other than "none" and choose an appropriate image_treatment.
   If there is no image, set image_position to "none" and
   image_treatment to "none".

4. Text legibility is non-negotiable.
   If you use "dark_overlay" or "full_bleed", ensure text_alignment and
   title_width_ratio leave enough reading space.

5. Spacing follows content density.
   Slides with few words (quote, title, big_number) → "spacious".
   Slides with many items (timeline, statistics) → "normal" or "dense".

6. Accent discipline.
   Use accent elements purposefully — not on every slide.
   Reserve "full_side_bar" and "dot_grid" for title/section slides only.

7. Honour explicit user design instructions.
   If the user specified a background colour, propagate it via
   background_override on the title slide and section dividers.
   Do NOT override it with a topic-derived colour.

8. Use ONLY the archetypes listed for each layout.
   Never invent new archetype names.

9. Return ONLY valid JSON. No markdown, no prose, no code fences.
"""


def _build_user_prompt(
    plan: PresentationPlan,
    design_intent: DesignIntent | None,
    image_index: set[int],
) -> str:
    """
    Build the user-turn prompt sent to Gemini Design Intelligence.

    Parameters
    ----------
    plan          : The PresentationPlan (content already resolved).
    design_intent : Optional explicit user design preferences.
    image_index   : Set of slide indices that have a resolved image available.
    """
    lines: list[str] = []

    # ── Presentation context ──────────────────────────────────────────────
    lines.append("PRESENTATION:")
    lines.append(f"  Topic: {plan.topic}")
    lines.append(f"  Style: {plan.style}")
    lines.append(f"  Slide count: {plan.slide_count}")
    lines.append(f"  Language: {plan.metadata.language}")
    lines.append("")

    # ── Explicit user design instructions ─────────────────────────────────
    if design_intent is not None and not design_intent.is_empty():
        lines.append("EXPLICIT USER DESIGN INSTRUCTIONS (highest priority):")
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
        lines.append(
            "  NOTE: These MUST be respected. Do not override with topic defaults."
        )
        lines.append("")

    # ── Archetype reference (compact) ─────────────────────────────────────
    lines.append("ALLOWED ARCHETYPES PER LAYOUT:")
    for layout_val, archs in _LAYOUT_ARCHETYPE_GUIDE.items():
        arch_list = ", ".join(archs)
        lines.append(f"  {layout_val}: [{arch_list}]")
    lines.append("")

    # ── Per-slide data ────────────────────────────────────────────────────
    lines.append("SLIDES:")
    for slide in plan.slides:
        has_image = slide.index in image_index
        content_summary = _summarise_content(slide)

        lines.append(f"  [{slide.index}] layout={slide.layout.value}")
        lines.append(f"      title: {slide.title}")
        lines.append(f"      content: {content_summary}")
        lines.append(f"      has_image: {has_image}")
        lines.append(f"      allowed_archetypes: {_LAYOUT_ARCHETYPE_GUIDE.get(slide.layout.value, [])}")
        lines.append("")

    # ── Final instruction ─────────────────────────────────────────────────
    lines.append(
        "Return ONE SlideDesignDirective per slide (all "
        f"{plan.slide_count} slides)."
    )
    lines.append("Return ONLY the JSON object. No markdown. No prose.")

    return "\n".join(lines)


def _summarise_content(slide: SlideData) -> str:
    """
    Return a short string describing slide content for the design prompt.

    Gemini does not need full content — it needs enough to judge complexity,
    image-relevance, and appropriate density.
    """
    c = slide.content

    if slide.layout == SlideLayout.STATISTICS:
        stats = c.get("stats", [])
        return f"{len(stats)} stat(s): {', '.join(s.get('label', '') for s in stats[:3])}"

    if slide.layout == SlideLayout.TIMELINE:
        events = c.get("events", [])
        return f"{len(events)} event(s)"

    if slide.layout == SlideLayout.COMPARISON:
        return (
            f"left={c.get('left_label', '')} vs right={c.get('right_label', '')}"
        )

    if slide.layout == SlideLayout.TWO_COLUMNS:
        lt = c.get("left_title", "")
        rt = c.get("right_title", "")
        return f"left='{lt}' / right='{rt}'"

    if slide.layout == SlideLayout.QUOTE:
        q = c.get("quote", "")
        return f"quote: {q[:60]}…" if len(q) > 60 else f"quote: {q}"

    if slide.layout == SlideLayout.AGENDA:
        items = c.get("items", [])
        return f"{len(items)} agenda item(s)"

    if slide.layout == SlideLayout.CHART:
        return f"chart_type={c.get('chart_type', '?')}"

    if slide.layout == SlideLayout.CONCLUSION:
        summary = c.get("summary", "")
        return summary[:60] + "…" if len(summary) > 60 else summary

    # TITLE, TITLE_TEXT, IMAGE_TEXT
    body = c.get("body", c.get("subtitle", ""))
    return body[:60] + "…" if len(body) > 60 else body


# ═══════════════════════════════════════════════════════════════════════════
# Parsing helpers
# ═══════════════════════════════════════════════════════════════════════════

def _full_default_plan(
    plan: PresentationPlan,
    reason: str,
) -> PresentationDesignPlan:
    """
    Build a fully-defaulted PresentationDesignPlan as the ultimate fallback.

    Called when Gemini is unavailable or returns unrecoverable output.
    """
    logger.warning("DesignIntelligence: using full safe defaults. Reason: %s", reason)
    layout_map = {s.index: s.layout for s in plan.slides}
    empty = PresentationDesignPlan(directives=[])
    validated, _ = validate_design_plan(empty, layout_map)
    return validated


def _parse_response(
    raw: str,
    plan: PresentationPlan,
) -> PresentationDesignPlan:
    """
    Parse Gemini raw JSON text into a validated PresentationDesignPlan.

    Two-stage approach:
    1. json.loads() → manual construction into Pydantic models.
    2. validate_design_plan() for archetype compatibility + missing slides.

    Any exception falls back to safe defaults — never raises.
    """
    layout_map = {s.index: s.layout for s in plan.slides}

    try:
        data: dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("DesignIntelligence: JSON parse failed: %s", exc)
        return _full_default_plan(plan, f"JSON decode error: {exc}")

    try:
        design_plan = PresentationDesignPlan.model_validate(data)
    except Exception as exc:
        logger.error(
            "DesignIntelligence: PresentationDesignPlan validation failed: %s", exc
        )
        # Attempt partial recovery: parse directives one-by-one
        directives: list[SlideDesignDirective] = []
        for raw_d in data.get("directives", []):
            try:
                directives.append(SlideDesignDirective.model_validate(raw_d))
            except Exception as inner:
                logger.warning(
                    "DesignIntelligence: dropping malformed directive "
                    "slide_index=%s: %s",
                    raw_d.get("slide_index", "?"),
                    inner,
                )
        design_plan = PresentationDesignPlan(
            directives=directives,
            global_font_heading=data.get("global_font_heading"),
            global_font_body=data.get("global_font_body"),
            global_spacing=SpacingDensity(
                data.get("global_spacing", SpacingDensity.NORMAL.value)
            ),
            design_rationale=data.get("design_rationale", ""),
        )

    validated, result = validate_design_plan(design_plan, layout_map)

    if result.missing_slides:
        logger.info(
            "DesignIntelligence: %d slide(s) had no directive from Gemini "
            "and received safe defaults: %s",
            len(result.missing_slides),
            result.missing_slides,
        )

    logger.info(
        "DesignIntelligence: validation passed=%s, "
        "%d directives, %d fixed, %d missing.",
        result.passed,
        len(validated.directives),
        sum(1 for r in result.slide_results if r.archetype_fixed),
        len(result.missing_slides),
    )

    return validated


# ═══════════════════════════════════════════════════════════════════════════
# DesignIntelligence
# ═══════════════════════════════════════════════════════════════════════════

class DesignIntelligenceError(Exception):
    """Raised only for configuration problems (e.g. missing API key)."""


class DesignIntelligence:
    """
    Calls Gemini as a presentation art director and returns a validated
    PresentationDesignPlan.

    Usage::

        di = DesignIntelligence()
        design_plan = await di.analyse(
            plan=presentation_plan,
            design_intent=intent,       # or None
            image_index={2, 5},         # slide indices with resolved images
        )

    The returned PresentationDesignPlan is always fully validated —
    every slide has a directive with a compatible archetype.

    Parameters (constructor)
    ------------------------
    model : str | None
        Gemini model name.  Defaults to settings.gemini_model.
        Override in tests to use a cheaper/faster model.
    temperature : float
        Gemini temperature.  0.4 by default — intentional but varied.
    """

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.4,
    ) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = model or settings.gemini_model
        self._temperature = temperature

    async def analyse(
        self,
        plan: PresentationPlan,
        design_intent: DesignIntent | None = None,
        image_index: set[int] | None = None,
    ) -> PresentationDesignPlan:
        """
        Produce a PresentationDesignPlan for *plan*.

        Parameters
        ----------
        plan          : Validated PresentationPlan (content already resolved).
        design_intent : Explicit user design preferences; None = none stated.
        image_index   : Set of slide indices for which an image is available.
                        Used so Gemini knows which slides have real images.
                        Defaults to the set of IMAGE_TEXT slide indices.

        Returns
        -------
        PresentationDesignPlan — always fully validated, never raises.
        """
        # Default image_index: slides that have an image_query
        if image_index is None:
            image_index = {
                s.index for s in plan.slides
                if s.image_query is not None
            }

        user_prompt = _build_user_prompt(plan, design_intent, image_index)

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=self._temperature,
        )

        # ── Gemini API call ───────────────────────────────────────────────
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )
        except Exception as exc:
            logger.error(
                "DesignIntelligence: Gemini API call failed for topic=%r: %s",
                plan.topic,
                exc,
            )
            return _full_default_plan(plan, f"API error: {exc}")

        # ── Extract raw text ──────────────────────────────────────────────
        # Prefer response.parsed (SDK-validated) when available.
        # Fall back to response.text (raw JSON string).
        raw: str | None = None

        if response.parsed is not None:
            # SDK already validated — wrap in our schema
            try:
                design_plan = PresentationDesignPlan.model_validate(
                    response.parsed
                    if isinstance(response.parsed, dict)
                    else response.parsed.model_dump()
                )
                layout_map = {s.index: s.layout for s in plan.slides}
                validated, result = validate_design_plan(design_plan, layout_map)
                logger.info(
                    "DesignIntelligence: SDK-parsed response, "
                    "validation passed=%s topic=%r",
                    result.passed,
                    plan.topic,
                )
                return validated
            except Exception as exc:
                logger.warning(
                    "DesignIntelligence: SDK-parsed object failed re-validation: %s "
                    "— falling back to raw text",
                    exc,
                )
                raw = response.text
        else:
            raw = response.text

        if not raw:
            logger.error(
                "DesignIntelligence: Gemini returned empty response for topic=%r",
                plan.topic,
            )
            return _full_default_plan(plan, "empty Gemini response")

        return _parse_response(raw, plan)

    # ── Synchronous convenience wrapper (for tests / non-async callers) ───

    def analyse_sync(
        self,
        plan: PresentationPlan,
        design_intent: DesignIntent | None = None,
        image_index: set[int] | None = None,
    ) -> PresentationDesignPlan:
        """
        Synchronous wrapper around analyse().  Creates a temporary event loop.

        Use only in tests or scripts — not in the async bot pipeline.
        """
        import asyncio
        return asyncio.run(
            self.analyse(plan, design_intent=design_intent, image_index=image_index)
        )
