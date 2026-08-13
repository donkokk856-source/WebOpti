"""WebOpti command-line pipeline: optional AI views plus independent WebP conversion."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # Lets --help and converter-only mode explain a missing optional install clearly.
    def load_dotenv() -> bool:
        return False

from config import DEFAULT_BATCH_SIZE, DEFAULT_MAX_HEIGHT, DEFAULT_MAX_WIDTH, DEFAULT_QUALITY, DEFAULT_WORKERS
from converter import ConversionOptions, ConversionResult, convert_image, find_images, output_path, process_images
from generator import ANGLES, GenerationResult, HttpImageGenerationProvider, generate_angle
from utils import setup_logging, validate_image

LOGGER = logging.getLogger("webopti")


@dataclass
class ProductTask:
    reference: Path
    generations: list[GenerationResult]
    conversions: list[ConversionResult]


def positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a whole number") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def quality_value(value: str) -> int:
    result = positive_integer(value)
    if result > 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return result


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebOpti: generate consistent product views and optimize images to WebP.")
    parser.add_argument("--input", type=Path, default=Path("input_images"), help="Reference/source images (default: input_images)")
    parser.add_argument("--generated", type=Path, default=Path("generated_images"), help="Generated PNG folder (default: generated_images)")
    parser.add_argument("--output", type=Path, default=Path("output_images"), help="WebP destination folder (default: output_images)")
    parser.add_argument("--generate", action="store_true", help="Generate four AI product views per input image")
    parser.add_argument("--convert", action="store_true", help="Convert images to optimized WebP (input images alone, or generated images after --generate)")
    parser.add_argument("--quality", type=quality_value, default=DEFAULT_QUALITY, help=f"WebP quality, 1-100 (default: {DEFAULT_QUALITY})")
    parser.add_argument("--max-width", type=positive_integer, default=DEFAULT_MAX_WIDTH, help="Optional maximum output width")
    parser.add_argument("--max-height", type=positive_integer, default=DEFAULT_MAX_HEIGHT, help="Optional maximum output height")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing generated and WebP files")
    parser.add_argument("--clear", action="store_true", help="Clear all generated and output image files")
    parser.add_argument("--batch-size", type=positive_integer, default=DEFAULT_BATCH_SIZE, help=f"Products per controlled generation batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--workers", type=positive_integer, default=min(DEFAULT_WORKERS, os.cpu_count() or 1), help="Maximum concurrent products/conversions (default: up to 4)")
    parser.add_argument("--dry-run", action="store_true", help="Show the AI generation plan without contacting an API")
    args = parser.parse_args()
    # Preserve the original convenient `python main.py` conversion behavior.
    if not args.generate and not args.convert and not args.clear:
        args.convert = True
    if args.dry_run and not args.generate:
        parser.error("--dry-run is only meaningful with --generate")
    return args


def format_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def product_folder(reference: Path, input_dir: Path, generated_dir: Path) -> Path:
    relative = reference.relative_to(input_dir)
    return generated_dir / relative.parent / relative.stem


def process_product(
    reference: Path,
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    provider: HttpImageGenerationProvider | None,
    options: ConversionOptions,
    do_generate: bool,
    do_convert: bool,
) -> ProductTask:
    generations: list[GenerationResult] = []
    conversions: list[ConversionResult] = []
    destination_folder = product_folder(reference, input_dir, generated_dir)

    valid, error, _ = validate_image(reference)
    if not valid:
        LOGGER.error("REFERENCE FAILED input=%s error=%s", reference, error)
        if do_generate:
            failed = [
                GenerationResult(
                    reference, angle_id, angle_name, destination_folder / f"{angle_id}.png", "failed", f"invalid reference image: {error}"
                )
                for angle_id, angle_name, _ in ANGLES
            ]
            generations.extend(failed)
        return ProductTask(reference, generations, conversions)

    if do_generate and provider is not None:
        for idx, angle in enumerate(ANGLES):
            if idx > 0:
                time.sleep(1.5)
            gen_res = generate_angle(provider, reference, destination_folder, *angle, options.overwrite)
            generations.append(gen_res)

    if do_convert:
        if do_generate:
            for gen_res in generations:
                if gen_res.status in {"generated", "skipped"} and gen_res.output.exists():
                    out_p = destination_folder.relative_to(generated_dir) / f"{gen_res.angle_id}.webp"
                    dest_path = output_dir / out_p
                    conv_res = convert_image(gen_res.output, dest_path, options)
                    conversions.append(conv_res)
                else:
                    out_p = destination_folder.relative_to(generated_dir) / f"{gen_res.angle_id}.webp"
                    dest_path = output_dir / out_p
                    conversions.append(ConversionResult(gen_res.output, dest_path, "failed", f"generation failed: {gen_res.message}"))
        else:
            dest_path = output_path(reference, input_dir, output_dir)
            conv_res = convert_image(reference, dest_path, options)
            conversions.append(conv_res)

    return ProductTask(reference, generations, conversions)


def print_product_task(number: int, total: int, task: ProductTask) -> None:
    print(f"\nProduct {number}/{total}")
    print(f"Reference: {task.reference.name}")
    if task.generations:
        print("\nGenerating:")
        for result in task.generations:
            marker = "✓" if result.status in {"generated", "skipped"} else "✗"
            suffix = "" if result.status == "generated" else f" ({result.status}: {result.message})"
            print(f"[{marker}] {result.angle_name}{suffix}")
    if task.conversions:
        print("\nOptimizing:")
        for conv in task.conversions:
            marker = "✓" if conv.status in {"success", "skipped"} else "✗"
            suffix = "" if conv.status == "success" else f" ({conv.status}: {conv.message})"
            print(f"[{marker}] {conv.destination.name}{suffix}")
    print("\nProduct completed.")


def print_report(generation: list[GenerationResult], conversions: list[ConversionResult], products_count: int, elapsed: float) -> None:
    generated = sum(item.status == "generated" for item in generation)
    generation_failed = [item for item in generation if item.status == "failed"]
    converted = [item for item in conversions if item.status == "success"]
    conversion_failed = [item for item in conversions if item.status == "failed"]
    input_size = sum(item.input_size for item in converted)
    output_size = sum(item.output_size for item in converted)
    saved = input_size - output_size
    compression = (saved / input_size * 100) if input_size else 0.0

    print("\nWEBOPTI COMPLETE\n")
    print(f"Products processed: {products_count}\n")
    if generation:
        print(f"AI images:\nGenerated: {generated}\nFailed: {len(generation_failed)}\n")
    if conversions:
        print(
            f"WebP images:\nConverted: {len(converted)}\nFailed: {len(conversion_failed)}\n"
        )
        print(
            f"Original size:\n{format_size(input_size)}\n\n"
            f"Final size:\n{format_size(output_size)}\n\n"
            f"Space saved:\n{format_size(saved)}\n\n"
            f"Compression:\n{compression:.1f}%\n"
        )
    print(f"Processing time:\n{elapsed:.1f} seconds")

    failures = generation_failed + conversion_failed
    if failures:
        print("\nFailed items:")
        for item in failures:
            ref = item.reference if isinstance(item, GenerationResult) else item.source
            print(f"- {ref} → {item.message}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = parse_arguments()
    setup_logging(Path("logs") / "webopti.log")
    start = time.perf_counter()

    input_dir, generated_dir, output_dir = args.input.resolve(), args.generated.resolve(), args.output.resolve()
    if not input_dir.is_dir():
        print(f"Error: input folder does not exist: {input_dir}", file=sys.stderr)
        return 2
    if len({input_dir, generated_dir, output_dir}) != 3:
        print("Error: input, generated, and output folders must be different.", file=sys.stderr)
        return 2
    if generated_dir.is_relative_to(input_dir) or output_dir.is_relative_to(input_dir):
        print("Error: generated and output folders must not be inside the input folder.", file=sys.stderr)
        return 2

    if args.clear:
        count = 0
        for target_dir in (generated_dir, output_dir):
            if target_dir.exists():
                for item in list(target_dir.rglob("*")):
                    if item.is_file() and item.name != ".gitkeep":
                        try:
                            item.unlink()
                            count += 1
                        except Exception as err:
                            print(f"Warning: could not delete {item}: {err}", file=sys.stderr)
                for item in sorted(target_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    if item.is_dir() and item != target_dir:
                        try:
                            if not any(item.iterdir()):
                                item.rmdir()
                        except Exception:
                            pass
        print(f"Cleared {count} generated/output image files.")
        if not args.generate and not args.convert:
            return 0

    print("WebOpti\n----------------------------------------\n")
    references = find_images(input_dir)
    print(f"Found {len(references)} products.")
    if not references:
        return 0

    if args.dry_run:
        print(f"\n{len(references)} products detected.\n\nAI generation plan:\n\n{len(references)} x 4 angles = {len(references) * len(ANGLES)} image generations\n\nNo API requests were made.")
        return 0

    provider = None
    if args.generate:
        load_dotenv()
        key, endpoint = os.getenv("IMAGE_API_KEY"), os.getenv("IMAGE_API_ENDPOINT")
        if not key or not endpoint:
            print("Error: AI generation requires IMAGE_API_KEY and IMAGE_API_ENDPOINT in .env or environment variables. See .env.example.", file=sys.stderr)
            return 2
        provider = HttpImageGenerationProvider(key, endpoint)

    LOGGER.info("RUN START products=%d generate=%s convert=%s", len(references), args.generate, args.convert)
    all_generations: list[GenerationResult] = []
    all_conversions: list[ConversionResult] = []
    options = ConversionOptions(args.quality, args.max_width, args.max_height, args.overwrite)
    completed = 0

    try:
        for batch_start in range(0, len(references), args.batch_size):
            batch = references[batch_start:batch_start + args.batch_size]
            with ThreadPoolExecutor(max_workers=min(args.workers, len(batch)), thread_name_prefix="product") as executor:
                futures = [
                    executor.submit(
                        process_product,
                        ref,
                        input_dir,
                        generated_dir,
                        output_dir,
                        provider,
                        options,
                        args.generate,
                        args.convert,
                    )
                    for ref in batch
                ]
                for future in as_completed(futures):
                    task = future.result()
                    completed += 1
                    print_product_task(completed, len(references), task)
                    all_generations.extend(task.generations)
                    all_conversions.extend(task.conversions)
    except RuntimeError as error:
        LOGGER.error("RUN CONFIGURATION ERROR %s", error)
        print(f"Error: {error}", file=sys.stderr)
        return 2

    print_report(all_generations, all_conversions, len(references), time.perf_counter() - start)
    return 1 if any(item.status == "failed" for item in all_generations + all_conversions) else 0


if __name__ == "__main__":
    raise SystemExit(main())

