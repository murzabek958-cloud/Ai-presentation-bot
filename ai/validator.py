"""
Validate a generated PresentationPlan against the user's PresentationRequirements.

Rules:
- Each violated requirement produces a clear error message.
- Validator does NOT modify the plan — it only checks it.
- Existing PresentationPlan Pydantic validation continues to run separately.
"""
from dataclasses import dataclass, field

from ai.schemas import PresentationPlan, PresentationRequirements, SlideLayout


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool = True
    errors: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.passed = False
        self.errors.append(message)

    def summary(self) -> str:
        if self.passed:
            return "OK"
        return "\n".join(f"• {e}" for e in self.errors)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class RequirementsValidator:
    """
    Check that a PresentationPlan satisfies a PresentationRequirements.
    Call validate() and inspect the returned ValidationResult.
    """

    def validate(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
    ) -> ValidationResult:
        result = ValidationResult()

        self._check_slide_count(plan, reqs, result)
        self._check_language(plan, reqs, result)
        self._check_style(plan, reqs, result)
        self._check_conclusion(plan, reqs, result)
        self._check_statistics(plan, reqs, result)
        self._check_images(plan, reqs, result)

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_slide_count(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if reqs.slide_count is None:
            return
        if plan.slide_count != reqs.slide_count:
            result.fail(
                f"Slide count mismatch: requested {reqs.slide_count}, "
                f"got {plan.slide_count}."
            )

    def _check_language(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if reqs.language is None:
            return
        if plan.metadata.language != reqs.language:
            result.fail(
                f"Language mismatch: requested '{reqs.language}', "
                f"got '{plan.metadata.language}'."
            )

    def _check_style(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if reqs.style is None:
            return
        if plan.style != reqs.style:
            result.fail(
                f"Style mismatch: requested '{reqs.style}', got '{plan.style}'."
            )

    def _check_conclusion(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if not reqs.require_conclusion:
            return
        layouts = [s.layout for s in plan.slides]
        if SlideLayout.CONCLUSION not in layouts:
            result.fail(
                "User requested a conclusion slide, but none was generated."
            )

    def _check_statistics(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if not reqs.require_statistics:
            return
        stat_layouts = {SlideLayout.STATISTICS, SlideLayout.CHART}
        has_stats = any(s.layout in stat_layouts for s in plan.slides)
        if not has_stats:
            result.fail(
                "User requested statistics/data slides, "
                "but no 'statistics' or 'chart' layout was generated."
            )

    def _check_images(
        self,
        plan: PresentationPlan,
        reqs: PresentationRequirements,
        result: ValidationResult,
    ) -> None:
        if reqs.include_images:
            return   # images are allowed — nothing to check
        slides_with_images = [
            s.index for s in plan.slides if s.image_query
        ]
        if slides_with_images:
            result.fail(
                f"User requested no images, but image queries were generated "
                f"for slide(s): {slides_with_images}."
            )
