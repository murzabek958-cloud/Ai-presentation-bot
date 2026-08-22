"""
ImageIntent — structured image intent model.

Extends the existing AI/Pydantic architecture.
AI expresses INTENT only — never coordinates (x, y, width, height).
The renderer converts intent into layout.

Wikipedia/Wikimedia search has been removed; Gemini is the sole
image source.  build_search_query() is kept for backwards compatibility
but now just delegates to build_cache_key().
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VisualType(str, Enum):
    """What kind of visual is requested."""
    PHOTO        = "photo"
    DIAGRAM      = "diagram"
    ILLUSTRATION = "illustration"
    MAP          = "map"
    SATELLITE    = "satellite"
    HISTORICAL   = "historical"
    CONCEPTUAL   = "conceptual"


class ImageRole(str, Enum):
    """How the image serves the slide."""
    HERO        = "hero"        # Dominant visual — title slides
    SUPPORTING  = "supporting"  # Helps explain — beside text
    BACKGROUND  = "background"  # Behind text with overlay
    CARD        = "card"        # Small decorative element


class ImagePosition(str, Enum):
    """Preferred image placement hint (renderer may override)."""
    LEFT       = "left"
    RIGHT      = "right"
    FULL       = "full"
    BACKGROUND = "background"


class AspectRatio(str, Enum):
    """Preferred aspect ratio."""
    WIDE      = "16:9"
    STANDARD  = "4:3"
    SQUARE    = "1:1"
    PORTRAIT  = "portrait"


class ImageIntent(BaseModel):
    """
    Structured image intent for a slide.

    The AI sets ``needed=True`` only when an image materially improves
    communication — not for every slide.

    IMPORTANT:
    - AI NEVER sets coordinates or pixel dimensions.
    - The renderer converts intent → concrete layout.
    """
    needed: bool = Field(
        default=False,
        description="True only when an image genuinely aids understanding.",
    )
    visual_type: VisualType = Field(
        default=VisualType.PHOTO,
        description="Kind of visual that would work best.",
    )
    subject: str = Field(
        default="",
        description="Specific generation subject.",
    )
    role: ImageRole = Field(
        default=ImageRole.SUPPORTING,
        description="How the image serves the slide layout.",
    )
    preferred_position: ImagePosition = Field(
        default=ImagePosition.RIGHT,
        description="Preferred placement hint — renderer may override.",
    )
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.WIDE,
        description="Preferred aspect ratio for the image.",
    )

    @classmethod
    def not_needed(cls) -> "ImageIntent":
        """Factory: image not needed for this slide."""
        return cls(needed=False)

    @classmethod
    def from_query(
        cls,
        query: str,
        visual_type: VisualType = VisualType.PHOTO,
        role: ImageRole = ImageRole.SUPPORTING,
        position: ImagePosition = ImagePosition.RIGHT,
    ) -> "ImageIntent":
        """Factory: build intent from a free-text query string."""
        return cls(
            needed=bool(query and query.strip()),
            visual_type=visual_type,
            subject=query.strip() if query else "",
            role=role,
            preferred_position=position,
        )

    # ------------------------------------------------------------------
    # Cache key (stable identifier for this generation request)
    # ------------------------------------------------------------------

    def build_cache_key(self, topic: str = "") -> str:
        """
        Return a stable, human-readable cache key for this intent.

        The key is derived from the subject + visual_type so that the
        same conceptual request always maps to the same cached image.
        """
        if not self.needed or not self.subject:
            return ""

        base = self.subject.strip()

        # Append visual-type hint for cache differentiation
        type_hints: dict[VisualType, str] = {
            VisualType.DIAGRAM:      "diagram",
            VisualType.MAP:          "map",
            VisualType.SATELLITE:    "satellite image",
            VisualType.HISTORICAL:   "historical photograph",
            VisualType.ILLUSTRATION: "illustration",
            VisualType.CONCEPTUAL:   "concept",
            VisualType.PHOTO:        "",
        }
        hint = type_hints.get(self.visual_type, "")
        if hint and hint.lower() not in base.lower():
            return f"{base} {hint}".strip()
        return base

    # Backwards-compat alias used by older code / tests
    def build_search_query(self, topic: str = "") -> str:
        """
        Alias for build_cache_key().

        Previously this built a Wikimedia search query.
        Now it just returns the stable cache key.
        Kept for backwards compatibility with existing callers.
        """
        return self.build_cache_key(topic)

    # ------------------------------------------------------------------
    # Gemini image-generation prompt
    # ------------------------------------------------------------------

    def build_generation_prompt(self) -> str:
        """
        Return a Gemini image-generation prompt.

        Requirements enforced:
        - Clean, presentation-friendly composition
        - Appropriate aspect ratio
        - High resolution appearance
        - Subject clearly visible
        - No unnecessary text, watermarks, UI, random labels
        - Composition suitable for intended placement
        - Relevant to slide topic (historical, scientific, technical, etc.)
        """
        if not self.needed or not self.subject:
            return ""

        role_hints: dict[ImageRole, str] = {
            ImageRole.HERO:       "full-width hero image, dramatic composition",
            ImageRole.SUPPORTING: "clean supporting visual, subject clearly centered",
            ImageRole.BACKGROUND: "subtle background texture, low contrast, no dominant elements",
            ImageRole.CARD:       "compact square illustration, high contrast",
        }
        type_hints: dict[VisualType, str] = {
            VisualType.PHOTO:        "realistic photograph",
            VisualType.DIAGRAM:      "clean scientific diagram, white background, clear labels",
            VisualType.MAP:          "clean map, minimal text",
            VisualType.SATELLITE:    "satellite or aerial view",
            VisualType.HISTORICAL:   "historical photograph, authentic look",
            VisualType.ILLUSTRATION: "clean digital illustration",
            VisualType.CONCEPTUAL:   "abstract conceptual artwork",
        }
        ratio_hints: dict[AspectRatio, str] = {
            AspectRatio.WIDE:     "wide 16:9 landscape format",
            AspectRatio.STANDARD: "4:3 landscape format",
            AspectRatio.SQUARE:   "square 1:1 format",
            AspectRatio.PORTRAIT: "portrait format",
        }

        parts = [
            f"{type_hints.get(self.visual_type, 'photograph')} of {self.subject}",
            role_hints.get(self.role, "clean composition"),
            ratio_hints.get(self.aspect_ratio, "landscape format"),
            "high resolution, professional quality",
            "no watermark, no UI elements, no decorative borders",
            "no unnecessary text overlays",
            "suitable for an academic presentation slide",
        ]
        return ". ".join(parts) + "."
