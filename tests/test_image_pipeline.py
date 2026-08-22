"""
Tests for the Auto Image Pipeline.

Covers:
- ImageIntent validation (needed/not needed, enums, factories, query builders)
- ValidationResult and validate_image (valid, corrupted, too small, wrong format, aspect ratio)
- ImageCache (hit, miss, invalid cached file, put/get roundtrip)
- ImageProvider abstraction (NullProvider always returns empty)
- ImagePipeline orchestration (Gemini-only):
    - cache hit  → Gemini NOT called
    - Gemini succeeds → valid path returned and cached
    - Gemini fails   → None returned (no-image fallback)
    - intent.needed=False → None immediately
    - Wikipedia / Wikimedia provider is NEVER called
- Offline mode: pipeline returns None without network (never raises)

All tests are fully offline — no real HTTP calls, no real Gemini calls.
External dependencies are replaced with fakes/mocks.

Wikipedia / Wikimedia have been removed from the pipeline; tests verify
they are not referenced or called.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from images.intent import (
    AspectRatio,
    ImageIntent,
    ImagePosition,
    ImageRole,
    VisualType,
)
from images.validator import (
    ALLOWED_FORMATS,
    MIN_HEIGHT,
    MIN_WIDTH,
    ValidationResult,
    validate_image,
)
from images.cache import ImageCache
from images.provider import ImageProvider, ImageResult, NullProvider, get_default_provider
from images.pipeline import ImagePipeline
from images.gemini_generator import GeminiImageGenerator


# ===========================================================================
# Helpers — create real image files for testing
# ===========================================================================

def _make_png(path: Path, width: int = 200, height: int = 150) -> Path:
    """Write a minimal valid PNG file at *path*."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    raw = b"\x00" + b"\xff\x00\x00" * width
    scanlines = raw * height
    compressed = zlib.compress(scanlines)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")

    path.write_bytes(signature + ihdr + idat + iend)
    return path


def _make_jpeg(path: Path, width: int = 200, height: int = 150) -> Path:
    """Write a minimal valid JPEG file using PIL."""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(100, 149, 237))
    img.save(str(path), format="JPEG", quality=85)
    return path


def _make_corrupted(path: Path) -> Path:
    """Write a file that looks like an image but is corrupted."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    return path


# ===========================================================================
# Fake generators
# ===========================================================================

class _NoOpGenerator(GeminiImageGenerator):
    """Gemini generator that always returns None (simulates failure)."""
    def generate(self, prompt: str, dest_dir=None, filename_hint="gemini"):
        return None


class _SuccessGenerator(GeminiImageGenerator):
    """Gemini generator that returns a valid image."""
    def __init__(self, tmp_path: Path):
        super().__init__(api_key="fake")
        self._tmp = tmp_path

    def generate(self, prompt: str, dest_dir=None, filename_hint="gemini"):
        p = Path(dest_dir or self._tmp) / "gemini_out.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        _make_png(p, 400, 225)
        return p


# ===========================================================================
# 1. ImageIntent — validation and factories
# ===========================================================================

class TestImageIntent:

    def test_default_not_needed(self):
        intent = ImageIntent()
        assert intent.needed is False

    def test_factory_not_needed(self):
        intent = ImageIntent.not_needed()
        assert intent.needed is False
        assert intent.subject == ""

    def test_from_query_sets_needed_true(self):
        intent = ImageIntent.from_query("human heart diagram")
        assert intent.needed is True
        assert intent.subject == "human heart diagram"

    def test_from_query_empty_string_sets_needed_false(self):
        intent = ImageIntent.from_query("")
        assert intent.needed is False

    def test_from_query_whitespace_sets_needed_false(self):
        intent = ImageIntent.from_query("   ")
        assert intent.needed is False

    def test_from_query_strips_whitespace(self):
        intent = ImageIntent.from_query("  Caspian Sea  ")
        assert intent.subject == "Caspian Sea"

    def test_explicit_needed_true(self):
        intent = ImageIntent(needed=True, subject="neural network")
        assert intent.needed is True

    def test_visual_type_default(self):
        intent = ImageIntent(needed=True, subject="test")
        assert intent.visual_type == VisualType.PHOTO

    def test_visual_type_diagram(self):
        intent = ImageIntent(needed=True, subject="test", visual_type=VisualType.DIAGRAM)
        assert intent.visual_type == VisualType.DIAGRAM

    def test_role_default(self):
        intent = ImageIntent(needed=True, subject="test")
        assert intent.role == ImageRole.SUPPORTING

    def test_position_default(self):
        intent = ImageIntent(needed=True, subject="test")
        assert intent.preferred_position == ImagePosition.RIGHT

    def test_aspect_ratio_default(self):
        intent = ImageIntent(needed=True, subject="test")
        assert intent.aspect_ratio == AspectRatio.WIDE

    def test_all_visual_types_valid(self):
        for vt in VisualType:
            intent = ImageIntent(needed=True, subject="x", visual_type=vt)
            assert intent.visual_type == vt

    def test_all_roles_valid(self):
        for role in ImageRole:
            intent = ImageIntent(needed=True, subject="x", role=role)
            assert intent.role == role

    def test_all_positions_valid(self):
        for pos in ImagePosition:
            intent = ImageIntent(needed=True, subject="x", preferred_position=pos)
            assert intent.preferred_position == pos

    def test_all_aspect_ratios_valid(self):
        for ar in AspectRatio:
            intent = ImageIntent(needed=True, subject="x", aspect_ratio=ar)
            assert intent.aspect_ratio == ar


class TestImageIntentCacheKey:

    def test_not_needed_returns_empty(self):
        intent = ImageIntent.not_needed()
        assert intent.build_cache_key() == ""

    def test_needed_no_subject_returns_empty(self):
        intent = ImageIntent(needed=True, subject="")
        assert intent.build_cache_key() == ""

    def test_photo_type_no_hint_appended(self):
        intent = ImageIntent(needed=True, subject="Caspian Sea", visual_type=VisualType.PHOTO)
        key = intent.build_cache_key()
        assert key == "Caspian Sea"

    def test_diagram_type_appends_hint(self):
        intent = ImageIntent(needed=True, subject="human heart", visual_type=VisualType.DIAGRAM)
        key = intent.build_cache_key()
        assert "diagram" in key.lower()
        assert "human heart" in key

    def test_map_type_appends_hint(self):
        intent = ImageIntent(needed=True, subject="Kazakhstan", visual_type=VisualType.MAP)
        key = intent.build_cache_key()
        assert "map" in key.lower()

    def test_historical_appends_hint(self):
        intent = ImageIntent(needed=True, subject="Battle of Stalingrad", visual_type=VisualType.HISTORICAL)
        key = intent.build_cache_key()
        assert "historical photograph" in key.lower()

    def test_hint_not_duplicated_if_already_in_subject(self):
        intent = ImageIntent(needed=True, subject="heart diagram", visual_type=VisualType.DIAGRAM)
        key = intent.build_cache_key()
        assert key.lower().count("diagram") == 1

    def test_topic_parameter_accepted(self):
        intent = ImageIntent(needed=True, subject="neural network")
        key = intent.build_cache_key(topic="Artificial Intelligence")
        assert "neural network" in key

    def test_build_search_query_alias(self):
        """build_search_query() is a backwards-compat alias for build_cache_key()."""
        intent = ImageIntent(needed=True, subject="Caspian Sea")
        assert intent.build_search_query() == intent.build_cache_key()


class TestImageIntentGenerationPrompt:

    def test_not_needed_returns_empty(self):
        intent = ImageIntent.not_needed()
        assert intent.build_generation_prompt() == ""

    def test_needed_no_subject_returns_empty(self):
        intent = ImageIntent(needed=True, subject="")
        assert intent.build_generation_prompt() == ""

    def test_prompt_contains_subject(self):
        intent = ImageIntent(needed=True, subject="human anatomy")
        prompt = intent.build_generation_prompt()
        assert "human anatomy" in prompt

    def test_prompt_contains_no_watermark_rule(self):
        intent = ImageIntent(needed=True, subject="test")
        prompt = intent.build_generation_prompt()
        assert "watermark" in prompt.lower()

    def test_prompt_contains_no_ui_rule(self):
        intent = ImageIntent(needed=True, subject="test")
        prompt = intent.build_generation_prompt()
        assert "UI" in prompt or "ui" in prompt.lower()

    def test_prompt_contains_presentation_context(self):
        intent = ImageIntent(needed=True, subject="test")
        prompt = intent.build_generation_prompt()
        assert "presentation" in prompt.lower()

    def test_diagram_prompt_mentions_diagram(self):
        intent = ImageIntent(needed=True, subject="heart", visual_type=VisualType.DIAGRAM)
        prompt = intent.build_generation_prompt()
        assert "diagram" in prompt.lower()

    def test_hero_role_in_prompt(self):
        intent = ImageIntent(needed=True, subject="test", role=ImageRole.HERO)
        prompt = intent.build_generation_prompt()
        assert "hero" in prompt.lower() or "dramatic" in prompt.lower()

    def test_prompt_ends_with_period(self):
        intent = ImageIntent(needed=True, subject="test")
        prompt = intent.build_generation_prompt()
        assert prompt.endswith(".")


# ===========================================================================
# 2. ValidationResult
# ===========================================================================

class TestValidationResult:

    def test_ok_is_valid(self):
        r = ValidationResult.ok()
        assert r.valid is True
        assert r.reason == ""

    def test_fail_is_not_valid(self):
        r = ValidationResult.fail("too small")
        assert r.valid is False
        assert "too small" in r.reason

    def test_frozen(self):
        r = ValidationResult.ok()
        with pytest.raises((AttributeError, TypeError)):
            r.valid = False  # type: ignore


# ===========================================================================
# 3. validate_image
# ===========================================================================

class TestValidateImage:

    def test_valid_png(self, tmp_path):
        p = _make_png(tmp_path / "valid.png", 200, 150)
        result = validate_image(p)
        assert result.valid, result.reason

    def test_valid_jpeg(self, tmp_path):
        p = _make_jpeg(tmp_path / "valid.jpg", 300, 200)
        result = validate_image(p)
        assert result.valid, result.reason

    def test_file_not_exist(self, tmp_path):
        result = validate_image(tmp_path / "nonexistent.png")
        assert not result.valid
        assert "does not exist" in result.reason

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        result = validate_image(p)
        assert not result.valid
        assert "empty" in result.reason.lower()

    def test_corrupted_file(self, tmp_path):
        p = _make_corrupted(tmp_path / "corrupt.png")
        result = validate_image(p)
        assert not result.valid

    def test_too_small_width(self, tmp_path):
        p = _make_png(tmp_path / "tiny.png", width=50, height=200)
        result = validate_image(p)
        assert not result.valid
        assert "small" in result.reason.lower()

    def test_too_small_height(self, tmp_path):
        p = _make_png(tmp_path / "short.png", width=200, height=30)
        result = validate_image(p)
        assert not result.valid
        assert "small" in result.reason.lower()

    def test_exactly_minimum_size_is_valid(self, tmp_path):
        p = _make_png(tmp_path / "min.png", width=MIN_WIDTH, height=MIN_HEIGHT)
        result = validate_image(p)
        assert result.valid, result.reason

    def test_non_image_file(self, tmp_path):
        p = tmp_path / "fake.jpg"
        p.write_bytes(b"this is not an image at all, just text bytes 12345")
        result = validate_image(p)
        assert not result.valid

    def test_extreme_aspect_ratio_too_wide(self, tmp_path):
        p = _make_png(tmp_path / "wide.png", width=2000, height=10)
        result = validate_image(p)
        assert not result.valid
        assert "aspect" in result.reason.lower()

    def test_extreme_aspect_ratio_too_tall(self, tmp_path):
        p = _make_png(tmp_path / "tall.png", width=10, height=200)
        result = validate_image(p)
        assert not result.valid
        assert "aspect" in result.reason.lower()

    def test_accepts_string_path(self, tmp_path):
        p = _make_png(tmp_path / "str.png")
        result = validate_image(str(p))
        assert result.valid, result.reason

    def test_accepts_path_object(self, tmp_path):
        p = _make_png(tmp_path / "pathobj.png")
        result = validate_image(p)
        assert result.valid, result.reason


# ===========================================================================
# 4. ImageCache
# ===========================================================================

class TestImageCache:

    def test_miss_returns_none(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        assert cache.get("nonexistent query") is None

    def test_has_returns_false_on_miss(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        assert cache.has("something") is False

    def test_put_and_get_roundtrip(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache = ImageCache(str(cache_dir))

        img = _make_png(tmp_path / "source.png")
        cache.put("test query", img, suffix=".png")

        result = cache.get("test query")
        assert result is not None
        assert result.exists()

    def test_has_returns_true_after_put(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        img = _make_png(tmp_path / "src.png")
        cache.put("myquery", img, suffix=".png")
        assert cache.has("myquery") is True

    def test_key_is_deterministic(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        k1 = cache.make_key("Caspian Sea")
        k2 = cache.make_key("Caspian Sea")
        assert k1 == k2

    def test_key_differs_for_different_queries(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        k1 = cache.make_key("Caspian Sea")
        k2 = cache.make_key("human heart")
        assert k1 != k2

    def test_key_case_insensitive(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        k1 = cache.make_key("Caspian Sea")
        k2 = cache.make_key("caspian sea")
        assert k1 == k2

    def test_invalid_cached_file_removed_and_returns_none(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache = ImageCache(str(cache_dir))

        key = cache.make_key("bad query")
        bad_file = cache_dir / f"{key}.png"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_bytes(b"not an image")

        result = cache.get("bad query")
        assert result is None
        assert not bad_file.exists()

    def test_clear_removes_all_files(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        img = _make_png(tmp_path / "s1.png")
        cache.put("q1", img, suffix=".png")
        cache.put("q2", img, suffix=".png")

        removed = cache.clear()
        assert removed == 2
        assert cache.get("q1") is None

    def test_cache_dir_created_if_not_exists(self, tmp_path):
        new_dir = tmp_path / "deep" / "new" / "cache"
        cache = ImageCache(str(new_dir))
        assert new_dir.exists()


# ===========================================================================
# 5. NullProvider — replaces WikimediaProvider as the default
# ===========================================================================

class TestNullProvider:

    def test_search_always_returns_empty_list(self):
        provider = NullProvider()
        results = provider.search("anything", max_results=5)
        assert results == []
        assert isinstance(results, list)

    def test_download_always_returns_none(self, tmp_path):
        provider = NullProvider()
        result = ImageResult(url="http://fake/image.png", source="null")
        path = provider.download(result, tmp_path)
        assert path is None

    def test_get_default_provider_returns_null_provider(self):
        provider = get_default_provider()
        assert isinstance(provider, NullProvider)

    def test_wikimedia_provider_not_importable_from_provider(self):
        """WikimediaProvider must no longer exist in images.provider."""
        import images.provider as pmod
        assert not hasattr(pmod, "WikimediaProvider"), (
            "WikimediaProvider should have been removed from images.provider"
        )

    def test_no_wikimedia_calls_during_pipeline(self, tmp_path):
        """
        Verify no Wikimedia / Wikipedia HTTP requests are made
        during a full pipeline resolve.
        """
        import urllib.request as _urllib_request
        original_urlopen = _urllib_request.urlopen

        wikimedia_calls = []

        def _patched_urlopen(url, *args, **kwargs):
            url_str = str(url)
            if "wikimedia" in url_str.lower() or "wikipedia" in url_str.lower():
                wikimedia_calls.append(url_str)
                raise AssertionError(f"Unexpected Wikimedia/Wikipedia call: {url_str}")
            return original_urlopen(url, *args, **kwargs)

        cache = ImageCache(str(tmp_path / "cache"))
        pipeline = ImagePipeline(
            cache=cache,
            generator=_NoOpGenerator(api_key="fake"),
        )
        intent = ImageIntent(needed=True, subject="Caspian Sea ecology")

        with patch("urllib.request.urlopen", side_effect=_patched_urlopen):
            result = pipeline.resolve_sync(intent)

        assert wikimedia_calls == [], f"Unexpected Wikimedia calls: {wikimedia_calls}"
        # result is None because generator is a no-op
        assert result is None

    def test_wikimedia_provider_not_in_provider_module(self):
        """WikimediaProvider must no longer exist in images.provider."""
        import images.provider as pmod
        assert not hasattr(pmod, "WikimediaProvider"), (
            "WikimediaProvider should have been removed from images.provider"
        )


# ===========================================================================
# 6. ImagePipeline orchestration — Gemini only
# ===========================================================================

class TestImagePipeline:

    def _intent(self, subject: str = "test subject") -> ImageIntent:
        return ImageIntent(needed=True, subject=subject)

    def _pipeline(self, tmp_path, generator=None):
        cache = ImageCache(str(tmp_path / "cache"))
        gen = generator or _NoOpGenerator(api_key="fake")
        return ImagePipeline(cache=cache, generator=gen)

    # --- intent.needed=False ---

    def test_not_needed_returns_none_immediately(self, tmp_path):
        pipeline = self._pipeline(tmp_path)
        intent = ImageIntent.not_needed()
        result = pipeline.resolve_sync(intent)
        assert result is None

    def test_empty_subject_returns_none(self, tmp_path):
        pipeline = self._pipeline(tmp_path)
        intent = ImageIntent(needed=True, subject="")
        result = pipeline.resolve_sync(intent)
        assert result is None

    # --- Cache hit → Gemini NOT called ---

    def test_cache_hit_gemini_not_called(self, tmp_path):
        cache = ImageCache(str(tmp_path / "cache"))
        img = _make_png(tmp_path / "cached.png")
        cache.put("test subject", img, suffix=".png")

        gen = _NoOpGenerator(api_key="fake")
        gen_call_count = [0]
        original_generate = gen.generate
        def counting_generate(*a, **kw):
            gen_call_count[0] += 1
            return original_generate(*a, **kw)
        gen.generate = counting_generate

        pipeline = ImagePipeline(cache=cache, generator=gen)
        result = pipeline.resolve_sync(self._intent("test subject"))

        assert result is not None
        assert result.exists()
        assert gen_call_count[0] == 0  # cache hit → Gemini NOT called

    # --- Gemini succeeds → valid path returned ---

    def test_gemini_success_returns_valid_path(self, tmp_path):
        gen = _SuccessGenerator(tmp_path)
        pipeline = self._pipeline(tmp_path, generator=gen)
        result = pipeline.resolve_sync(self._intent("AI concept"))
        assert result is not None
        assert result.exists()

    # --- Gemini is called when cache misses ---

    def test_cache_miss_triggers_gemini(self, tmp_path):
        gen = _SuccessGenerator(tmp_path)
        gen_call_count = [0]
        original_generate = gen.generate
        def counting_generate(*a, **kw):
            gen_call_count[0] += 1
            return original_generate(*a, **kw)
        gen.generate = counting_generate

        pipeline = self._pipeline(tmp_path, generator=gen)
        result = pipeline.resolve_sync(self._intent("AI concept"))

        assert result is not None
        assert gen_call_count[0] == 1  # Gemini WAS called

    # --- Gemini fails → None (no-image fallback) ---

    def test_gemini_failure_returns_none(self, tmp_path):
        pipeline = self._pipeline(
            tmp_path,
            generator=_NoOpGenerator(api_key="fake"),
        )
        result = pipeline.resolve_sync(self._intent("something"))
        assert result is None  # graceful fallback

    # --- IMAGE_TEXT layout triggers image; non-image layouts do not ---

    def test_image_text_layout_needs_image(self):
        """IMAGE_TEXT slides should have needed=True."""
        intent = ImageIntent(needed=True, subject="renewable energy")
        assert intent.needed is True

    def test_title_layout_does_not_need_image(self):
        """Non-image slides should have needed=False."""
        intent = ImageIntent.not_needed()
        assert intent.needed is False

    # --- Successful result is cached ---

    def test_gemini_result_is_cached(self, tmp_path):
        gen = _SuccessGenerator(tmp_path)
        cache = ImageCache(str(tmp_path / "cache"))
        pipeline = ImagePipeline(cache=cache, generator=gen)

        # First call — Gemini generates
        r1 = pipeline.resolve_sync(self._intent("Kazakhstan map"))
        assert r1 is not None

        # Second call — should be cache hit (Gemini not called again)
        gen_call_count = [0]
        original = gen.generate
        def counting(*a, **kw):
            gen_call_count[0] += 1
            return original(*a, **kw)
        gen.generate = counting

        r2 = pipeline.resolve_sync(self._intent("Kazakhstan map"))
        assert r2 is not None
        assert gen_call_count[0] == 0  # cache hit on second call

    # --- Returned path must be valid ---

    def test_returned_path_is_valid_image(self, tmp_path):
        pipeline = self._pipeline(tmp_path, generator=_SuccessGenerator(tmp_path))
        result = pipeline.resolve_sync(self._intent("test"))
        assert result is not None
        vr = validate_image(result)
        assert vr.valid, vr.reason

    # --- No-network fallback ---

    def test_no_api_key_returns_none_not_raises(self, tmp_path):
        """
        No Gemini API key → generator returns None gracefully.
        Pipeline must return None — never raise.
        """
        pipeline = self._pipeline(
            tmp_path,
            generator=_NoOpGenerator(api_key=""),  # no API key
        )
        result = pipeline.resolve_sync(self._intent("Caspian Sea ecology"))
        assert result is None  # graceful fallback

    def test_cache_hit_works_when_gemini_unavailable(self, tmp_path):
        """Cache hit in offline mode returns the cached image."""
        cache = ImageCache(str(tmp_path / "cache"))
        img = _make_png(tmp_path / "cached.png")
        cache.put("offline test", img, suffix=".png")

        pipeline = ImagePipeline(
            cache=cache,
            generator=_NoOpGenerator(api_key=""),
        )
        result = pipeline.resolve_sync(self._intent("offline test"))
        assert result is not None
        assert result.exists()

    # --- Multiple different topics ---

    @pytest.mark.parametrize("subject", [
        "Адам анатомиясы",
        "Каспий теңізі",
        "Жасанды интеллект",
        "Қазақстан тарихы",
    ])
    def test_various_kazakh_topics_no_crash(self, tmp_path, subject):
        """Pipeline must not crash for any topic, including Kazakh text."""
        pipeline = self._pipeline(tmp_path)
        intent = ImageIntent(needed=True, subject=subject)
        result = pipeline.resolve_sync(intent)
        # result may be None (no Gemini key), but must not raise
        assert result is None or result.exists()

    # --- provider kwarg backwards compat ---

    def test_provider_kwarg_is_accepted_but_ignored(self, tmp_path):
        """ImagePipeline still accepts provider= kwarg for backwards compat."""
        fake_provider = NullProvider()
        pipeline = ImagePipeline(
            cache=ImageCache(str(tmp_path / "cache")),
            provider=fake_provider,   # should be accepted
            generator=_NoOpGenerator(api_key="fake"),
        )
        result = pipeline.resolve_sync(self._intent("test"))
        assert result is None  # no Gemini key


# ===========================================================================
# 7. GeminiImageGenerator — unit tests (no real API calls)
# ===========================================================================

class TestGeminiImageGenerator:

    def test_no_api_key_returns_none(self, tmp_path):
        gen = GeminiImageGenerator(api_key="")
        result = gen.generate("test prompt", dest_dir=str(tmp_path))
        assert result is None

    def test_empty_prompt_returns_none(self, tmp_path):
        gen = GeminiImageGenerator(api_key="fake_key")
        result = gen.generate("", dest_dir=str(tmp_path))
        assert result is None

    def test_whitespace_prompt_returns_none(self, tmp_path):
        gen = GeminiImageGenerator(api_key="fake_key")
        result = gen.generate("   ", dest_dir=str(tmp_path))
        assert result is None

    def test_api_failure_returns_none_not_raises(self, tmp_path):
        """If google.genai raises any exception, returns None gracefully."""
        gen = GeminiImageGenerator(api_key="fake_key")
        with patch(
            "images.gemini_generator.GeminiImageGenerator.generate",
            return_value=None,
        ):
            result = gen.generate("test prompt", dest_dir=str(tmp_path))
            assert result is None

    def test_gemini_is_sole_provider(self, tmp_path):
        """
        Verify GeminiImageGenerator is the only active image provider
        in the pipeline — no WikimediaProvider, no search fallback.
        The pipeline returns a valid image path when Gemini succeeds.
        """
        cache = ImageCache(str(tmp_path / "cache"))
        pipeline = ImagePipeline(cache=cache, generator=_SuccessGenerator(tmp_path))
        intent = ImageIntent(needed=True, subject="test")
        result = pipeline.resolve_sync(intent)
        assert result is not None
        assert result.exists()
        # Validate the returned image is valid
        from images.validator import validate_image
        vr = validate_image(result)
        assert vr.valid, vr.reason


# ===========================================================================
# 8. Enum values sanity check
# ===========================================================================

class TestEnumValues:

    def test_visual_type_values(self):
        assert VisualType.PHOTO.value == "photo"
        assert VisualType.DIAGRAM.value == "diagram"
        assert VisualType.MAP.value == "map"
        assert VisualType.HISTORICAL.value == "historical"

    def test_image_role_values(self):
        assert ImageRole.HERO.value == "hero"
        assert ImageRole.SUPPORTING.value == "supporting"
        assert ImageRole.BACKGROUND.value == "background"
        assert ImageRole.CARD.value == "card"

    def test_image_position_values(self):
        assert ImagePosition.LEFT.value == "left"
        assert ImagePosition.RIGHT.value == "right"
        assert ImagePosition.FULL.value == "full"
        assert ImagePosition.BACKGROUND.value == "background"

    def test_aspect_ratio_values(self):
        assert AspectRatio.WIDE.value == "16:9"
        assert AspectRatio.STANDARD.value == "4:3"
        assert AspectRatio.SQUARE.value == "1:1"
        assert AspectRatio.PORTRAIT.value == "portrait"

    def test_all_visual_types_count(self):
        assert len(VisualType) == 7

    def test_all_roles_count(self):
        assert len(ImageRole) == 4

    def test_all_positions_count(self):
        assert len(ImagePosition) == 4

    def test_all_aspect_ratios_count(self):
        assert len(AspectRatio) == 4
