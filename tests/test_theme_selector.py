"""
Tests for presentation/theme_selector.py
All tests are deterministic and fully offline.
"""
import re

import pytest

from presentation.theme_selector import (
    ThemeSelector,
    TopicClassifier,
    TopicProfile,
    Palette,
    list_palettes,
    get_palette,
    palette_to_theme,
    _PALETTES,
)
from presentation.styles import Theme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SELECTOR = ThemeSelector()
CLASSIFIER = TopicClassifier()

REQUIRED_PALETTE_ROLES = [
    "background", "surface", "text_primary", "text_secondary",
    "text_on_dark", "primary", "accent", "border", "success", "warning",
]


def _is_hex(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", value))


def _profile(topic: str) -> TopicProfile:
    return CLASSIFIER.classify(topic)


# ---------------------------------------------------------------------------
# 1. Palette integrity — every palette has all required roles
# ---------------------------------------------------------------------------

class TestPaletteLibrary:
    def test_at_least_10_palettes(self):
        assert len(list_palettes()) >= 10

    @pytest.mark.parametrize("name", list_palettes())
    def test_palette_has_all_roles(self, name: str):
        p = get_palette(name)
        for role in REQUIRED_PALETTE_ROLES:
            assert hasattr(p, role), f"Palette '{name}' missing role '{role}'"
            assert _is_hex(getattr(p, role)), (
                f"Palette '{name}'.{role} = {getattr(p, role)!r} is not valid hex"
            )

    @pytest.mark.parametrize("name", list_palettes())
    def test_palette_name_matches_key(self, name: str):
        p = get_palette(name)
        assert p.name == name

    def test_get_palette_unknown_raises(self):
        with pytest.raises(KeyError):
            get_palette("does_not_exist")


# ---------------------------------------------------------------------------
# 2. TopicProfile structure
# ---------------------------------------------------------------------------

class TestTopicProfile:
    def test_profile_returns_topic_profile(self):
        p = _profile("nature ecology")
        assert isinstance(p, TopicProfile)

    def test_profile_has_required_fields(self):
        p = _profile("technology AI")
        assert isinstance(p.scores, dict)
        assert isinstance(p.primary_category, str)
        assert isinstance(p.secondary_categories, list)
        assert isinstance(p.visual_mood, str)
        assert isinstance(p.palette_name, str)
        assert 0.0 <= p.confidence <= 1.0

    def test_unknown_topic_returns_neutral(self):
        p = _profile("xyzzy foobar baz")
        assert p.primary_category == "neutral"
        assert p.palette_name == "neutral"
        assert p.confidence == 0.0

    def test_top_categories_returns_sorted(self):
        p = _profile("ocean water marine ecology")
        top = p.top_categories(3)
        scores = [s for _, s in top]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 3. Category classification — English
# ---------------------------------------------------------------------------

class TestClassificationEnglish:
    def test_nature_selects_green_palette(self):
        p = _profile("nature ecology forests biodiversity")
        assert p.primary_category == "nature"
        assert "green" in p.palette_name or p.palette_name in ("nature", "agriculture", "ocean_ecology")

    def test_ocean_selects_blue_teal_palette(self):
        p = _profile("ocean marine water aquatic")
        assert p.primary_category == "ocean"
        assert p.palette_name in ("ocean", "ocean_ecology")

    def test_anatomy_selects_medical_palette(self):
        p = _profile("human anatomy heart brain organ medicine")
        assert p.primary_category == "medicine"
        assert p.palette_name in ("medicine", "medicine_science")

    def test_technology_selects_tech_palette(self):
        p = _profile("artificial intelligence machine learning technology")
        assert p.primary_category == "technology"
        assert p.palette_name in ("technology", "technology_business")

    def test_history_selects_warm_palette(self):
        p = _profile("history civilization culture heritage ancient")
        assert p.primary_category == "history"
        assert p.palette_name == "history"

    def test_space_selects_space_palette(self):
        p = _profile("space astronomy galaxy universe cosmos")
        assert p.primary_category == "space"
        assert p.palette_name == "space"

    def test_finance_selects_finance_palette(self):
        p = _profile("finance economics investment banking market")
        assert p.primary_category == "finance"
        assert p.palette_name in ("finance", "technology_business")

    def test_education_selects_education_palette(self):
        p = _profile("education learning university students curriculum")
        assert p.primary_category == "education"
        assert p.palette_name == "education"

    def test_business_selects_business_palette(self):
        p = _profile("business entrepreneurship startup company marketing")
        assert p.primary_category == "business"
        assert p.palette_name in ("business", "technology_business", "finance")


# ---------------------------------------------------------------------------
# 4. Kazakh keywords
# ---------------------------------------------------------------------------

class TestClassificationKazakh:
    def test_kk_nature(self):
        p = _profile("табиғат экология орман флора")
        assert p.primary_category == "nature"

    def test_kk_ocean(self):
        p = _profile("Каспий теңізінің экологиясы")
        # ocean should be primary or very close to nature/ecology
        assert p.primary_category in ("ocean", "nature", "ecology")
        assert p.palette_name in ("ocean", "ocean_ecology", "nature")

    def test_kk_anatomy(self):
        p = _profile("Адам анатомиясы жүрек ми орган")
        assert p.primary_category == "medicine"

    def test_kk_technology(self):
        p = _profile("жасанды интеллект технология бағдарлама")
        assert p.primary_category == "technology"

    def test_kk_history(self):
        p = _profile("Қазақстан тарихы мәдениет өркениет")
        assert p.primary_category == "history"

    def test_kk_business(self):
        p = _profile("кәсіпкерлік бизнес компания маркетинг")
        assert p.primary_category == "business"

    def test_kk_education(self):
        p = _profile("білім беру университет студент оқыту")
        assert p.primary_category == "education"


# ---------------------------------------------------------------------------
# 5. Russian keywords
# ---------------------------------------------------------------------------

class TestClassificationRussian:
    def test_ru_nature(self):
        p = _profile("природа экология лес растения")
        assert p.primary_category == "nature"

    def test_ru_ocean(self):
        p = _profile("Каспийское море океан вода")
        assert p.primary_category in ("ocean", "nature")

    def test_ru_medicine(self):
        p = _profile("анатомия медицина здоровье болезнь")
        assert p.primary_category == "medicine"

    def test_ru_technology(self):
        p = _profile("искусственный интеллект технологии программы")
        assert p.primary_category == "technology"


# ---------------------------------------------------------------------------
# 6. Mixed / combined topics
# ---------------------------------------------------------------------------

class TestCombinedTopics:
    def test_ocean_ecology_combo(self):
        p = _profile("Каспий теңізінің экологиясы су өсімдік")
        # Should resolve to ocean_ecology blend or similar teal/green
        assert p.palette_name in ("ocean_ecology", "ocean", "nature")

    def test_medicine_science_combo(self):
        p = _profile("medical science research biology anatomy")
        assert p.palette_name in ("medicine_science", "medicine")

    def test_technology_business_combo(self):
        p = _profile("tech startup business strategy software")
        assert p.palette_name in ("technology_business", "technology", "business")

    def test_unknown_gives_fallback(self):
        p = _profile("абракадабра нечто непонятное xyz123")
        assert p.palette_name == "neutral"


# ---------------------------------------------------------------------------
# 7. Determinism — same input always produces same output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.parametrize("topic", [
        "nature ecology forests",
        "ocean marine Caspian",
        "artificial intelligence technology",
        "history culture heritage",
        "business entrepreneurship",
        "Адам анатомиясы",
        "Каспий теңізінің экологиясы",
    ])
    def test_deterministic(self, topic: str):
        p1 = _profile(topic)
        p2 = _profile(topic)
        assert p1.primary_category == p2.primary_category
        assert p1.palette_name == p2.palette_name
        assert p1.confidence == p2.confidence


# ---------------------------------------------------------------------------
# 8. ThemeSelector.select() → Theme compatibility
# ---------------------------------------------------------------------------

class TestThemeSelector:
    def test_returns_theme_instance(self):
        theme = SELECTOR.select("Адам анатомиясы")
        assert isinstance(theme, Theme)

    def test_theme_has_all_fields(self):
        theme = SELECTOR.select("technology AI software")
        for field in ("primary", "secondary", "accent", "background",
                      "text_dark", "text_light", "font_heading", "font_body"):
            val = getattr(theme, field)
            assert isinstance(val, str) and val, f"theme.{field} is empty"

    def test_theme_colors_are_hex(self):
        theme = SELECTOR.select("ocean marine water")
        for field in ("primary", "secondary", "accent", "background",
                      "text_dark", "text_light"):
            val = getattr(theme, field)
            assert _is_hex(val), f"theme.{field} = {val!r} is not valid hex"

    def test_select_with_profile_returns_tuple(self):
        result = SELECTOR.select_with_profile("history culture civilization")
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], Theme)
        assert isinstance(result[1], TopicProfile)

    def test_nature_theme_is_green_family(self):
        theme = SELECTOR.select("nature ecology forests")
        # Primary should be a green-ish hex: G channel > R and B
        h = theme.primary.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        assert g > r or g > b, f"Expected green-dominant primary, got {theme.primary}"

    def test_ocean_theme_is_blue_family(self):
        theme = SELECTOR.select("ocean marine aquatic water")
        h = theme.primary.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Blue or teal: B should be >= G or R should be low
        assert b >= g or r < 60, f"Expected blue/teal primary, got {theme.primary}"

    def test_deterministic_theme(self):
        t1 = SELECTOR.select("Жасанды интеллект технология")
        t2 = SELECTOR.select("Жасанды интеллект технология")
        assert t1.primary == t2.primary
        assert t1.accent == t2.accent


# ---------------------------------------------------------------------------
# 9. palette_to_theme adapter
# ---------------------------------------------------------------------------

class TestPaletteToTheme:
    def test_converts_all_palettes(self):
        for name, palette in _PALETTES.items():
            theme = palette_to_theme(palette)
            assert isinstance(theme, Theme), f"Failed for palette '{name}'"

    def test_custom_base_name(self):
        p = get_palette("ocean")
        theme = palette_to_theme(p, base_name="custom_name")
        assert theme.name == "custom_name"
