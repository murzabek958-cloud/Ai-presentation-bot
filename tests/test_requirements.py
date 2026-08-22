"""
Offline tests for PresentationRequirements and RequirementsValidator.

No Gemini API calls are made — all tests construct plans manually.
"""
from datetime import datetime

import pytest

from ai.schemas import (
    PlanMetadata,
    PresentationPlan,
    PresentationRequirements,
    SlideData,
    SlideLayout,
)
from ai.validator import RequirementsValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(
    slide_layouts: list[SlideLayout],
    language: str = "kk",
    style: str = "academic",
    topic: str = "Test topic",
    image_queries: list[str | None] | None = None,
) -> PresentationPlan:
    """Build a minimal valid PresentationPlan from a list of layouts."""
    if image_queries is None:
        image_queries = [None] * len(slide_layouts)

    slides = [
        SlideData(
            index=i,
            layout=layout,
            title=f"Slide {i}",
            content={},
            image_query=image_queries[i],
        )
        for i, layout in enumerate(slide_layouts)
    ]
    return PresentationPlan(
        topic=topic,
        style=style,
        slide_count=len(slides),
        slides=slides,
        metadata=PlanMetadata(
            language=language,
            generated_at=datetime.utcnow(),
        ),
    )


validator = RequirementsValidator()


# ---------------------------------------------------------------------------
# Test 1: Kazakh request — 8 slides
# ---------------------------------------------------------------------------

def test_kazakh_8_slides_pass():
    """Plan with exactly 8 slides in kk satisfies those requirements."""
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE] + [SlideLayout.TITLE_TEXT] * 6 + [SlideLayout.CONCLUSION],
        language="kk",
    )
    reqs = PresentationRequirements(slide_count=8, language="kk")
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_kazakh_8_slides_wrong_count_fails():
    reqs = PresentationRequirements(slide_count=8, language="kk")
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE] + [SlideLayout.TITLE_TEXT] * 4 + [SlideLayout.CONCLUSION],
        language="kk",
    )
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert "Slide count mismatch" in result.summary()


# ---------------------------------------------------------------------------
# Test 2: Russian request — 10 slides
# ---------------------------------------------------------------------------

def test_russian_10_slides_pass():
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE] + [SlideLayout.TITLE_TEXT] * 8 + [SlideLayout.CONCLUSION],
        language="ru",
    )
    reqs = PresentationRequirements(slide_count=10, language="ru")
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_russian_10_slides_wrong_language_fails():
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE] + [SlideLayout.TITLE_TEXT] * 8 + [SlideLayout.CONCLUSION],
        language="kk",   # wrong
    )
    reqs = PresentationRequirements(slide_count=10, language="ru")
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert "Language mismatch" in result.summary()


# ---------------------------------------------------------------------------
# Test 3: Require statistics
# ---------------------------------------------------------------------------

def test_statistics_required_and_present_passes():
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.TITLE_TEXT,
            SlideLayout.STATISTICS,
            SlideLayout.CONCLUSION,
        ]
    )
    reqs = PresentationRequirements(require_statistics=True)
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_chart_satisfies_statistics_requirement():
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.CHART,
            SlideLayout.CONCLUSION,
        ]
    )
    reqs = PresentationRequirements(require_statistics=True)
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_statistics_required_but_missing_fails():
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.TITLE_TEXT,
            SlideLayout.CONCLUSION,
        ]
    )
    reqs = PresentationRequirements(require_statistics=True)
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert "statistics" in result.summary().lower()


# ---------------------------------------------------------------------------
# Test 4: Require conclusion
# ---------------------------------------------------------------------------

def test_conclusion_required_and_present_passes():
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.TITLE_TEXT,
            SlideLayout.CONCLUSION,
        ]
    )
    reqs = PresentationRequirements(require_conclusion=True)
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_conclusion_required_but_missing_fails():
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.TITLE_TEXT,
            SlideLayout.TITLE_TEXT,
        ]
    )
    reqs = PresentationRequirements(require_conclusion=True)
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert "conclusion" in result.summary().lower()


# ---------------------------------------------------------------------------
# Test 5: No images requested
# ---------------------------------------------------------------------------

def test_no_images_requested_and_none_generated_passes():
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE, SlideLayout.TITLE_TEXT, SlideLayout.CONCLUSION],
        image_queries=[None, None, None],
    )
    reqs = PresentationRequirements(include_images=False)
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_no_images_requested_but_present_fails():
    plan = _make_plan(
        slide_layouts=[SlideLayout.TITLE, SlideLayout.IMAGE_TEXT, SlideLayout.CONCLUSION],
        image_queries=[None, "sunset photo", None],
    )
    reqs = PresentationRequirements(include_images=False)
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert "image" in result.summary().lower()


# ---------------------------------------------------------------------------
# Test 6: Multiple requirements simultaneously
# ---------------------------------------------------------------------------

def test_multiple_requirements_all_satisfied():
    """
    10 slides, kk, academic, conclusion required, statistics required, no images.
    """
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.TITLE_TEXT,
            SlideLayout.STATISTICS,
            SlideLayout.TITLE_TEXT,
            SlideLayout.TWO_COLUMNS,
            SlideLayout.TITLE_TEXT,
            SlideLayout.CHART,
            SlideLayout.TITLE_TEXT,
            SlideLayout.QUOTE,
            SlideLayout.CONCLUSION,
        ],
        language="kk",
        style="academic",
        image_queries=[None] * 10,
    )
    reqs = PresentationRequirements(
        slide_count=10,
        language="kk",
        style="academic",
        require_conclusion=True,
        require_statistics=True,
        include_images=False,
    )
    result = validator.validate(plan, reqs)
    assert result.passed, result.summary()


def test_multiple_requirements_partial_failure():
    """
    Same requirements, but conclusion is missing and image is present → 2 errors.
    """
    plan = _make_plan(
        slide_layouts=[
            SlideLayout.TITLE,
            SlideLayout.STATISTICS,
            SlideLayout.IMAGE_TEXT,   # image present — violates include_images=False
            SlideLayout.TITLE_TEXT,
            SlideLayout.TWO_COLUMNS,
            SlideLayout.TITLE_TEXT,
            SlideLayout.CHART,
            SlideLayout.TITLE_TEXT,
            SlideLayout.QUOTE,
            SlideLayout.TITLE_TEXT,  # no CONCLUSION — violates require_conclusion
        ],
        language="kk",
        style="academic",
        image_queries=[None, None, "mountains", None, None, None, None, None, None, None],
    )
    reqs = PresentationRequirements(
        slide_count=10,
        language="kk",
        style="academic",
        require_conclusion=True,
        require_statistics=True,
        include_images=False,
    )
    result = validator.validate(plan, reqs)
    assert not result.passed
    assert len(result.errors) == 2
    topics = result.summary().lower()
    assert "conclusion" in topics
    assert "image" in topics


# ---------------------------------------------------------------------------
# Test 7: build_user_prompt — requirements reach the prompt text
# ---------------------------------------------------------------------------

from ai.prompts import build_user_prompt


def test_prompt_baseline_no_requirements():
    """Default call produces no USER REQUIREMENTS block."""
    prompt = build_user_prompt(
        topic="Climate change",
        slide_count=8,
        language="kk",
        style="academic",
    )
    assert "USER REQUIREMENTS" not in prompt
    assert "MANDATORY" not in prompt
    assert "Topic: Climate change" in prompt
    assert "Number of slides: 8" in prompt
    assert "Language: kk" in prompt


def test_prompt_require_conclusion_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        require_conclusion=True,
    )
    assert "USER REQUIREMENTS" in prompt
    assert "conclusion" in prompt.lower()
    assert "MANDATORY" in prompt


def test_prompt_require_statistics_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        require_statistics=True,
    )
    assert "statistics" in prompt.lower() or "chart" in prompt.lower()
    assert "MANDATORY" in prompt


def test_prompt_require_sources_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        require_sources=True,
    )
    assert "source" in prompt.lower() or "citation" in prompt.lower()
    assert "MANDATORY" in prompt


def test_prompt_no_images_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        include_images=False,
    )
    assert "image_query" in prompt.lower()
    assert "null" in prompt.lower()
    assert "MANDATORY" in prompt


def test_prompt_max_text_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        max_text_per_slide=True,
    )
    assert "minimal" in prompt.lower() or "max" in prompt.lower()
    assert "MANDATORY" in prompt


def test_prompt_extra_instructions_present():
    prompt = build_user_prompt(
        topic="AI", slide_count=8, language="kk", style="academic",
        extra_instructions="Use bullet points only, no paragraphs.",
    )
    assert "Use bullet points only, no paragraphs." in prompt
    assert "ADDITIONAL USER INSTRUCTION" in prompt


def test_prompt_all_requirements_simultaneously():
    """
    All flags set — prompt must contain every requirement block.
    Mirrors: "10 слайд, қазақша, академиялық, статистика, дереккөздер,
              мәтін аз, қорытынды, сурет жоқ"
    """
    prompt = build_user_prompt(
        topic="Жасанды интеллект және білім беру",
        slide_count=10,
        language="kk",
        style="academic",
        require_conclusion=True,
        require_statistics=True,
        require_sources=True,
        include_images=False,
        max_text_per_slide=True,
        extra_instructions="Соңғы слайдта пайдаланылған әдебиеттер тізімін көрсет.",
    )
    prompt_lower = prompt.lower()
    assert "number of slides: 10" in prompt_lower
    assert "language: kk" in prompt_lower
    assert "conclusion" in prompt_lower
    assert "statistics" in prompt_lower or "chart" in prompt_lower
    assert "source" in prompt_lower or "citation" in prompt_lower
    assert "image_query" in prompt_lower
    assert "minimal" in prompt_lower or "max" in prompt_lower
    assert "Соңғы слайдта пайдаланылған әдебиеттер тізімін көрсет." in prompt
    assert prompt.count("MANDATORY") >= 5
