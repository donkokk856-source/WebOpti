# WebOpti

WebOpti is a local CLI for jewelry e-commerce imagery. Use it as a standalone WebP optimizer, as a reference-image AI generator, or as a full pipeline that generates four product views and optimizes them to WebP.

It recursively supports JPG/JPEG, PNG, WebP, TIFF, and BMP; retains filenames, Unicode, spaces, and subfolders; applies EXIF orientation; preserves transparency; avoids upscaling; and keeps processing after a bad file.

## Install and folders

Use Python 3.12+ and install dependencies from the project folder:

```bash
pip install -r requirements.txt
```

Place original product photos under `input_images/`. The tool creates these result paths for `input_images/summer/Celeste Star Ring 250.jpg`:

```text
generated_images/summer/Celeste Star Ring 250/
├── closeup.png
├── 45degree.png
├── side.png
└── top.png

output_images/summer/Celeste Star Ring 250/
├── closeup.webp
├── 45degree.webp
├── side.webp
└── top.webp
```

## Convert only

The original converter behavior remains the default:

```bash
python main.py
python main.py --convert --input input_images --output output_images
python main.py --quality 88
python main.py --max-width 2000 --max-height 2000
```

Quality defaults to 85. A higher quality preserves more fine detail but creates larger files. Maximum dimensions retain the original aspect ratio and only downscale; WebOpti never upscales. Existing output files are skipped unless explicitly replaced:

```bash
python main.py --convert --overwrite
```

## Configure AI generation

Copy `.env.example` to `.env`, then fill in the credentials for your chosen provider:

```text
IMAGE_API_KEY=your-secret-key
IMAGE_API_ENDPOINT=https://your-provider.example/v1/image-to-image
```

`.env` is ignored by Git and must not be committed. The provider is isolated in `generator.py`, so replacing it with an official SDK adapter does not affect conversion or CLI code.

The included HTTP adapter posts JSON with a bearer token:

```json
{"prompt": "...", "image": "data:image/jpeg;base64,..."}
```

It accepts a JSON response with an image in one of these forms: `{"b64_json":"..."}`, `{"image_base64":"..."}`, `{"image":"..."}`, a `data` object/list containing one of those fields, or `{"url":"https://..."}`. If your provider differs, update only `HttpImageGenerationProvider.generate()` in `generator.py` or add an SDK-backed provider implementing its `generate(reference, prompt) -> bytes` interface.

## Generate views

```bash
python main.py --generate
python main.py --generate --input input_images --generated generated_images
python main.py --generate --convert --quality 85 --max-width 2000
```

Each reference gets four separate, product-preserving prompts: close-up, 45-degree three-quarter, low side-angle, and top-down. The base prompt explicitly treats the upload as authoritative and forbids changing its identity, shape, materials, colors, gemstones, charms, proportions, or decorative details. Every angle also forbids people, hands, models, text, watermarks, packaging, added objects, and extra jewelry.

Generation is purposely controlled: `--batch-size` determines how many products are staged at once and `--workers` caps concurrent products/API requests. Each angle retries up to three times and a failure never stops the rest of the batch.

```bash
python main.py --generate --convert --batch-size 5 --workers 3
```

## Cost-safe planning

Before making paid API calls, use dry run:

```bash
python main.py --generate --dry-run
```

It scans the images and reports the exact number of planned calls (`products × 4`) without contacting the provider or creating images.

## Reports and troubleshooting

At completion, WebOpti shows generated/failed AI images, converted/failed WebP images, comparable source and final sizes, space saved, compression percentage, and elapsed time. Size statistics count only successful conversions from that run. Detailed product, angle, request, validation, error, dimensions, and file-size records are in `logs/webopti.log`.

- **Missing API settings:** create `.env` from `.env.example` or set both environment variables in your shell.
- **Existing generated/converted image:** it is skipped unless you add `--overwrite`.
- **Bad input or AI output:** the relevant item is listed as failed; all other items continue. Inspect `logs/webopti.log`.
- **Provider returns a different payload:** adapt `HttpImageGenerationProvider.generate()` as described above.
- **Pillow WebP error:** update Pillow: `pip install --upgrade Pillow`.

Run `python main.py --help` for the full argument list.
