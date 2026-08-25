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
    margin_outer: float = 0.45          # Outer slide margin
    margin_top_content: float = 1.45    # Top of content area (below title)

    # --- Spacing ---
    gap_card: float = 0.22              # Gap between cards
    gap_section: float = 0.35          # Gap between sections
    gap_title_rule: float = 0.08       # Space between title and rule line
    gap_rule_content: float = 0.18     # Space between rule and content area
    gap_text: float = 0.14             # Space between text blocks

    # --- Title area ---
    title_height: float = 0.95         # Title textbox height
    title_rule_height: float = 0.035   # Decorative rule thickness
    title_font_size: int = 30          # Standard slide title size (pt)
    subtitle_font_size: int = 22       # Subtitle / hero subtitle
    author_font_size: int = 14         # Author / caption

    # --- Body typography ---
    body_font_large: int = 21          # Large body text
    body_font_normal: int = 18         # Standard body text
    body_font_small: int = 15          # Supporting / dense text
    caption_font_size: int = 12        # Source / footnote

    # --- Metric / hero typography ---
    metric_font_huge: int = 68         # Hero single stat
    metric_font_large: int = 48        # Multi-stat cards
    metric_font_medium: int = 36       # Horizontal metric rows
    metric_label_size: int = 16        # Label under metric

    # --- Heading hierarchy ---
    heading_hero: int = 44             # Title slide main heading
    heading_large: int = 36            # Section statement
    heading_normal: int = 28           # Card / column heading
    heading_small: int = 20            # Tag / label heading

    # --- Card internals ---
    card_pad_x: float = 0.22          # Card horizontal padding
    card_pad_y: float = 0.25          # Card vertical padding
    card_header_h: float = 0.52       # Card label/header strip height

    # --- Accent stripe ---
    accent_stripe_w: float = 0.18     # Side accent stripe width
    accent_stripe_thin: float = 0.04  # Thin horizontal rule

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


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

ACADEMIC = Theme(
    name="academic",
    primary="#1B3A6B",       # Deep navy — authority and trust
    secondary="#2E5FA3",     # Mid-blue for subheadings
    accent="#C8922A",        # Warm gold for highlights
    background="#FFFFFF",    # White — clean reading surface
    text_dark="#1A1A1A",     # Near-black body text
    text_light="#F5F5F5",    # Light text on dark slides
    font_heading="Cambria",
    font_body="Calibri",
)

MODERN = Theme(
    name="modern",
    primary="#0F172A",       # Slate-900 — strong dark base
    secondary="#6366F1",     # Indigo — tech/startup feel
    accent="#22D3EE",        # Cyan — energetic highlight
    background="#F8FAFC",    # Near-white with cool tint
    text_dark="#0F172A",     # Slate-900 body text
    text_light="#F8FAFC",    # Light text on dark slides
    font_heading="Arial",
    font_body="Arial",
)

MINIMAL = Theme(
    name="minimal",
    primary="#111111",       # Almost-black — max contrast
    secondary="#555555",     # Mid-grey for secondary info
    accent="#111111",        # No separate accent — same as primary
    background="#FFFFFF",    # Pure white — maximum whitespace
    text_dark="#111111",     # Near-black
    text_light="#FFFFFF",    # White text on dark elements
    font_heading="Georgia",
    font_body="Georgia",
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_THEMES: dict[str, Theme] = {
    t.name: t for t in (ACADEMIC, MODERN, MINIMAL)
}


def get_theme(name: str) -> Theme:
    """Return the Theme for *name*. Raises ValueError for unknown names."""
    try:
        return _THEMES[name]
    except KeyError:
        available = ", ".join(_THEMES)
        raise ValueError(
            f"Unknown theme '{name}'. Available themes: {available}"
        )


def list_themes() -> list[str]:
    """Return all registered theme names."""
    return list(_THEMES)
