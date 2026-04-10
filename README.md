# GIF Studio

A web-based toolkit for converting videos to GIFs, processing images with background removal, and generating AI-powered media using Google Gemini. Built with Flask and vanilla JavaScript.

## Features

### Video to GIF Converter
- **Bulk upload** — drag-and-drop or select multiple videos, processed sequentially with live progress
- **Trim & crop** — set start/end timestamps, crop to square, 16:9, or 9:16
- **Resize** — scale to 640/480/320/240/160px width (height auto-scales)
- **FPS control** — match original or reduce to 24/15/12/10/8/5 fps
- **Playback effects** — speed (0.25x–4x), reverse, bounce (forward + backward loop)
- **Color adjustments** — brightness, contrast, grayscale, sepia
- **Background removal** — remove or blur backgrounds using Apple Vision (macOS 14+)
- **Auto-crop & padding** — trim whitespace, add padding per side
- **Text overlay** — add captions at top, center, or bottom
- **Output formats** — GIF (with lossy compression via gifsicle), WebP, APNG
- **Palette optimization** — configurable max colors (32–256) with Bayer dithering

### Image Processing
- **Bulk upload** — process multiple images at once
- **Background removal** — Apple Vision powered subject isolation
- **Auto-trim** — crop transparent areas around the subject
- **Resize & padding** — scale width, add uniform padding
- **Output formats** — PNG (with transparency), WebP, JPG
- **Original filename preserved** on download

### Prompt Builder (AI-Powered)
- **Visual prompt construction** — combine subject, action, background, style, camera, and duration
- **24 animation presets** — wave, dance, jump, spin, type, meditate, and more
- **21 visual styles** — cartoon, 3D mascot, pixel art, anime, watercolor, glassmorphism, etc.
- **AI prompt enhancement** — refine prompts using Gemini text models
- **Logo generation** — create square logos with optional reference image for style inspiration
- **Image generation** — text-to-image via Gemini Imagen
- **Video generation** — text-to-video via Veo with real-time polling
- **Send to Converter** — send generated videos directly to the converter tab

### Settings
- Gemini API key management (stored in browser localStorage)
- Model selection: Gemini 2.0 Flash, 2.5 Flash, 2.5 Pro
- Connection testing

## Prerequisites

- **Python 3.8+**
- **ffmpeg** and **ffprobe** in PATH
- **macOS 14+** (Sonoma) for background removal (Apple Vision)
- **gifsicle** (optional, for lossy GIF compression)
- **Google Gemini API key** (optional, for AI features)

### Install ffmpeg

```bash
# Check if already installed
ffmpeg -version && ffprobe -version

# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

Optionally install gifsicle for lossy GIF compression:
```bash
brew install gifsicle        # macOS
sudo apt-get install gifsicle # Ubuntu/Debian
```

Run `scripts/check_ffmpeg.sh` to verify your setup.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Web Interface

```bash
python3 app.py
# Open http://localhost:5001
```

### Command Line

```bash
# Basic conversion
./video_to_gif.sh /path/to/video.mp4

# Custom output path
./video_to_gif.sh /path/to/video.mp4 output.gif

# With background removal (macOS)
./video_to_gif.sh -r /path/to/video.mp4
```

## API Endpoints

### Video Processing
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/convert` | Upload video + options, returns job ID |
| GET | `/progress/<job_id>` | SSE stream with real-time progress |
| GET | `/result/<job_id>` | Serve converted GIF/WebP/APNG |
| GET | `/download/<job_id>` | Download converted file |

### Image Processing
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/process-image` | Upload image + options, returns job ID |
| GET | `/image-result/<job_id>` | Serve processed image |
| GET | `/image-download/<job_id>` | Download processed image |

### Gemini AI
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/gemini` | Text generation (prompt enhancement) |
| POST | `/api/gemini/logo` | Logo generation with optional reference |
| POST | `/api/gemini/image` | Image generation (Imagen) |
| POST | `/api/gemini/video` | Start video generation (Veo) |
| GET | `/api/gemini/video/<op_id>` | Poll video generation status |
| GET | `/api/gemini/video/<op_id>/download` | Download generated video |

## Project Structure

```
.
├── app.py                          # Flask backend (all routes and processing)
├── templates/index.html            # Frontend SPA (HTML + CSS + JS)
├── requirements.txt                # Python dependencies
├── video_to_gif.sh                 # CLI video-to-GIF converter
└── scripts/
    ├── remove_background.swift     # Apple Vision background removal tool
    └── check_ffmpeg.sh             # FFmpeg installation checker
```

## Dependencies

**Python**: Flask, Pillow, requests

**System tools**: ffmpeg, ffprobe, gifsicle (optional), swiftc (macOS, auto-compiles)

**AI models** (via Gemini API): gemini-2.0-flash, gemini-2.5-flash, gemini-2.5-pro, gemini-3.1-flash-image-preview, veo-3.1-generate-preview
