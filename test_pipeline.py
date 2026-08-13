"""Unit test suite for WebOpti AI generation & WebP optimization pipeline."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from config import DEFAULT_QUALITY
from converter import ConversionOptions, convert_image, find_images, output_path
from generator import (
    ANGLES,
    BASE_PROMPT,
    NEGATIVE_REQUIREMENTS,
    build_prompt,
    generate_angle,
)
from utils import validate_image


class DummyProvider:
    """Mock provider returning valid or invalid image bytes based on counter."""

    def __init__(self, fail_count: int = 0) -> None:
        self.attempts = 0
        self.fail_count = fail_count

    def generate(self, reference: Path, prompt: str) -> bytes:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError("API temporary connection error")

        img = Image.new("RGB", (100, 100), color=(200, 150, 100))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


class WebOptiPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        import generator
        generator.REQUEST_INTERVAL_SECONDS = 0.0
        generator.LAST_API_REQUEST_TIME = 0.0

        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.input_dir = self.base_dir / "input_images"
        self.generated_dir = self.base_dir / "generated_images"
        self.output_dir = self.base_dir / "output_images"

        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create sample valid image
        self.sample_ref = self.input_dir / "product_001.jpg"
        img = Image.new("RGB", (200, 200), color=(255, 0, 0))
        img.save(self.sample_ref, format="JPEG")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_image_validation(self) -> None:
        valid, msg, size = validate_image(self.sample_ref)
        self.assertTrue(valid)
        self.assertEqual(size, (200, 200))
        self.assertEqual(msg, "")

        bad_file = self.input_dir / "invalid.jpg"
        bad_file.write_bytes(b"not an image file")
        valid_bad, msg_bad, size_bad = validate_image(bad_file)
        self.assertFalse(valid_bad)
        self.assertIsNone(size_bad)

    def test_prompt_building(self) -> None:
        angle_prompt = ANGLES[0][2]
        prompt = build_prompt(angle_prompt)
        self.assertIn(BASE_PROMPT, prompt)
        self.assertIn(angle_prompt, prompt)
        self.assertIn(NEGATIVE_REQUIREMENTS, prompt)

    def test_generator_with_retries(self) -> None:
        provider = DummyProvider(fail_count=2)
        product_dir = self.generated_dir / "product_001"

        result = generate_angle(
            provider,
            self.sample_ref,
            product_dir,
            "closeup",
            "Close-up",
            ANGLES[0][2],
            overwrite=True,
        )

        self.assertEqual(result.status, "generated")
        self.assertTrue(result.output.exists())
        self.assertEqual(provider.attempts, 3)

        # Skip on second run without overwrite
        result_skip = generate_angle(
            provider,
            self.sample_ref,
            product_dir,
            "closeup",
            "Close-up",
            ANGLES[0][2],
            overwrite=False,
        )
        self.assertEqual(result_skip.status, "skipped")

    def test_converter_webp(self) -> None:
        dest = output_path(self.sample_ref, self.input_dir, self.output_dir)
        options = ConversionOptions(
            quality=DEFAULT_QUALITY, max_width=None, max_height=None, overwrite=True
        )

        res = convert_image(self.sample_ref, dest, options)
        self.assertEqual(res.status, "success")
        self.assertTrue(dest.exists())
        self.assertGreater(res.output_size, 0)
        self.assertEqual(res.output_dimensions, (200, 200))

    def test_find_images(self) -> None:
        nested = self.input_dir / "folder" / "sub"
        nested.mkdir(parents=True, exist_ok=True)
        img_file = nested / "ring.png"
        Image.new("RGB", (50, 50)).save(img_file, format="PNG")

        images = find_images(self.input_dir)
        self.assertEqual(len(images), 2)
        self.assertIn(self.sample_ref, images)
        self.assertIn(img_file, images)


if __name__ == "__main__":
    unittest.main()
