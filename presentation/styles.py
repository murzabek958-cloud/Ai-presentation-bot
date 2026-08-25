from dataclasses import dataclass
from pydantic import BaseModel


class Theme(BaseModel, frozen=True):
    name: str

    # Core palette
    primary: str      # Main brand / header color
    secondary: str    # Supporting color
    accent: str       # Highlight / call-to-action
    background: str   # Slide background
    text_dark: str    # Primary text
    text_light: str   # Text on dark backgrounds

    # Typography
    font_heading: str
    font_body: str


# ---------------------------------------------------------------------------
# Design Tokens — spacing, typography, colors used in builder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DesignTokens:
    """
    Reusable design tokens for consistent layout across all slides.
    All measurements are in inches (for use with pptx Inches()).
    """

    # --- Page structure ---
    margin_outer: float = 0.45
    margin_top_content: float = 1.45

    # --- Spacing ---
    gap_card: float = 0.22
    gap_section: float = 0.35
    gap_title_rule: float = 0.08
    gap_rule_content: float = 0.18
    gap_text: float = 0.14

    # --- Title area ---
    title_height: float = 0.95
    title_rule_height: float = 0.035
    title_font_size: int = 30
    subtitle_font_size: int = 22
    author_font_size: int = 14

    # --- Body typography ---
    body_font_large: int = 21
    body_font_normal: int = 18
    body_font_small: int = 15
    caption_font_size: int = 12

    # --- Metric / hero typography ---
    metric_font_huge: int = 68
    metric_font_large: int = 48
    metric_font_medium: int = 36
    metric_label_size: int = 16

    # --- Heading hierarchy ---
    heading_hero: int = 44
    heading_large: int = 36
    heading_normal: int = 28
    heading_small: int = 20

    # --- Card internals ---
    card_pad_x: float = 0.22
    card_pad_y: float = 0.25
    card_header_h: float = 0.52

    # --- Accent stripe ---
    accent_stripe_w: float = 0.18
    accent_stripe_thin: float = 0.04

    # --- Computed helpers ---
    @property
    def content_width(self) -> float:
        """Usable content width (slide 13.33in - 2 × outer margin)."""
        return 13.33 - 2 * self.margin_outer

    @property
    def content_start_y(self) -> float:
        """Y of content area start (title_height + rule + gap)."""
        return self.margin_top_content + self.title_rule_height + self.gap_rule_content


# Singleton tokens — import and use directly
TOKENS = DesignTokens()
