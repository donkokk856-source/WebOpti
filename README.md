# 💎 WebOpti: AI Product Image Generator & WebP Optimization Studio

**WebOpti** is a production-grade AI-powered product image generation pipeline and WebP image optimization tool. It allows e-commerce brands, photographers, and developers to automatically generate **4 professional product angles** from a single reference image while strictly preserving the original product's identity, geometry, materials, and colors.

It features both a **Command-Line Interface (CLI)** and a **Django Web UI Dashboard** with live execution monitoring, output gallery, and settings management.

---

## 🌟 Key Features

- **🤖 4-Angle AI Product Generation**:
  1. **CLOSE-UP**: High-detail macro view focusing on decorative elements and craft.
  2. **45-DEGREE**: Three-quarter view showing front design and product depth.
  3. **SIDE / LOW-ANGLE**: Profile view accentuating thickness and silhouette.
  4. **TOP-DOWN**: 90-degree overhead catalog view cleanly centered in frame.
- **🛡️ Authoritative Product Preservation**:
  Strict prompt design ensures the AI changes **only the camera angle and presentation**, forbidding redesigns, shape alterations, color changes, added/removed elements, or extra objects.
- **⚡ Batch WebP Converter & Compression**:
  Recursively processes JPG, JPEG, PNG, WebP, TIFF, and BMP images, converting them to lossy WebP format with size compression statistics (space saved & compression %).
- **🖥️ Django Web UI Dashboard**:
  - **Live Execution Monitor**: Real-time progress bar, product status checklist, and live terminal logs.
  - **Product Output Gallery**: Visual card grid to inspect, compare, and download generated WebP views with a **1-Click Clear Output Gallery** option.
  - **Settings Manager**: Web interface to manage credentials (`IMAGE_API_KEY`, `IMAGE_API_ENDPOINT`).
- **🔌 Multi-Provider Support**:
  Native support for **Google Gemini (Nano Banana / Flash Image)**, **xAI (Grok)**, **Stability AI**, **Fal.ai**, and generic REST API endpoints.
- **🛡️ Rate-Limiting & Error Resilience**:
  - Automatic retry with exponential backoff on `HTTP 429 Too Many Requests`.
  - Image quality validation using Pillow before saving outputs.
  - Non-terminating batch processing: individual failures do not stop the pipeline.
- **🧪 Cost Control**: `--dry-run` mode reports planned API requests without making cloud calls.

---

## 📂 Project Structure

```text
WebOpti/
│
├── main.py                # Command-Line Interface (CLI) entry point
├── generator.py           # AI generation prompts, provider adapter & retries
├── converter.py           # Image discovery, resizing & WebP conversion engine
├── config.py              # Default pipeline settings & parameters
├── utils.py                # Logging setup & Pillow image validation
├── test_pipeline.py       # Automated unit test suite
├── requirements.txt       # Python dependencies (Pillow, requests, python-dotenv, django)
├── .env.example           # Environment template (API keys & endpoints)
├── .gitignore             # Git exclusions (credentials, logs, caches)
├── README.md              # Project documentation
│
├── webopti_web/           # Django project configuration
├── web_app/               # Django application (views, URLs, static assets, templates)
│   ├── static/            # Dark glassmorphic CSS & frontend JS scripts
│   └── templates/         # Dashboard, Gallery, & Settings HTML templates
│
├── input_images/          # Source product photos
├── generated_images/      # Generated PNG multi-angle images
├── output_images/         # Converted WebP optimized images
└── logs/                  # Application execution logs (webopti.log)
```

---

## ⚙️ Installation & Setup

### 1. Requirements
- Python 3.10+
- Installed dependencies from `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 2. Configure Credentials (`.env`)
Copy `.env.example` to `.env` and fill in your API provider key and endpoint URL:

```ini
IMAGE_API_KEY=your_actual_api_key
IMAGE_API_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent
```

*Or configure these credentials visually via the Settings page in the Django Web UI.*

---

## 🌐 Running the Django Web UI

Start the Django local development server:

```bash
python manage.py runserver 8000
```

Open your browser and navigate to:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

- **Dashboard**: Set local input folder, WebP quality, batch size, workers, and launch full AI + WebP pipelines.
- **Gallery**: View product cards, preview images in full-screen modal, download WebP files, or clear outputs.
- **Settings**: Manage API credentials safely.

---

## 🖥️ Command-Line Interface (CLI) Usage

### 1. WebP Conversion Only
Convert product photos directly into WebP format:

```bash
python main.py --convert
python main.py --input "C:\path\to\your\images" --convert --quality 85
```

### 2. Cost Control Check (Dry Run)
Preview the planned AI generations without sending API requests:

```bash
python main.py --input "C:\path\to\your\images" --generate --dry-run
```

### 3. Full Pipeline (AI Generation + WebP Optimization)
Generate 4 AI views per product and optimize them to WebP:

```bash
python main.py --input "C:\path\to\your\images" --generate --convert --batch-size 1 --workers 1
```

### 4. Clear Output Gallery from CLI
Remove all generated PNGs and WebP files from output folders:

```bash
python main.py --clear
```

---

## 🧪 Running Automated Unit Tests

Run the test suite to verify image validation, prompt construction, retries, and converter logic:

```bash
python -m unittest test_pipeline.py
```

---

## 📄 License
This project is licensed under the MIT License.
