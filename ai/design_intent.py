"""
ai/design_intent.py
────────────────────────────────────────────────────────────────────────────
Phase 2: DesignIntent — structured representation of explicit user design
preferences extracted from a natural-language request.

Scope
-----
DesignIntent holds ONLY what the user explicitly stated about visual design.
It does NOT contain topic information, slide count, or language preferences
— those remain in PresentationRequirements / PresentationPlan.

Extraction strategy
-------------------
DesignIntent is populated by DesignIntentParser, which runs deterministic
keyword/pattern matching on the raw user message.  This deliberately avoids
a second LLM call: the existing Gemini planning call handles content; color
and font preferences are simple enough for pattern matching.

Priority contract
-----------------
Any non-None field in DesignIntent overrides the corresponding value from
the style/topic layer in DesignResolver.  DesignResolver enforces this —
DesignIntent itself does not.

Fields
------
background_color : str | None   — '#RRGGBB', overrides palette background
primary_color    : str | None   — '#RRGGBB', overrides palette primary
accent_color     : str | None   — '#RRGGBB', overrides palette accent
font_heading     : str | None   — typeface name, overrides font resolution
font_body        : str | None   — typeface name, overrides font resolution
style_hint       : str | None   — "academic"|"modern"|"minimal", treated as
                                  a *hint* (lower priority than explicit colors)
density_hint     : str | None   — "spacious"|"normal"|"dense"

All fields default to None — meaning "user said nothing about this".
A DesignIntent with all-None fields is functionally identical to None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── Named color vocabulary ────────────────────────────────────────────────
# Kazakh (kk), Russian (ru), and English (en) color names → hex.
# Only colors that are unambiguous and render well as slide backgrounds.

_COLOR_NAMES: dict[str, str] = {
    # English
    "red":         "#C0392B",
    "dark red":    "#922B21",
    "blue":        "#1A5276",
    "dark blue":   "#154360",
    "navy":        "#0D1B2A",
    "green":       "#1E8449",
    "dark green":  "#145A32",
    "yellow":      "#D4AC0D",
    "orange":      "#CA6F1E",
    "purple":      "#6C3483",
    "violet":      "#7D3C98",
    "pink":        "#C0516E",
    "black":       "#111111",
    "white":       "#FFFFFF",
    "grey":        "#5D6D7E",
    "gray":        "#5D6D7E",
    "brown":       "#784212",
    "teal":        "#148F77",
    "cyan":        "#117A8B",
    "gold":        "#B7950B",
    "beige":       "#F5F0E8",
    "cream":       "#FAF7F0",
    # Russian
    "красный":     "#C0392B",
    "красн":       "#C0392B",
    "синий":       "#1A5276",
    "тёмно-синий": "#154360",
    "темно-синий": "#154360",
    "зелёный":     "#1E8449",
    "зеленый":     "#1E8449",
    "жёлтый":      "#D4AC0D",
    "желтый":      "#D4AC0D",
    "оранжевый":   "#CA6F1E",
    "фиолетовый":  "#6C3483",
    "розовый":     "#C0516E",
    "чёрный":      "#111111",
    "черный":      "#111111",
    "белый":       "#FFFFFF",
    "серый":       "#5D6D7E",
    "коричневый":  "#784212",
    "бирюзовый":   "#148F77",
    "золотой":     "#B7950B",
    # Kazakh
    "қызыл":       "#C0392B",
    "көк":         "#1A5276",
    "жасыл":       "#1E8449",
    "сары":        "#D4AC0D",
    "қара":        "#111111",
    "ақ":          "#FFFFFF",
    "сұр":         "#5D6D7E",
    "күлгін":      "#6C3483",
    "қоңыр":       "#784212",
    "алтын":       "#B7950B",
}

# ── Style hint vocabulary ─────────────────────────────────────────────────

_STYLE_HINTS: dict[str, str] = {
    # English
    "academic":    "academic",
    "formal":      "academic",
    "scientific":  "academic",
    "modern":      "modern",
    "contemporary": "modern",
    "clean":       "modern",
    "minimal":     "minimal",
    "minimalist":  "minimal",
    "minimalistic": "minimal",
    "simple":      "minimal",
    # Russian
    "академический": "academic",
    "академичный":   "academic",
    "научный":       "academic",
    "современный":   "modern",
    "минимальный":   "minimal",
    "минималистичный": "minimal",
    "минималистский":  "minimal",
    # Kazakh
    "академиялық":   "academic",
    "ғылыми":        "academic",
    "заманауи":      "modern",
    "минималистік":  "minimal",
    "қарапайым":     "minimal",
}

# ── Density hint vocabulary ───────────────────────────────────────────────

_DENSITY_HINTS: dict[str, str] = {
    # English
    "spacious":    "spacious",
    "airy":        "spacious",
    "dense":       "dense",
    "compact":     "dense",
    "detailed":    "dense",
    "information-rich": "dense",
    # Russian
    "просторный":  "spacious",
    "плотный":     "dense",
    "компактный":  "dense",
    "подробный":   "dense",
    # Kazakh
    "кеңістікті":  "spacious",
    "тығыз":       "dense",
    "егжейтегжейлі": "dense",
}

# ── Font name recogniser ──────────────────────────────────────────────────
# Only safe fonts available in PowerPoint by default.

_SAFE_FONTS: frozenset[str] = frozenset({
    "arial", "calibri", "cambria", "georgia", "helvetica",
    "times new roman", "verdana", "trebuchet ms", "garamond",
    "century gothic", "franklin gothic medium",
})


# ── DesignIntent dataclass ────────────────────────────────────────────────

@dataclass
class DesignIntent:
    """
    Explicit user design preferences extracted from a natural-language message.

    All fields default to None (= "user said nothing about this").
    """
    background_color: str | None = None   # '#RRGGBB'
    primary_color:    str | None = None   # '#RRGGBB'
    accent_color:     str | None = None   # '#RRGGBB'
    font_heading:     str | None = None   # typeface name
    font_body:        str | None = None   # typeface name
    style_hint:       str | None = None   # "academic"|"modern"|"minimal"
    density_hint:     str | None = None   # "spacious"|"normal"|"dense"

    def is_empty(self) -> bool:
        """Return True when no explicit preference was captured."""
        return all(v is None for v in (
            self.background_color,
            self.primary_color,
            self.accent_color,
            self.font_heading,
            self.font_body,
            self.style_hint,
            self.density_hint,
        ))

    def __repr__(self) -> str:  # pragma: no cover
        filled = {k: v for k, v in self.__dict__.items() if v is not None}
        return f"DesignIntent({filled})"


# ── DesignIntentParser ────────────────────────────────────────────────────

class DesignIntentParser:
    """
    Deterministic, pattern-based extractor of DesignIntent from raw text.

    No LLM call — uses keyword matching and simple regex for hex codes.
    Supports Kazakh, Russian, and English in a single pass.

    Usage::

        parser = DesignIntentParser()
        intent = parser.parse("nature topic, red background, minimal style")
        # → DesignIntent(background_color='#C0392B', style_hint='minimal')
    """

    # ── compiled regex for inline hex codes ──────────────────────────────
    # Matches #RGB (3-digit) and #RRGGBB (6-digit), case-insensitive.
    _HEX_RE = re.compile(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")

    # ── context keywords that signal a color role ─────────────────────────
    # Pattern: "<role_kw> … <color>" within a short window.
    # Ordered by specificity — first match wins.

    _BACKGROUND_KW = frozenset({
        # English
        "background", "bg", "backdrop", "slide background", "slide color",
        "slide colour",
        # Russian
        "фон", "фоновый", "фоне", "цвет фона", "цвет слайда",
        # Kazakh
        "фон", "слайд түсі", "фондық",
    })

    _PRIMARY_KW = frozenset({
        # English
        "primary", "main color", "main colour", "header color", "header colour",
        "heading color", "heading colour",
        # Russian
        "основной цвет", "цвет заголовка", "основной",
        # Kazakh
        "негізгі түс", "тақырып түсі",
    })

    _ACCENT_KW = frozenset({
        # English
        "accent", "highlight", "highlight color", "accent color", "accent colour",
        # Russian
        "акцент", "цвет акцента", "выделение",
        # Kazakh
        "акцент", "бөлектеу",
    })

    def parse(self, text: str) -> DesignIntent:
        """
        Extract a DesignIntent from *text*.

        Strategy
        --------
        1. Normalise text (lowercase, collapse whitespace).
        2. Scan for explicit hex codes first (#RRGGBB).
        3. Scan for named colors combined with role keywords.
        4. Scan for style/density hints.
        5. Scan for font names.
        """
        norm = self._normalise(text)
        intent = DesignIntent()

        self._extract_hex(norm, intent)
        self._extract_named_colors(norm, intent)
        self._extract_style(norm, intent)
        self._extract_density(norm, intent)
        self._extract_fonts(norm, intent)

        return intent

    # ── private extraction steps ──────────────────────────────────────────

    def _normalise(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _extract_hex(self, norm: str, intent: DesignIntent) -> None:
        """Find explicit #RRGGBB codes and assign to roles by context."""
        for m in self._HEX_RE.finditer(norm):
            hex_val = self._expand_hex(m.group(0))
            start   = m.start()
            # Look at the 60-char window before the hex code for role signals
            window  = norm[max(0, start - 60): start]

            if any(kw in window for kw in self._BACKGROUND_KW):
                if intent.background_color is None:
                    intent.background_color = hex_val
            elif any(kw in window for kw in self._PRIMARY_KW):
                if intent.primary_color is None:
                    intent.primary_color = hex_val
            elif any(kw in window for kw in self._ACCENT_KW):
                if intent.accent_color is None:
                    intent.accent_color = hex_val
            else:
                # Unqualified hex → assume background (most common intent)
                if intent.background_color is None:
                    intent.background_color = hex_val

    def _extract_named_colors(self, norm: str, intent: DesignIntent) -> None:
        """
        Detect named colors and assign each color to its nearest role keyword.

        Examples:
            "қызыл фон" -> background
            "көк акцент" -> accent
            "ақ фон, көк акцент" -> background + accent
        """

        role_groups = (
            ("background", self._BACKGROUND_KW),
            ("primary", self._PRIMARY_KW),
            ("accent", self._ACCENT_KW),
        )

        for color_name, hex_val in sorted(
            _COLOR_NAMES.items(),
            key=lambda kv: -len(kv[0]),
        ):
            for match in re.finditer(re.escape(color_name), norm):
                color_start = match.start()
                color_end = match.end()

                best_role = None
                best_distance = None

                # Only inspect a local neighborhood around THIS color.
                local_start = max(0, color_start - 25)
                local_end = min(len(norm), color_end + 25)

                for role, keywords in role_groups:
                    for kw in keywords:
                        # Search every occurrence of the role keyword
                        # inside the local neighborhood.
                        local_text = norm[local_start:local_end]

                        for role_match in re.finditer(
                            re.escape(kw),
                            local_text,
                        ):
                            role_start = local_start + role_match.start()
                            role_end = local_start + role_match.end()

                            # Ignore a keyword that is actually farther
                            # than 25 characters from the color.
                            if role_end < color_start:
                                distance = color_start - role_end
                            elif role_start > color_end:
                                distance = role_start - color_end
                            else:
                                distance = 0

                            if distance > 25:
                                continue

                            if (
                                best_distance is None
                                or distance < best_distance
                            ):
                                best_distance = distance
                                best_role = role

                if best_role == "background":
                    if intent.background_color is None:
                        intent.background_color = hex_val

                elif best_role == "primary":
                    if intent.primary_color is None:
                        intent.primary_color = hex_val

                elif best_role == "accent":
                    if intent.accent_color is None:
                        intent.accent_color = hex_val

                else:
                    # No explicit role → background.
                    if intent.background_color is None:
                        intent.background_color = hex_val

    def _extract_style(self, norm: str, intent: DesignIntent) -> None:
        """Detect style hint keywords."""
        for kw, style in sorted(
            _STYLE_HINTS.items(), key=lambda kv: -len(kv[0])
        ):
            if kw in norm:
                if intent.style_hint is None:
                    intent.style_hint = style
                break

    def _extract_density(self, norm: str, intent: DesignIntent) -> None:
        """Detect density hint keywords."""
        for kw, density in sorted(
            _DENSITY_HINTS.items(), key=lambda kv: -len(kv[0])
        ):
            if kw in norm:
                if intent.density_hint is None:
                    intent.density_hint = density
                break

    def _extract_fonts(self, norm: str, intent: DesignIntent) -> None:
        """
        Detect font name mentions.

        Heuristic: if a safe font name appears in text and is preceded by a
        font-role keyword ("heading font", "body font", "font"), assign it.
        If no role keyword is present, assign to heading font (more impactful).
        """
        _HEADING_KW = {"heading font", "title font", "шрифт заголовка",
                       "тақырып шрифті", "заголовок"}
        _BODY_KW    = {"body font", "text font", "шрифт текста",
                       "мәтін шрифті", "основной шрифт"}

        for font in sorted(_SAFE_FONTS, key=len, reverse=True):
            if font not in norm:
                continue

            idx    = norm.index(font)
            window = norm[max(0, idx - 40): idx]

            if any(kw in window for kw in _BODY_KW):
                if intent.font_body is None:
                    intent.font_body = self._title_case_font(font)
            else:
                # heading_kw match OR no role kw → heading
                if intent.font_heading is None:
                    intent.font_heading = self._title_case_font(font)

    # ── utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _expand_hex(raw: str) -> str:
        """Convert #RGB → #RRGGBB, leave #RRGGBB unchanged."""
        raw = raw.lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        return "#" + raw.upper()

    @staticmethod
    def _title_case_font(name: str) -> str:
        """'arial' → 'Arial', 'times new roman' → 'Times New Roman'."""
        return " ".join(w.capitalize() for w in name.split())


# ── Module-level singleton ────────────────────────────────────────────────
# Import and use directly: from ai.design_intent import parse_design_intent

_parser = DesignIntentParser()


def parse_design_intent(user_message: str) -> DesignIntent:
    """
    Parse explicit design preferences from a raw user message.

    Returns a DesignIntent; check .is_empty() to skip resolution if nothing
    was extracted.
    """
    return _parser.parse(user_message)
