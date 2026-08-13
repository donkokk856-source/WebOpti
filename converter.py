"""Image discovery and controlled, lossily compressed WebP conversion."""

from __future__ import annotations

import logging
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps, UnidentifiedImageError

from config import SUPPORTED_EXTENSIONS

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversionOptions:
    """Settings shared by every conversion job."""

    quality: int
    max_width: int | None
    max_height: int | None
    overwrite: bool


@dataclass
class ConversionResult:
    """The result and size information from one source file."""

    source: Path
    destination: Path
    status: str  # success, failed, skipped
    message: str = ""
    input_size: int = 0
    output_size: int = 0
    input_dimensions: tuple[int, int] | None = None
    output_dimensions: tuple[int, int] | None = None


def find_images(input_dir: Path) -> list[Path]:
    """Return supported image paths below *input_dir* in stable order."""
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda path: str(path).lower(),
    )


def output_path(source: Path, input_dir: Path, output_dir: Path) -> Path:
    """Keep the source's relative folder and filename, changing only its suffix."""
    return output_dir / source.relative_to(input_dir).with_suffix(".webp")


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def _resize_if_needed(image: Image.Image, max_width: int | None, max_height: int | None) -> Image.Image:
    """Downscale to fit optional bounds, without ever enlarging an image."""
    width, height = image.size
    ratios = [1.0]
    if max_width is not None:
        ratios.append(max_width / width)
    if max_height is not None:
        ratios.append(max_height / height)
    ratio = min(ratios)
    if ratio >= 1.0:
        return image
    new_size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def convert_image(source: Path, destination: Path, options: ConversionOptions) -> ConversionResult:
    """Validate and convert a single image, leaving the destination untouched on failure."""
    try:
        source_size = source.stat().st_size
        if destination.exists() and not options.overwrite:
            message = "output already exists (use --overwrite to replace it)"
            LOGGER.info("SKIPPED input=%s output=%s reason=%s", source, destination, message)
            return ConversionResult(source, destination, "skipped", message, input_size=source_size)

        # verify() catches malformed files before doing the real decode below.
        with Image.open(source) as verification_image:
            verification_image.verify()

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened_image:
                image = ImageOps.exif_transpose(opened_image)
                image.load()  # Decode while the source file is still open.

                original_dimensions = image.size
                has_alpha = _has_transparency(image)
                image = _resize_if_needed(image, options.max_width, options.max_height)
                # WebP accepts RGB/RGBA cleanly. Conversion also removes EXIF and other source metadata.
                image = image.convert("RGBA" if has_alpha else "RGB")
                final_dimensions = image.size

                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.{time.time_ns()}.tmp.webp")
                try:
                    image.save(
                        temporary,
                        format="WEBP",
                        quality=options.quality,
                        method=6,
                        lossless=False,
                    )
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        temporary.unlink()

        result = ConversionResult(
            source, destination, "success", input_size=source_size,
            output_size=destination.stat().st_size, input_dimensions=original_dimensions,
            output_dimensions=final_dimensions,
        )
        LOGGER.info(
            "SUCCESS input=%s output=%s input_dimensions=%s output_dimensions=%s input_bytes=%d output_bytes=%d",
            source, destination, original_dimensions, final_dimensions, result.input_size, result.output_size,
        )
        return result
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        message = str(error) or error.__class__.__name__
        LOGGER.exception("FAILED input=%s output=%s error=%s", source, destination, message)
        return ConversionResult(source, destination, "failed", message)


def process_images(
    images: list[Path], input_dir: Path, output_dir: Path, options: ConversionOptions,
    workers: int, progress: Callable[[int, int, ConversionResult], None],
) -> list[ConversionResult]:
    """Convert files with a bounded worker pool; images are decoded only by active workers."""
    results: list[ConversionResult] = []
    claimed_outputs: set[Path] = set()
    jobs: list[tuple[Path, Path]] = []
    for source in images:
        destination = output_path(source, input_dir, output_dir)
        destination_key = destination.resolve(strict=False)
        if destination_key in claimed_outputs:
            results.append(ConversionResult(source, destination, "skipped", "another input has the same WebP output name"))
        else:
            claimed_outputs.add(destination_key)
            jobs.append((source, destination))

    completed = len(results)
    total = len(images)
    for result in results:
        completed += 0
        progress(completed, total, result)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="webp") as executor:
        futures = {executor.submit(convert_image, source, destination, options): (source, destination) for source, destination in jobs}
        for future in as_completed(futures):
            result = future.result()  # convert_image catches per-file conversion errors.
            results.append(result)
            completed += 1
            progress(completed, total, result)
    return results
