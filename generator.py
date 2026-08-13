"""Provider-isolated product-reference image generation service.

The default HTTP adapter intentionally lives only in this module. Replace
`HttpImageGenerationProvider.generate` when adopting a provider with a different
official SDK or request schema; the rest of WebOpti remains unchanged.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:
    import requests
except ModuleNotFoundError:  # Conversion-only use remains available until dependencies are installed.
    requests = None  # type: ignore[assignment]

from config import GENERATION_RETRIES
from utils import validate_image

LOGGER = logging.getLogger("webopti")

BASE_PROMPT = (
    "Use the uploaded image as the exact product reference. Preserve the product's identity, "
    "geometry, proportions, materials, colors, textures, decorative details, and construction. "
    "Do not redesign, replace, add, remove, or modify any part of the product. Only change the "
    "camera viewpoint and product presentation. Create a photorealistic premium e-commerce jewelry photograph."
)
NEGATIVE_REQUIREMENTS = (
    "No people, no hands, no models, no text, no logos unless they are part of the original product, "
    "no watermark, no additional jewelry, no additional objects, no packaging, no artificial product redesign."
)
ANGLES: tuple[tuple[str, str, str], ...] = (
    ("closeup", "Close-up", "Create a premium macro close-up product photograph of the exact jewelry product from the reference image. Preserve every product detail exactly. Use a close camera distance with the main decorative element sharply in focus. Use soft diffused studio lighting, subtle realistic shadows, luxury jewelry photography, shallow depth of field, clean cream/off-white background, photorealistic."),
    ("45degree", "45-degree", "Create a premium 45-degree three-quarter product photograph of the exact jewelry product from the reference image. Preserve every product detail exactly. Show the front design and depth of the product while keeping the entire product clearly visible. Use soft studio lighting, realistic reflections, subtle shadows, clean cream/off-white background, premium jewelry catalog photography, photorealistic."),
    ("side", "Side", "Create a premium low side-angle product photograph of the exact jewelry product from the reference image. Preserve every product detail exactly. Show the product profile, thickness, depth, and construction clearly. Use soft directional studio lighting, realistic reflections, subtle shadows, clean cream/off-white background, shallow depth of field, luxury jewelry photography, photorealistic."),
    ("top", "Top", "Create a premium 90-degree top-down product photograph of the exact jewelry product from the reference image. Preserve every product detail exactly. Show the complete product clearly and center it naturally in the frame. Use even soft studio lighting, realistic shadows, clean cream/off-white background, professional e-commerce catalog photography, photorealistic."),
)


@dataclass(frozen=True)
class GenerationResult:
    reference: Path
    angle_id: str
    angle_name: str
    output: Path
    status: str  # generated, skipped, failed
    message: str = ""


class ImageGenerationProvider(Protocol):
    """Small seam for an API provider or official SDK implementation."""

    def generate(self, reference: Path, prompt: str) -> bytes: ...


class HttpImageGenerationProvider:
    """Generic JSON/base64 adapter for a configured image-to-image HTTP endpoint.

    It POSTs `{prompt, image}` where image is a data URL, with bearer auth. It accepts
    an image response as `b64_json`, `image_base64`, `image`, or a direct `url`.
    See README for the precise adapter contract.
    """

    def __init__(self, api_key: str, endpoint: str, timeout: int = 120) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout

    def generate(self, reference: Path, prompt: str) -> bytes:
        if requests is None:
            raise RuntimeError("Missing dependency 'requests'. Run: pip install -r requirements.txt")
        mime = "image/jpeg" if reference.suffix.lower() in {".jpg", ".jpeg"} else f"image/{reference.suffix.lower().lstrip('.')}"
        raw_bytes = reference.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("ascii")

        # Native support for Google Gemini / Nano Banana API endpoints
        if "googleapis.com" in self.endpoint:
            url = self.endpoint
            if "key=" not in url:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}key={self.api_key}"
            headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": mime, "data": encoded}},
                        ]
                    }
                ]
            }
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            res_json = response.json()
            try:
                candidates = res_json.get("candidates", [])
                parts = candidates[0]["content"]["parts"]
                for part in parts:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and "data" in inline:
                        return base64.b64decode(inline["data"])
            except (KeyError, IndexError, TypeError) as err:
                raise ValueError(f"Google Gemini response format error: {res_json}") from err
            raise ValueError("No image data found in Google Gemini API response")

        # Standard generic HTTP adapter
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"prompt": prompt, "image": f"data:{mime};base64,{encoded}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", payload)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            raise ValueError("API response does not contain an image object")
        encoded_image = data.get("b64_json") or data.get("image_base64") or data.get("image")
        if encoded_image:
            if encoded_image.startswith("data:"):
                encoded_image = encoded_image.split(",", 1)[1]
            return base64.b64decode(encoded_image)
        if data.get("url"):
            download = requests.get(data["url"], timeout=self.timeout)
            download.raise_for_status()
            return download.content
        raise ValueError("API response lacks b64_json, image_base64, image, or url")


LAST_API_REQUEST_TIME: float = 0.0
REQUEST_INTERVAL_SECONDS: float = 120.0  # Strict 2-minute window between requests


def build_prompt(angle_prompt: str) -> str:
    return f"{BASE_PROMPT}\n\n{angle_prompt}\n\nNegative requirements: {NEGATIVE_REQUIREMENTS}"


def enforce_rate_limit_pacing() -> None:
    """Ensure at most one API request is sent per 2-minute window."""
    global LAST_API_REQUEST_TIME
    now = time.time()
    if LAST_API_REQUEST_TIME > 0:
        elapsed = now - LAST_API_REQUEST_TIME
        if elapsed < REQUEST_INTERVAL_SECONDS:
            wait_needed = REQUEST_INTERVAL_SECONDS - elapsed
            LOGGER.info("Rate limit pacing: waiting %.1fs to respect 2-minute API window...", wait_needed)
            print(f"Waiting {wait_needed:.1f}s to respect 2-minute API window...")
            time.sleep(wait_needed)
    LAST_API_REQUEST_TIME = time.time()


def generate_angle(
    provider: ImageGenerationProvider, reference: Path, product_directory: Path,
    angle_id: str, angle_name: str, angle_prompt: str, overwrite: bool,
) -> GenerationResult:
    """Generate, validate, and atomically save one requested product viewpoint."""
    destination = product_directory / f"{angle_id}.png"
    if destination.exists() and not overwrite:
        valid, message, _ = validate_image(destination)
        if valid:
            LOGGER.info("GENERATION SKIPPED product=%s angle=%s output=%s", reference.name, angle_id, destination)
            return GenerationResult(reference, angle_id, angle_name, destination, "skipped", "already exists")
        LOGGER.warning("Existing invalid generated image will be replaced: %s (%s)", destination, message)

    product_directory.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(angle_prompt)
    last_error = "unknown API error"
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        temporary = destination.with_name(f".{angle_id}.{time.time_ns()}.tmp.png")
        try:
            enforce_rate_limit_pacing()
            started = time.perf_counter()
            image_bytes = provider.generate(reference, prompt)
            temporary.write_bytes(image_bytes)
            valid, validation_error, dimensions = validate_image(temporary)
            if not valid:
                raise ValueError(f"generated response is not a valid image: {validation_error}")
            temporary.replace(destination)
            LOGGER.info("GENERATION SUCCESS product=%s angle=%s output=%s dimensions=%s seconds=%.2f", reference.name, angle_id, destination, dimensions, time.perf_counter() - started)
            return GenerationResult(reference, angle_id, angle_name, destination, "generated")
        except Exception as error:
            last_error = str(error) or error.__class__.__name__
            if hasattr(error, "response") and getattr(error, "response", None) is not None:
                try:
                    err_json = error.response.json()
                    last_error = err_json.get("error", {}).get("message", last_error)
                except Exception:
                    pass

            is_rate_limit = "429" in last_error or "Too Many Requests" in last_error or "RESOURCE_EXHAUSTED" in last_error
            LOGGER.warning("GENERATION RETRY product=%s angle=%s attempt=%d/%d error=%s", reference.name, angle_id, attempt, max_attempts, last_error)
            if attempt < max_attempts:
                sleep_time = 120.0 if is_rate_limit else (2 ** (attempt - 1))
                time.sleep(sleep_time)
        finally:
            if temporary.exists():
                temporary.unlink()
    LOGGER.error("GENERATION FAILED product=%s angle=%s error=%s", reference.name, angle_id, last_error)
    return GenerationResult(reference, angle_id, angle_name, destination, "failed", last_error)

