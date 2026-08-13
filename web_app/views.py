"""Views and API endpoints for WebOpti Django Web UI."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings
from django.http import FileResponse, Http404, HttpRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from config import DEFAULT_BATCH_SIZE, DEFAULT_QUALITY, DEFAULT_WORKERS
from converter import ConversionOptions, convert_image, find_images, output_path
from generator import ANGLES, GenerationResult, HttpImageGenerationProvider, generate_angle
from utils import validate_image

LOGGER = logging.getLogger("webopti")

# Global background job state tracker
JOB_LOCK = threading.Lock()
ACTIVE_JOB: dict[str, Any] = {
    "running": False,
    "mode": "",
    "total_products": 0,
    "completed_products": 0,
    "current_product": "",
    "status_message": "Idle",
    "dry_run": False,
    "plan_summary": "",
    "generations_count": 0,
    "conversions_count": 0,
    "total_input_bytes": 0,
    "total_output_bytes": 0,
    "elapsed_seconds": 0.0,
    "errors": [],
    "logs": [],
}


def add_job_log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    with JOB_LOCK:
        ACTIVE_JOB["logs"].append(entry)
        if len(ACTIVE_JOB["logs"]) > 200:
            ACTIVE_JOB["logs"].pop(0)


def get_env_dict() -> dict[str, str]:
    env_path = django_settings.BASE_DIR / ".env"
    result = {"IMAGE_API_KEY": "", "IMAGE_API_ENDPOINT": ""}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                result[key.strip()] = val.strip().strip("\"'")
    return result


def index(request: HttpRequest):
    env_vars = get_env_dict()
    default_input = (
        request.session.get("input_folder", r"C:\Users\pauls\OneDrive\Desktop\drive-download-20260811T075919Z-1-001")
        if hasattr(request, "session")
        else r"C:\Users\pauls\OneDrive\Desktop\drive-download-20260811T075919Z-1-001"
    )
    context = {
        "input_folder": default_input,
        "api_configured": bool(env_vars.get("IMAGE_API_KEY") and env_vars.get("IMAGE_API_ENDPOINT")),
        "default_quality": DEFAULT_QUALITY,
        "default_batch_size": DEFAULT_BATCH_SIZE,
        "default_workers": DEFAULT_WORKERS,
    }
    return render(request, "index.html", context)


def settings_view(request: HttpRequest):
    env_vars = get_env_dict()
    context = {
        "api_key": env_vars.get("IMAGE_API_KEY", ""),
        "api_endpoint": env_vars.get("IMAGE_API_ENDPOINT", ""),
    }
    return render(request, "settings.html", context)


def gallery(request: HttpRequest):
    output_dir = django_settings.BASE_DIR / "output_images"
    generated_dir = django_settings.BASE_DIR / "generated_images"

    products_map: dict[str, dict[str, Any]] = {}

    if output_dir.exists():
        for p in output_dir.rglob("*.webp"):
            if p.is_file():
                rel = p.relative_to(output_dir)
                prod_name = rel.parent.name or rel.stem
                if prod_name not in products_map:
                    products_map[prod_name] = {
                        "name": prod_name,
                        "views": [],
                        "total_size": 0,
                    }
                size = p.stat().st_size
                products_map[prod_name]["total_size"] += size
                products_map[prod_name]["views"].append({
                    "angle": p.stem,
                    "filename": p.name,
                    "path": f"/serve_file/?path={p.resolve()}",
                    "size": size,
                })

    context = {
        "products": list(products_map.values()),
        "has_outputs": bool(products_map),
    }
    return render(request, "gallery.html", context)


@csrf_exempt
def api_save_settings(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    api_key = request.POST.get("api_key", "").strip()
    api_endpoint = request.POST.get("api_endpoint", "").strip()

    env_path = django_settings.BASE_DIR / ".env"
    lines = [
        "# WebOpti Environment Settings\n",
        f"IMAGE_API_KEY={api_key}\n",
        f"IMAGE_API_ENDPOINT={api_endpoint}\n",
    ]
    env_path.write_text("".join(lines), encoding="utf-8")
    os.environ["IMAGE_API_KEY"] = api_key
    os.environ["IMAGE_API_ENDPOINT"] = api_endpoint

    return JsonResponse({"success": True, "message": "Settings saved successfully."})


def api_job_status(request: HttpRequest):
    with JOB_LOCK:
        job_copy = dict(ACTIVE_JOB)
    return JsonResponse(job_copy)


def _run_pipeline_background(
    mode: str,
    input_dir_path: Path,
    quality: int,
    batch_size: int,
    workers: int,
    overwrite: bool,
    dry_run: bool,
):
    global ACTIVE_JOB
    start_time = time.perf_counter()

    with JOB_LOCK:
        ACTIVE_JOB["running"] = True
        ACTIVE_JOB["mode"] = mode
        ACTIVE_JOB["dry_run"] = dry_run
        ACTIVE_JOB["completed_products"] = 0
        ACTIVE_JOB["generations_count"] = 0
        ACTIVE_JOB["conversions_count"] = 0
        ACTIVE_JOB["total_input_bytes"] = 0
        ACTIVE_JOB["total_output_bytes"] = 0
        ACTIVE_JOB["errors"] = []
        ACTIVE_JOB["logs"] = []
        ACTIVE_JOB["status_message"] = "Scanning product images..."

    add_job_log(f"Scanning folder: {input_dir_path}")
    references = find_images(input_dir_path)

    with JOB_LOCK:
        ACTIVE_JOB["total_products"] = len(references)

    if not references:
        with JOB_LOCK:
            ACTIVE_JOB["status_message"] = "No images found in input folder."
            ACTIVE_JOB["running"] = False
        add_job_log("No supported images found.")
        return

    add_job_log(f"Found {len(references)} products.")

    if dry_run:
        plan = f"{len(references)} products detected. Plan: {len(references)} x 4 angles = {len(references) * 4} image generations."
        with JOB_LOCK:
            ACTIVE_JOB["plan_summary"] = plan
            ACTIVE_JOB["status_message"] = "Dry run completed."
            ACTIVE_JOB["running"] = False
        add_job_log(plan)
        add_job_log("No API requests were made.")
        return

    provider = None
    if mode in {"generate", "full"}:
        env_vars = get_env_dict()
        key = env_vars.get("IMAGE_API_KEY") or os.getenv("IMAGE_API_KEY")
        endpoint = env_vars.get("IMAGE_API_ENDPOINT") or os.getenv("IMAGE_API_ENDPOINT")
        if not key or not endpoint:
            err = "Missing IMAGE_API_KEY / IMAGE_API_ENDPOINT in .env"
            with JOB_LOCK:
                ACTIVE_JOB["errors"].append(err)
                ACTIVE_JOB["status_message"] = f"Error: {err}"
                ACTIVE_JOB["running"] = False
            add_job_log(f"ERROR: {err}")
            return
        provider = HttpImageGenerationProvider(key, endpoint)

    generated_dir = django_settings.BASE_DIR / "generated_images"
    output_dir = django_settings.BASE_DIR / "output_images"
    options = ConversionOptions(quality, None, None, overwrite)

    do_generate = mode in {"generate", "full"}
    do_convert = mode in {"convert", "full"}

    for idx, ref in enumerate(references, 1):
        with JOB_LOCK:
            if ACTIVE_JOB.get("stop_requested"):
                ACTIVE_JOB["status_message"] = "Job stopped by user."
                ACTIVE_JOB["running"] = False
                ACTIVE_JOB["stop_requested"] = False
                add_job_log("Job stopped by user request.")
                return
            ACTIVE_JOB["current_product"] = ref.name
            ACTIVE_JOB["status_message"] = f"Processing Product {idx}/{len(references)}: {ref.name}"

        add_job_log(f"Product {idx}/{len(references)}: {ref.name}")
        destination_folder = generated_dir / ref.stem

        if do_generate and provider:
            for angle_id, angle_name, angle_prompt in ANGLES:
                with JOB_LOCK:
                    if ACTIVE_JOB.get("stop_requested"):
                        ACTIVE_JOB["status_message"] = "Job stopped by user."
                        ACTIVE_JOB["running"] = False
                        ACTIVE_JOB["stop_requested"] = False
                        add_job_log("Job stopped by user request.")
                        return
                add_job_log(f"  Generating {angle_name}...")
                gen_res = generate_angle(provider, ref, destination_folder, angle_id, angle_name, angle_prompt, overwrite)
                if gen_res.status == "generated":
                    with JOB_LOCK:
                        ACTIVE_JOB["generations_count"] += 1
                elif gen_res.status == "failed":
                    with JOB_LOCK:
                        ACTIVE_JOB["errors"].append(f"{ref.name} ({angle_id}): {gen_res.message}")

        if do_convert:
            if do_generate:
                for angle_id, angle_name, _ in ANGLES:
                    png_path = destination_folder / f"{angle_id}.png"
                    if png_path.exists():
                        dest_webp = output_dir / ref.stem / f"{angle_id}.webp"
                        conv_res = convert_image(png_path, dest_webp, options)
                        if conv_res.status == "success":
                            with JOB_LOCK:
                                ACTIVE_JOB["conversions_count"] += 1
                                ACTIVE_JOB["total_input_bytes"] += conv_res.input_size
                                ACTIVE_JOB["total_output_bytes"] += conv_res.output_size
            else:
                dest_webp = output_path(ref, input_dir_path, output_dir)
                conv_res = convert_image(ref, dest_webp, options)
                if conv_res.status == "success":
                    with JOB_LOCK:
                        ACTIVE_JOB["conversions_count"] += 1
                        ACTIVE_JOB["total_input_bytes"] += conv_res.input_size
                        ACTIVE_JOB["total_output_bytes"] += conv_res.output_size

        with JOB_LOCK:
            ACTIVE_JOB["completed_products"] = idx

    elapsed = time.perf_counter() - start_time
    with JOB_LOCK:
        ACTIVE_JOB["elapsed_seconds"] = round(elapsed, 1)
        ACTIVE_JOB["status_message"] = "Pipeline completed successfully."
        ACTIVE_JOB["running"] = False

    add_job_log(f"WEBOPTI COMPLETE in {elapsed:.1f} seconds.")


@csrf_exempt
def api_run_pipeline(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    with JOB_LOCK:
        if ACTIVE_JOB["running"]:
            return JsonResponse({"error": "A job is already running."}, status=400)

    mode = request.POST.get("mode", "full")
    input_folder_str = request.POST.get("input_folder", "").strip()
    quality = int(request.POST.get("quality", DEFAULT_QUALITY))
    batch_size = int(request.POST.get("batch_size", DEFAULT_BATCH_SIZE))
    workers = int(request.POST.get("workers", DEFAULT_WORKERS))
    overwrite = request.POST.get("overwrite") == "true"
    dry_run = request.POST.get("dry_run") == "true"

    if input_folder_str:
        request.session["input_folder"] = input_folder_str

    input_dir_path = Path(input_folder_str) if input_folder_str else (django_settings.BASE_DIR / "input_images")
    if not input_dir_path.exists() or not input_dir_path.is_dir():
        return JsonResponse({"error": f"Input folder does not exist: {input_dir_path}"}, status=400)

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(mode, input_dir_path, quality, batch_size, workers, overwrite, dry_run),
        daemon=True,
    )
    thread.start()

    return JsonResponse({"success": True, "message": "Job started."})


@csrf_exempt
def api_stop_job(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    with JOB_LOCK:
        if not ACTIVE_JOB["running"]:
            return JsonResponse({"message": "No active job is running."})
        ACTIVE_JOB["stop_requested"] = True
        ACTIVE_JOB["status_message"] = "Stop requested by user..."

    add_job_log("Stop button clicked. Waiting for active worker to pause...")
    return JsonResponse({"success": True, "message": "Stop request sent."})


@csrf_exempt
def api_clear_gallery(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    with JOB_LOCK:
        if ACTIVE_JOB["running"]:
            return JsonResponse({"error": "Cannot clear gallery while a job is running."}, status=400)

    generated_dir = django_settings.BASE_DIR / "generated_images"
    output_dir = django_settings.BASE_DIR / "output_images"

    cleared_count = 0
    for target_dir in (generated_dir, output_dir):
        if target_dir.exists():
            for item in list(target_dir.rglob("*")):
                if item.is_file() and item.name != ".gitkeep":
                    try:
                        item.unlink()
                        cleared_count += 1
                    except Exception as err:
                        LOGGER.warning("Could not delete %s: %s", item, err)
            # Remove empty subdirectories
            for item in sorted(target_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if item.is_dir() and item != target_dir:
                    try:
                        if not any(item.iterdir()):
                            item.rmdir()
                    except Exception:
                        pass

    add_job_log(f"Cleared gallery: removed {cleared_count} generated/output image files.")
    return JsonResponse({"success": True, "message": f"Cleared {cleared_count} output files."})


def serve_file(request: HttpRequest):
    file_path_str = request.GET.get("path", "")
    if not file_path_str:
        raise Http404("Missing file path")

    file_path = Path(file_path_str).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise Http404("File not found")

    return FileResponse(open(file_path, "rb"))
