"""
presentation/theme_selector.py
───────────────────────────────────────────────────────────────────────────────
Topic-aware theme / palette selection engine.

Architecture
────────────
CONTENT (topic string)
  → TopicClassifier.classify()  →  TopicProfile  (weighted semantic categories)
  → PaletteLibrary.select()     →  Palette       (semantic color roles)
  → palette_to_theme()          →  Theme         (existing API — no changes)

The layout/renderer layer is untouched; it continues using theme.primary,
theme.accent, etc.  Only the *values* of those roles change per topic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

from presentation.styles import Theme


# ═══════════════════════════════════════════════════════════════════════════
# 1.  PALETTE  — semantic color roles, independent of layout
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Palette:
    """
    A complete, presentation-safe color palette expressed as semantic roles.
    All values are hex strings ('#RRGGBB').
    """
    name: str

    # Surface
    background: str     # Slide background
    surface: str        # Card / panel surface (slightly different from bg)

    # Text
    text_primary: str   # Main body text on background
    text_secondary: str # Subdued / secondary text
    text_on_dark: str   # Text that sits on primary / dark panels

    # Brand
    primary: str        # Headers, dark panels, dominant brand colour
    accent: str         # Highlights, rules, CTA buttons
    border: str         # Subtle dividers, card borders

    # Semantic
    success: str        # Positive indicator
    warning: str        # Caution indicator

    def __post_init__(self) -> None:
        required = [
            "background", "surface", "text_primary", "text_secondary",
            "text_on_dark", "primary", "accent", "border", "success", "warning",
        ]
        for role in required:
            val = getattr(self, role)
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", val):
                raise ValueError(f"Palette '{self.name}': {role}={val!r} is not a valid hex color")


# ═══════════════════════════════════════════════════════════════════════════
# 2.  PALETTE LIBRARY  — 12 original, curated palettes
# ═══════════════════════════════════════════════════════════════════════════

_PALETTES: dict[str, Palette] = {}


def _reg(p: Palette) -> Palette:
    _PALETTES[p.name] = p
    return p


# ── Nature / ecology ──────────────────────────────────────────────────────
PALETTE_NATURE = _reg(Palette(
    name="nature",
    background="#F7FAF3",   # Very light sage white
    surface="#EAF2E3",      # Pale leaf green
    text_primary="#1C2B18", # Deep forest green
    text_secondary="#4A6741",
    text_on_dark="#F0F7EC",
    primary="#2D5A27",      # Forest green
    accent="#7BBD4E",       # Fresh leaf accent
    border="#B5D4A0",
    success="#3A8F3A",
    warning="#C8922A",
))

# ── Ocean / water ─────────────────────────────────────────────────────────
PALETTE_OCEAN = _reg(Palette(
    name="ocean",
    background="#F2F8FC",
    surface="#DFF0F8",
    text_primary="#0D2B3E",
    text_secondary="#2E6080",
    text_on_dark="#E8F4FB",
    primary="#1A5276",      # Deep ocean blue
    accent="#1ABCBF",       # Teal/turquoise
    border="#85C1E9",
    success="#27AE8F",
    warning="#E5A826",
))

# ── Medicine / anatomy / healthcare ───────────────────────────────────────
PALETTE_MEDICINE = _reg(Palette(
    name="medicine",
    background="#F5F9FC",
    surface="#EAF3F8",
    text_primary="#0E1E2B",
    text_secondary="#2C5F7A",
    text_on_dark="#EEF5FA",
    primary="#1A4A6E",      # Clinical blue
    accent="#2698C4",       # Bright clinical teal
    border="#A8D4E8",
    success="#2DAF82",
    warning="#C0392B",      # Restrained red — medical alert
))

# ── Technology / AI / cybersecurity ───────────────────────────────────────
PALETTE_TECH = _reg(Palette(
    name="technology",
    background="#F6F8FA",
    surface="#EAECF4",
    text_primary="#0D1117",
    text_secondary="#4A5568",
    text_on_dark="#E8ECF5",
    primary="#1A1F5E",      # Deep indigo-navy
    accent="#4F8EF7",       # Electric blue
    border="#9BAEDD",
    success="#22C55E",
    warning="#F59E0B",
))

# ── Finance / economics ───────────────────────────────────────────────────
PALETTE_FINANCE = _reg(Palette(
    name="finance",
    background="#F8F9FA",
    surface="#EEF0F2",
    text_primary="#0F1923",
    text_secondary="#3D5166",
    text_on_dark="#F0F4F8",
    primary="#14304D",      # Banker navy
    accent="#2E7D52",       # Stable green
    border="#9DB8C8",
    success="#1E8449",
    warning="#B7950B",
))

# ── History / culture / art ───────────────────────────────────────────────
PALETTE_HISTORY = _reg(Palette(
    name="history",
    background="#FAF6F0",   # Warm parchment
    surface="#F2EBE0",
    text_primary="#2C1810",
    text_secondary="#7A5C45",
    text_on_dark="#F9F4EC",
    primary="#6B2D1F",      # Burgundy-earth
    accent="#C8892A",       # Antique gold
    border="#D4B896",
    success="#4A7A3A",
    warning="#B85C1A",
))

# ── Space / astronomy ─────────────────────────────────────────────────────
PALETTE_SPACE = _reg(Palette(
    name="space",
    background="#F0F2F8",
    surface="#E2E6F2",
    text_primary="#0B0F2E",
    text_secondary="#3A4070",
    text_on_dark="#E8ECFF",
    primary="#0B1354",      # Deep cosmos navy
    accent="#7C6AF7",       # Nebula violet
    border="#8A96D4",
    success="#2AB8A0",
    warning="#E8AE3A",
))

# ── Education / learning ──────────────────────────────────────────────────
PALETTE_EDUCATION = _reg(Palette(
    name="education",
    background="#F5F6FF",
    surface="#EBEDFc",
    text_primary="#12163A",
    text_secondary="#404880",
    text_on_dark="#ECEEFF",
    primary="#2B3794",      # Scholarly deep blue
    accent="#8B5CF6",       # Purple highlight
    border="#A5ACE0",
    success="#22A86E",
    warning="#F5A623",
))

# ── Business / corporate ──────────────────────────────────────────────────
PALETTE_BUSINESS = _reg(Palette(
    name="business",
    background="#F8F8FA",
    surface="#EDEDF2",
    text_primary="#0F1520",
    text_secondary="#445566",
    text_on_dark="#F0F2F5",
    primary="#1C2B45",      # Corporate navy
    accent="#3B82C4",       # Professional blue
    border="#9AAABB",
    success="#2E7D4F",
    warning="#C47A1A",
))

# ── Agriculture / farming ─────────────────────────────────────────────────
PALETTE_AGRICULTURE = _reg(Palette(
    name="agriculture",
    background="#F6F9F0",
    surface="#EAF0E0",
    text_primary="#1A2A10",
    text_secondary="#4A6530",
    text_on_dark="#EFF5E8",
    primary="#3A5E1F",      # Field green
    accent="#C8922A",       # Harvest gold
    border="#AACE88",
    success="#4CAF50",
    warning="#E07B20",
))

# ── Ocean + Ecology blend ─────────────────────────────────────────────────
PALETTE_OCEAN_ECOLOGY = _reg(Palette(
    name="ocean_ecology",
    background="#F2F9F6",
    surface="#DFF2EC",
    text_primary="#0D2B25",
    text_secondary="#2A6B5A",
    text_on_dark="#E6F5F0",
    primary="#1A5C50",      # Deep teal
    accent="#2EC4B6",       # Vivid teal-green
    border="#80CCB8",
    success="#27A87A",
    warning="#E5A826",
))

# ── Medicine + Science blend ──────────────────────────────────────────────
PALETTE_MEDICINE_SCIENCE = _reg(Palette(
    name="medicine_science",
    background="#F4F8FB",
    surface="#E8F2F8",
    text_primary="#0C1A27",
    text_secondary="#2A5268",
    text_on_dark="#EAF3FA",
    primary="#15426A",
    accent="#17A8C4",       # Scientific teal
    border="#90C8DC",
    success="#2AAF80",
    warning="#C03C2A",
))

# ── Technology + Business blend ───────────────────────────────────────────
PALETTE_TECH_BUSINESS = _reg(Palette(
    name="technology_business",
    background="#F5F7FA",
    surface="#EAECF2",
    text_primary="#0C1220",
    text_secondary="#3A4A5C",
    text_on_dark="#EDF0F5",
    primary="#18274A",
    accent="#3A7BD5",
    border="#8EA8CC",
    success="#22A060",
    warning="#E09020",
))

# ── Neutral / professional fallback ───────────────────────────────────────
PALETTE_NEUTRAL = _reg(Palette(
    name="neutral",
    background="#F8F9FA",
    surface="#EDEFF2",
    text_primary="#111827",
    text_secondary="#4B5563",
    text_on_dark="#F3F4F6",
    primary="#1E293B",
    accent="#3B82F6",
    border="#94A3B8",
    success="#22C55E",
    warning="#F59E0B",
))


# ═══════════════════════════════════════════════════════════════════════════
# 3.  TOPIC PROFILE  — structured output of classifier
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TopicProfile:
    """
    Structured semantic signals derived from a topic string.
    Scores are floats in [0, 1].  Only filled-in categories are stored.
    """
    topic: str
    scores: dict[str, float] = field(default_factory=dict)  # category → score
    primary_category: str = "neutral"
    secondary_categories: list[str] = field(default_factory=list)
    visual_mood: str = "professional"
    palette_name: str = "neutral"
    confidence: float = 0.0

    def top_categories(self, n: int = 3) -> list[tuple[str, float]]:
        """Return the top-n (category, score) pairs, sorted descending."""
        return sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)[:n]


# ═══════════════════════════════════════════════════════════════════════════
# 4.  TOPIC CLASSIFIER  — deterministic, keyword-weighted, multilingual
# ═══════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# Keyword catalogue
# Each entry: (pattern_or_word, weight)
# Patterns are matched case-insensitively against the normalized topic string.
# Kazakh, Russian, and English terms are included.
# ---------------------------------------------------------------------------
_CATEGORIES: dict[str, list[tuple[str, float]]] = {
    "nature": [
        # Kazakh
        ("табиғат", 1.0), ("экология", 0.9), ("орман", 0.9),
        ("өсімдік", 0.8), ("жануар", 0.8), ("климат", 0.8),
        ("қоршаған орта", 0.9), ("флора", 0.8), ("фауна", 0.8),
        ("биосфера", 0.85), ("биоалуантүрлілік", 0.85),
        # Russian
        ("природа", 1.0), ("экологи", 0.9), ("лес", 0.85),
        ("растени", 0.8), ("животн", 0.8), ("климат", 0.8),
        ("окружающая среда", 0.9), ("биосфер", 0.85),
        # English
        ("nature", 1.0), ("ecology", 0.9), ("forest", 0.85),
        ("plant", 0.7), ("animal", 0.7), ("climate", 0.75),
        ("environment", 0.9), ("biodiversity", 0.9),
        ("flora", 0.8), ("fauna", 0.8),
    ],
    "ocean": [
        # Kazakh
        ("теңіз", 1.0), ("мұхит", 1.0), ("каспий", 0.95),
        ("су", 0.6), ("өзен", 0.85), ("көл", 0.8),
        ("балық", 0.7), ("гидрология", 0.85),
        # Russian
        ("море", 1.0), ("океан", 1.0), ("каспийск", 0.95),
        ("вода", 0.6), ("река", 0.85), ("озеро", 0.8),
        ("рыб", 0.65), ("гидрологи", 0.85),
        # English
        ("ocean", 1.0), ("sea", 1.0), ("caspian", 0.95),
        ("water", 0.6), ("river", 0.8), ("lake", 0.8),
        ("marine", 0.9), ("aquatic", 0.9), ("hydrolog", 0.85),
    ],
    "medicine": [
        # Kazakh
        ("анатомия", 1.0), ("медицина", 1.0), ("денсаулық", 0.9),
        ("жүрек", 0.85), ("ми", 0.8), ("ауру", 0.8),
        ("орган", 0.75), ("дәрі", 0.8), ("клиника", 0.85),
        ("хирургия", 0.9), ("диагноз", 0.85), ("емдеу", 0.85),
        # Russian
        ("анатоми", 1.0), ("медицин", 1.0), ("здоровь", 0.9),
        ("сердц", 0.85), ("мозг", 0.8), ("болезн", 0.8),
        ("орган", 0.75), ("лекарств", 0.8), ("клиник", 0.85),
        ("хирурги", 0.9), ("диагноз", 0.85),
        # English
        ("anatomy", 1.0), ("medicine", 1.0), ("health", 0.9),
        ("heart", 0.85), ("brain", 0.8), ("disease", 0.8),
        ("organ", 0.75), ("clinical", 0.85), ("surgery", 0.9),
        ("diagnosis", 0.85), ("therapy", 0.8), ("pharma", 0.75),
    ],
    "science": [
        # Kazakh
        ("ғылым", 0.9), ("зерттеу", 0.8), ("физика", 0.9),
        ("химия", 0.9), ("биология", 0.9), ("математика", 0.85),
        # Russian
        ("наук", 0.9), ("исследовани", 0.8), ("физик", 0.9),
        ("хими", 0.9), ("биологи", 0.9), ("математик", 0.85),
        # English
        ("science", 0.9), ("research", 0.8), ("physics", 0.9),
        ("chemistry", 0.9), ("biology", 0.9), ("mathematics", 0.85),
        ("laboratory", 0.85),
    ],
    "technology": [
        # Kazakh
        ("жасанды интеллект", 1.0), ("ии", 0.9), ("технология", 0.9),
        ("киберқауіпсіздік", 1.0), ("бағдарлама", 0.85),
        ("деректер", 0.8), ("робот", 0.85), ("цифрлы", 0.85),
        ("автоматтандыру", 0.8),
        # Russian
        ("искусственный интеллект", 1.0), ("ии", 0.9),
        ("технологи", 0.9), ("кибербезопасност", 1.0),
        ("программ", 0.85), ("данн", 0.8), ("робот", 0.85),
        ("цифров", 0.85), ("автоматизаци", 0.8),
        # English
        ("artificial intelligence", 1.0), ("ai", 0.9), ("machine learning", 0.95),
        ("technology", 0.9), ("cybersecurity", 1.0), ("software", 0.85),
        ("data", 0.75), ("robot", 0.85), ("digital", 0.85),
        ("automation", 0.8), ("cloud", 0.8), ("blockchain", 0.85),
    ],
    "finance": [
        # Kazakh
        ("қаржы", 1.0), ("экономика", 0.9), ("банк", 0.85),
        ("инвестиция", 0.9), ("бюджет", 0.85), ("кіріс", 0.8),
        ("пайда", 0.8), ("биржа", 0.9),
        # Russian
        ("финанс", 1.0), ("экономик", 0.9), ("банк", 0.85),
        ("инвестиц", 0.9), ("бюджет", 0.85), ("доход", 0.8),
        ("прибыл", 0.8), ("биржа", 0.9),
        # English
        ("finance", 1.0), ("economics", 0.9), ("banking", 0.85),
        ("investment", 0.9), ("budget", 0.85), ("revenue", 0.8),
        ("profit", 0.8), ("stock", 0.85), ("market", 0.75),
    ],
    "history": [
        # Kazakh
        ("тарих", 1.0), ("мәдениет", 0.85), ("өркениет", 0.9),
        ("дәстүр", 0.8), ("мұра", 0.85), ("ескерткіш", 0.8),
        ("кезең", 0.75), ("ғасыр", 0.75),
        # Russian
        ("истори", 1.0), ("культур", 0.85), ("цивилизаци", 0.9),
        ("традиц", 0.8), ("наследи", 0.85), ("памятник", 0.8),
        ("эпох", 0.75), ("век", 0.65),
        # English
        ("history", 1.0), ("culture", 0.85), ("civilization", 0.9),
        ("tradition", 0.8), ("heritage", 0.85), ("ancient", 0.8),
        ("era", 0.7), ("century", 0.65), ("archaeology", 0.9),
    ],
    "space": [
        # Kazakh
        ("ғарыш", 1.0), ("астрономия", 1.0), ("планета", 0.9),
        ("жұлдыз", 0.85), ("ғаламшар", 0.9), ("галактика", 0.9),
        # Russian
        ("космос", 1.0), ("астрономи", 1.0), ("планет", 0.9),
        ("звезд", 0.85), ("галактик", 0.9), ("вселенн", 0.9),
        # English
        ("space", 1.0), ("astronomy", 1.0), ("planet", 0.9),
        ("star", 0.8), ("galaxy", 0.9), ("universe", 0.9),
        ("cosmos", 1.0), ("nasa", 0.85), ("orbit", 0.85),
    ],
    "education": [
        # Kazakh
        ("білім", 1.0), ("оқу", 0.85), ("мектеп", 0.85),
        ("университет", 0.85), ("студент", 0.8), ("оқушы", 0.8),
        ("педагогика", 0.9), ("оқыту", 0.85),
        # Russian
        ("образовани", 1.0), ("обучени", 0.85), ("школ", 0.85),
        ("университет", 0.85), ("студент", 0.8), ("педагогик", 0.9),
        # English
        ("education", 1.0), ("learning", 0.85), ("school", 0.85),
        ("university", 0.85), ("student", 0.8), ("pedagogy", 0.9),
        ("curriculum", 0.85), ("teaching", 0.8),
    ],
    "business": [
        # Kazakh
        ("бизнес", 1.0), ("кәсіпкерлік", 1.0), ("компания", 0.85),
        ("маркетинг", 0.85), ("стратегия", 0.8), ("менеджмент", 0.85),
        ("стартап", 0.9), ("өндіріс", 0.8),
        # Russian
        ("бизнес", 1.0), ("предпринимательств", 1.0), ("компани", 0.85),
        ("маркетинг", 0.85), ("стратеги", 0.8), ("менеджмент", 0.85),
        ("стартап", 0.9), ("производств", 0.8),
        # English
        ("business", 1.0), ("entrepreneurship", 1.0), ("company", 0.85),
        ("marketing", 0.85), ("strategy", 0.8), ("management", 0.85),
        ("startup", 0.9), ("enterprise", 0.85),
    ],
    "agriculture": [
        # Kazakh
        ("ауыл шаруашылығы", 1.0), ("егін", 0.9), ("мал", 0.85),
        ("топырақ", 0.85), ("дала", 0.75), ("өсімдік шаруашылығы", 0.95),
        # Russian
        ("сельское хозяйств", 1.0), ("земледели", 0.9), ("скотоводств", 0.85),
        ("почв", 0.85), ("урожай", 0.9), ("агрономи", 0.95),
        # English
        ("agriculture", 1.0), ("farming", 0.95), ("crop", 0.85),
        ("soil", 0.8), ("harvest", 0.85), ("agronomy", 0.95),
        ("livestock", 0.85),
    ],
}

# ---------------------------------------------------------------------------
# Compatible combination map
# When two categories co-occur strongly, use a blend palette instead.
# Keys are frozensets of the two category names.
# ---------------------------------------------------------------------------
_COMBO_PALETTE: dict[frozenset, str] = {
    frozenset({"ocean", "nature"}):     "ocean_ecology",
    frozenset({"ocean", "ecology"}):    "ocean_ecology",
    frozenset({"nature", "ecology"}):   "nature",
    frozenset({"medicine", "science"}): "medicine_science",
    frozenset({"technology", "business"}): "technology_business",
    frozenset({"technology", "finance"}):  "technology_business",
    frozenset({"space", "science"}):    "space",
    frozenset({"history", "culture"}):  "history",
    frozenset({"education", "science"}): "education",
    frozenset({"finance", "business"}): "finance",
    frozenset({"agriculture", "nature"}): "agriculture",
}

# ---------------------------------------------------------------------------
# Category → single palette name (base mapping)
# ---------------------------------------------------------------------------
_CATEGORY_PALETTE: dict[str, str] = {
    "nature":      "nature",
    "ocean":       "ocean",
    "medicine":    "medicine",
    "science":     "medicine_science",
    "technology":  "technology",
    "finance":     "finance",
    "history":     "history",
    "space":       "space",
    "education":   "education",
    "business":    "business",
    "agriculture": "agriculture",
}

# ---------------------------------------------------------------------------
# Visual mood per palette
# ---------------------------------------------------------------------------
_PALETTE_MOOD: dict[str, str] = {
    "nature":             "organic",
    "ocean":              "fluid",
    "medicine":           "clinical",
    "medicine_science":   "clinical",
    "technology":         "digital",
    "technology_business": "professional-digital",
    "finance":            "authoritative",
    "history":            "warm-heritage",
    "space":              "cosmic",
    "education":          "scholarly",
    "business":           "professional",
    "agriculture":        "earthy",
    "ocean_ecology":      "natural-fluid",
    "neutral":            "professional",
}


def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    text = text.lower().strip()
    # NFC normalize (Kazakh letters are multibyte but already NFC in most environments)
    text = unicodedata.normalize("NFC", text)
    # Collapse multiple spaces / tabs
    text = re.sub(r"\s+", " ", text)
    return text


class TopicClassifier:
    """
    Deterministic, keyword-weighted topic classifier.
    Returns a TopicProfile with per-category confidence scores.
    """

    def classify(self, topic: str) -> TopicProfile:
        norm = _normalize(topic)
        scores: dict[str, float] = {}

        for category, patterns in _CATEGORIES.items():
            total = 0.0
            matches = 0
            for pattern, weight in patterns:
                if pattern in norm:
                    total += weight
                    matches += 1
            if matches > 0:
                # Normalise by number of patterns to avoid categories with
                # many patterns dominating by sheer count
                scores[category] = min(total / len(patterns) * 10.0, 1.0)

        if not scores:
            return TopicProfile(
                topic=topic,
                scores={},
                primary_category="neutral",
                secondary_categories=[],
                visual_mood="professional",
                palette_name="neutral",
                confidence=0.0,
            )

        sorted_cats = sorted(scores, key=lambda c: scores[c], reverse=True)
        primary    = sorted_cats[0]
        secondary  = sorted_cats[1:4]
        confidence = scores[primary]

        # Choose palette — check combo first
        palette_name = self._select_palette(primary, secondary, scores)
        mood         = _PALETTE_MOOD.get(palette_name, "professional")

        return TopicProfile(
            topic=topic,
            scores=scores,
            primary_category=primary,
            secondary_categories=secondary,
            visual_mood=mood,
            palette_name=palette_name,
            confidence=round(confidence, 3),
        )

    def _select_palette(
        self,
        primary: str,
        secondary: list[str],
        scores: dict[str, float],
    ) -> str:
        # Check if a secondary category is strong enough to trigger a blend
        if secondary:
            second = secondary[0]
            threshold_for_blend = 0.5   # secondary score must be >= this
            if scores.get(second, 0) >= threshold_for_blend:
                key = frozenset({primary, second})
                if key in _COMBO_PALETTE:
                    return _COMBO_PALETTE[key]

        return _CATEGORY_PALETTE.get(primary, "neutral")


# ═══════════════════════════════════════════════════════════════════════════
# 5.  PALETTE → THEME ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

def palette_to_theme(palette: Palette, base_name: str | None = None) -> Theme:
    """
    Convert a Palette into the existing Theme API without modifying Theme itself.

    Fonts are intentionally left as neutral defaults ("Calibri") because the
    actual font choice belongs to Gemini's VisualDesignSpec.  DesignSpec.to_theme()
    overrides these defaults with whatever Gemini specified.
    """
    name = base_name or palette.name

    return Theme(
        name=name,
        primary=palette.primary,
        secondary=palette.border,        # border ≈ secondary mid-colour
        accent=palette.accent,
        background=palette.background,
        text_dark=palette.text_primary,
        text_light=palette.text_on_dark,
        font_heading="Calibri",   # Gemini overrides this via DesignSpec.to_theme()
        font_body="Calibri",      # Gemini overrides this via DesignSpec.to_theme()
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6.  PUBLIC FACADE  — ThemeSelector
# ═══════════════════════════════════════════════════════════════════════════

class ThemeSelector:
    """
    High-level facade:  topic string → Theme (compatible with existing renderer)

    Usage::

        selector = ThemeSelector()
        theme = selector.select("Адам анатомиясы")
        # → Theme with clinical blue/teal palette

        profile = selector.profile("Каспий теңізінің экологиясы")
        # → TopicProfile with scores, palette_name, etc.
    """

    def __init__(self) -> None:
        self._classifier = TopicClassifier()

    def profile(self, topic: str) -> TopicProfile:
        """Return the full TopicProfile for *topic* (useful for debugging / tests)."""
        return self._classifier.classify(topic)

    def select(self, topic: str) -> Theme:
        """Return a Theme chosen for *topic*.  Always deterministic."""
        tp      = self.profile(topic)
        palette = _PALETTES.get(tp.palette_name, _PALETTES["neutral"])
        return palette_to_theme(palette, base_name=tp.palette_name)

    def select_with_profile(self, topic: str) -> tuple[Theme, TopicProfile]:
        """Return (Theme, TopicProfile) in one call."""
        tp      = self.profile(topic)
        palette = _PALETTES.get(tp.palette_name, _PALETTES["neutral"])
        theme   = palette_to_theme(palette, base_name=tp.palette_name)
        return theme, tp


# ═══════════════════════════════════════════════════════════════════════════
# 7.  REGISTRY HELPERS  (for external inspection / testing)
# ═══════════════════════════════════════════════════════════════════════════

def list_palettes() -> list[str]:
    """Return all registered palette names."""
    return list(_PALETTES)


def get_palette(name: str) -> Palette:
    """Return a palette by name.  Raises KeyError for unknown names."""
    return _PALETTES[name]
