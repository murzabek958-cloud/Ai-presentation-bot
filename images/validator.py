"""
Image validation layer.

Every downloaded or generated image is validated before being passed
to the renderer. Invalid images are silently rejected — never shown
as broken placeholders.

Validation criteria:
- File exists and is non-empty
- Valid image format (JPEG, PNG, GIF, WEBP, BMP)
- Readable by PIL
- Minimum resolution (120×90)
- Reasonable aspect ratio (0.1 – 10.0)
- Reasonable file size (< 30 MB)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_WIDTH  = 120   # px
MIN_HEIGHT = 90    # px
MAX_FILE_BYTES = 30 * 1024 * 1024  # 30 MB
MIN_ASPECT = 0.1   # height/width must be > 0.1
MAX_ASPECT = 10.0  # and < 10.0

ALLOWED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "BMP"}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = ""

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, reason: str) -> "ValidationResult":
        return cls(valid=False, reason=reason)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_image(path: str | Path) -> ValidationResult:
    """
    Validate an image file before using it in the renderer.

    Returns ValidationResult(valid=True) on success.
    Returns ValidationResult(valid=False, reason=...) on any failure.

    Never raises — all exceptions are caught and reported as failures.
    """
    p = Path(path)

    # 1. File exists
    if not p.exists():
        return ValidationResult.fail(f"File does not exist: {p}")

    # 2. File size
    size = p.stat().st_size
    if size == 0:
        return ValidationResult.fail("File is empty (0 bytes)")
    if size > MAX_FILE_BYTES:
        return ValidationResult.fail(
            f"File too large: {size / 1_048_576:.1f} MB > {MAX_FILE_BYTES // 1_048_576} MB"
        )

    # 3. Try to open with PIL
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(str(p)) as img:
            img.verify()        # catches truncated / corrupt files
    except Exception as exc:
        return ValidationResult.fail(f"PIL cannot read image: {exc}")

    # Re-open after verify() (verify closes the file)
    try:
        from PIL import Image
        with Image.open(str(p)) as img:
            fmt    = img.format or ""
            width  = img.width
            height = img.height
    except Exception as exc:
        return ValidationResult.fail(f"PIL re-open failed: {exc}")

    # 4. Allowed format
    if fmt.upper() not in ALLOWED_FORMATS:
        return ValidationResult.fail(
            f"Unsupported format '{fmt}'. Allowed: {ALLOWED_FORMATS}"
        )

    # 5. Aspect ratio sanity
    aspect = height / width
    if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
        return ValidationResult.fail(
            f"Unreasonable aspect ratio: {aspect:.2f} "
            f"(allowed {MIN_ASPECT}–{MAX_ASPECT})"
        )

    # 6. Minimum resolution
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return ValidationResult.fail(
            f"Image too small: {width}×{height} (min {MIN_WIDTH}×{MIN_HEIGHT})"
        )

    logger.debug("Image valid: %s  %s  %dx%d", p.name, fmt, width, height)
    return ValidationResult.ok()
