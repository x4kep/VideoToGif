#!/usr/bin/env python3
import glob
import json
import os
import pty
import re
import select
import shutil
import subprocess
import tempfile
from uuid import uuid4

import requests as http_requests
from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOVE_BG_BIN = os.path.join(SCRIPT_DIR, "scripts", "remove_bg")
REMOVE_BG_SRC = os.path.join(SCRIPT_DIR, "scripts", "remove_background.swift")

jobs: dict = {}


def probe_video(path):
    """Get video metadata via ffprobe."""
    cmd = [
        "ffprobe", "-v", "0", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    info = json.loads(out)
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    fps_str = video_stream.get("r_frame_rate", "24/1")
    num, den = fps_str.split("/")
    fps = round(int(num) / int(den), 2) if int(den) else 24
    return {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "duration": float(info.get("format", {}).get("duration", 0)),
    }


def _add_text_overlay(frames, text, position):
    """Add text overlay to frames using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    # Try to load a nice font, fall back to default
    font = None
    for font_path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/Library/Fonts/Arial.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, 36)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    for frame_path in frames:
        img = Image.open(frame_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size

        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (w - tw) // 2

        if position == "top":
            y = 20
        elif position == "center":
            y = (h - th) // 2
        else:
            y = h - th - 20

        # Draw border/shadow
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                draw.text((x + dx, y + dy), text, font=font, fill="black")
        # Draw text
        draw.text((x, y), text, font=font, fill="white")

        img.save(frame_path)


def _adjust_canvas(frames, auto_crop, pad_top, pad_bottom, pad_left, pad_right):
    """Auto-trim whitespace around subject and/or add padding."""
    from PIL import Image, ImageChops

    if auto_crop and frames:
        # Find the combined bounding box across all frames
        overall_bbox = None
        for frame_path in frames:
            img = Image.open(frame_path).convert("RGBA")
            alpha = img.split()[3]
            if alpha.getextrema()[0] < 255:
                bbox = alpha.getbbox()
            else:
                bg = Image.new("RGB", img.size, (255, 255, 255))
                diff = ImageChops.difference(img.convert("RGB"), bg)
                bbox = diff.getbbox()
            if bbox:
                if overall_bbox is None:
                    overall_bbox = bbox
                else:
                    overall_bbox = (
                        min(overall_bbox[0], bbox[0]),
                        min(overall_bbox[1], bbox[1]),
                        max(overall_bbox[2], bbox[2]),
                        max(overall_bbox[3], bbox[3]),
                    )

        if overall_bbox:
            # Ensure even dimensions (required by some encoders)
            x1, y1, x2, y2 = overall_bbox
            w = x2 - x1
            h = y2 - y1
            if w % 2: x2 += 1
            if h % 2: y2 += 1
            overall_bbox = (x1, y1, x2, y2)
            for frame_path in frames:
                img = Image.open(frame_path).convert("RGBA")
                cropped = img.crop(overall_bbox)
                cropped.save(frame_path)

    if pad_top or pad_bottom or pad_left or pad_right:
        for frame_path in frames:
            img = Image.open(frame_path).convert("RGBA")
            w, h = img.size
            new_w = w + pad_left + pad_right
            new_h = h + pad_top + pad_bottom
            # Ensure even dimensions
            if new_w % 2: new_w += 1
            if new_h % 2: new_h += 1
            new_img = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
            new_img.paste(img, (pad_left, pad_top))
            new_img.save(frame_path)


def build_pipeline(input_path, output_path, opts, progress_fd):
    """Run the full conversion pipeline, writing progress to progress_fd."""
    def log(msg):
        os.write(progress_fd, (msg + "\n").encode())

    meta = probe_video(input_path)
    work_dir = os.path.dirname(output_path)
    frames_dir = os.path.join(work_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # --- Resolve options ---
    fps = opts.get("fps") or meta["fps"]
    width = opts.get("width") or 0  # 0 = original
    start = opts.get("start") or 0
    end = opts.get("end") or 0
    crop = opts.get("crop", "none")
    speed = opts.get("speed") or 1.0
    reverse = opts.get("reverse", False)
    bounce = opts.get("bounce", False)
    loop = opts.get("loop", 0)  # 0 = infinite
    max_colors = opts.get("max_colors") or 256
    lossy = opts.get("lossy") or 0
    remove_bg = opts.get("remove_bg", False)
    blur_bg = opts.get("blur_bg", False)
    grayscale = opts.get("grayscale", False)
    sepia = opts.get("sepia", False)
    brightness = opts.get("brightness") or 0
    contrast = opts.get("contrast") or 0
    text = opts.get("text", "").strip()
    text_pos = opts.get("text_pos", "bottom")
    auto_crop = opts.get("auto_crop", False)
    pad_top = opts.get("pad_top") or 0
    pad_bottom = opts.get("pad_bottom") or 0
    pad_left = opts.get("pad_left") or 0
    pad_right = opts.get("pad_right") or 0
    out_format = opts.get("format", "gif")

    # --- Step 1: Extract frames ---
    log("Extracting frames...")
    extract_cmd = ["ffmpeg", "-y"]
    if start:
        extract_cmd += ["-ss", str(start)]
    if end:
        extract_cmd += ["-to", str(end)]
    extract_cmd += ["-i", input_path]

    # Build video filter chain for extraction
    vfilters = []
    vfilters.append(f"fps={fps}")

    # Crop
    if crop == "square":
        vfilters.append("crop=min(iw\\,ih):min(iw\\,ih)")
    elif crop == "16:9":
        vfilters.append("crop=iw:iw*9/16")
    elif crop == "9:16":
        vfilters.append("crop=ih*9/16:ih")

    # Resize
    if width and width > 0:
        vfilters.append(f"scale={width}:-1:flags=lanczos")
    else:
        vfilters.append("scale=iw:-1:flags=lanczos")

    # Brightness / Contrast
    if brightness or contrast:
        b = brightness / 100.0 if brightness else 0
        c = 1.0 + (contrast / 100.0) if contrast else 1.0
        vfilters.append(f"eq=brightness={b}:contrast={c}")

    # Grayscale
    if grayscale:
        vfilters.append("hue=s=0")

    # Sepia
    if sepia:
        vfilters.append("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131")

    extract_cmd += ["-vf", ",".join(vfilters)]
    extract_cmd += [f"{frames_dir}/frame_%05d.png"]
    subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    frames = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    total = len(frames)
    if total == 0:
        log("Error: No frames extracted")

    # Text overlay (via Pillow, since ffmpeg drawtext requires libfreetype)
    if text and total > 0:
        log("Adding text overlay...")
        _add_text_overlay(frames, text, text_pos)

    log(f"Extracted {total} frames")

    # --- Step 2: Background removal (Apple Vision) ---
    if remove_bg:
        if not os.path.isfile(REMOVE_BG_BIN):
            log("Compiling background removal tool...")
            subprocess.run([
                "swiftc", "-O", "-o", REMOVE_BG_BIN, REMOVE_BG_SRC,
                "-framework", "Vision", "-framework", "CoreImage", "-framework", "AppKit",
            ], check=True)
        log("Removing backgrounds (Apple Vision)...")
        for i, frame in enumerate(frames, 1):
            subprocess.run([REMOVE_BG_BIN, frame, frame], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log(f"Processing frame {i}/{total}")

    # --- Step 2b: Blur background ---
    if blur_bg and not remove_bg:
        log("Blurring backgrounds...")
        for i, frame in enumerate(frames, 1):
            _blur_background(frame)
            log(f"Blurring frame {i}/{total}")

    # --- Step 2c: Auto-crop and padding ---
    if auto_crop or pad_top or pad_bottom or pad_left or pad_right:
        log("Adjusting canvas...")
        _adjust_canvas(frames, auto_crop, pad_top, pad_bottom, pad_left, pad_right)

    # --- Step 3: Speed / Reverse / Bounce ---
    if speed != 1.0 or reverse or bounce:
        log("Applying playback effects...")
        if speed != 1.0 and speed > 0:
            # Keep every Nth frame for speedup, duplicate for slowdown
            if speed > 1:
                step = speed
                frames = [frames[int(i)] for i in _frange(0, len(frames), step) if int(i) < len(frames)]
            else:
                # Slow down: duplicate frames
                new_frames = []
                repeats = int(1 / speed)
                for f in frames:
                    for r in range(repeats):
                        new_frames.append(f)
                frames = new_frames

        if reverse:
            frames = list(reversed(frames))

        if bounce:
            frames = frames + list(reversed(frames[1:-1]))

        # Renumber frames
        for i, src in enumerate(frames):
            dst = os.path.join(frames_dir, f"out_{i:05d}.png")
            if src != dst:
                shutil.copy2(src, dst)
        # Clean originals and rename
        for f in glob.glob(os.path.join(frames_dir, "frame_*.png")):
            os.remove(f)
        for i, f in enumerate(sorted(glob.glob(os.path.join(frames_dir, "out_*.png")))):
            os.rename(f, os.path.join(frames_dir, f"frame_{i:05d}.png"))

        frames = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
        total = len(frames)
        log(f"Playback adjusted: {total} frames")

    # --- Step 4: Assemble output ---
    actual_fps = fps if speed == 1.0 else fps  # fps already handled by frame selection
    has_transparency = remove_bg

    if out_format == "webp":
        log("Assembling WebP...")
        ext = ".webp"
        output_path = re.sub(r'\.[^.]+$', ext, output_path)
        assemble_cmd = [
            "ffmpeg", "-y", "-framerate", str(actual_fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-vcodec", "libwebp", "-lossless", "0", "-q:v", "80",
            "-loop", str(loop),
            output_path,
        ]
        r = subprocess.run(assemble_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            log(f"Assembly error: {r.stderr.decode(errors='replace')[-500:]}")
            return None

    elif out_format == "apng":
        log("Assembling APNG...")
        ext = ".apng"
        output_path = re.sub(r'\.[^.]+$', ext, output_path)
        assemble_cmd = [
            "ffmpeg", "-y", "-framerate", str(actual_fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-f", "apng", "-plays", str(loop),
            output_path,
        ]
        r = subprocess.run(assemble_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            log(f"Assembly error: {r.stderr.decode(errors='replace')[-500:]}")
            return None

    else:
        log("Generating palette...")
        palette_file = os.path.join(frames_dir, "palette.png")
        reserve = ":reserve_transparent=1" if has_transparency else ""
        palette_cmd = [
            "ffmpeg", "-y", "-framerate", str(actual_fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-vf", f"palettegen=max_colors={max_colors}:stats_mode=full{reserve}",
            palette_file,
        ]
        r = subprocess.run(palette_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            log(f"Palette error: {r.stderr.decode(errors='replace')[-500:]}")
            return None

        log("Assembling GIF...")
        assemble_cmd = [
            "ffmpeg", "-y", "-framerate", str(actual_fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-i", palette_file,
            "-lavfi", "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
            "-loop", str(loop),
            output_path,
        ]
        r = subprocess.run(assemble_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            log(f"Assembly error: {r.stderr.decode(errors='replace')[-500:]}")
            return None

        # Lossy compression with gifsicle
        if lossy > 0 and shutil.which("gifsicle"):
            log(f"Applying lossy compression (level {lossy})...")
            tmp_out = output_path + ".opt.gif"
            subprocess.run(
                ["gifsicle", f"--lossy={lossy}", "-O3", output_path, "-o", tmp_out],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if os.path.exists(tmp_out):
                os.replace(tmp_out, output_path)

    if os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log(f"Created: {os.path.basename(output_path)} ({size_mb:.1f} MB)")
        return output_path
    else:
        log("Error: Output file not created")
        return None


def _frange(start, stop, step):
    v = start
    while v < stop:
        yield v
        v += step


def _blur_background(frame_path):
    """Blur background using Apple Vision mask + Pillow."""
    from PIL import Image, ImageFilter

    mask_path = frame_path + ".mask.png"
    # Generate mask
    result = subprocess.run(
        [REMOVE_BG_BIN, frame_path, mask_path],
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not os.path.exists(mask_path):
        return

    original = Image.open(frame_path).convert("RGBA")
    masked = Image.open(mask_path).convert("RGBA")

    # Create blurred version of original
    blurred = original.filter(ImageFilter.GaussianBlur(radius=20))

    # Use the alpha from masked as the selection mask
    mask = masked.split()[3]

    # Composite: sharp foreground over blurred background
    result_img = Image.composite(original, blurred, mask)
    result_img.save(frame_path)
    os.remove(mask_path)


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    video = request.files.get("video")
    if not video or not video.filename:
        return jsonify({"error": "No video file provided"}), 400

    opts = json.loads(request.form.get("options", "{}"))
    out_format = opts.get("format", "gif")
    ext = {"gif": ".gif", "webp": ".webp", "apng": ".apng"}.get(out_format, ".gif")

    job_id = str(uuid4())
    work_dir = tempfile.mkdtemp(prefix="vtg_")
    filename = secure_filename(video.filename)
    input_path = os.path.join(work_dir, filename)
    output_path = os.path.join(work_dir, f"output{ext}")
    video.save(input_path)

    master_fd, slave_fd = pty.openpty()

    pid = os.fork()
    if pid == 0:
        # Child process
        os.close(master_fd)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        try:
            result = build_pipeline(input_path, output_path, opts, 1)
            # Update output path if format changed it
            os._exit(0 if result else 1)
        except Exception as e:
            os.write(1, f"Error: {e}\n".encode())
            os._exit(1)
    else:
        os.close(slave_fd)
        # Find actual output (format might change extension)
        jobs[job_id] = {
            "pid": pid,
            "master_fd": master_fd,
            "output": output_path,
            "work_dir": work_dir,
            "status": "running",
            "format": out_format,
        }
        return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        master_fd = job["master_fd"]
        pid = job["pid"]
        buf = ""

        while True:
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while "\r" in buf or "\n" in buf:
                    for sep in ("\r\n", "\n", "\r"):
                        idx = buf.find(sep)
                        if idx != -1:
                            line = buf[:idx].strip()
                            buf = buf[idx + len(sep):]
                            if line:
                                yield f"data: {json.dumps({'log': line})}\n\n"
                            break
            else:
                # Check if child exited
                try:
                    rpid, status = os.waitpid(pid, os.WNOHANG)
                    if rpid != 0:
                        break
                except ChildProcessError:
                    break

        try:
            os.close(master_fd)
        except OSError:
            pass

        if buf.strip():
            yield f"data: {json.dumps({'log': buf.strip()})}\n\n"

        # Wait for child
        try:
            _, status = os.waitpid(pid, 0)
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
        except ChildProcessError:
            exit_code = 0

        # Find the actual output file (might have different extension)
        work_dir = job["work_dir"]
        for ext in (".gif", ".webp", ".apng"):
            candidate = os.path.join(work_dir, f"output{ext}")
            if os.path.exists(candidate):
                job["output"] = candidate
                break

        result_status = "done" if exit_code == 0 and os.path.exists(job["output"]) else "error"
        job["status"] = result_status
        yield f"data: {json.dumps({'status': result_status})}\n\n"

    return Response(generate(), content_type="text/event-stream")


@app.route("/result/<job_id>")
def result(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if not os.path.exists(job["output"]):
        return jsonify({"error": "Output not ready"}), 404
    mime = {
        "gif": "image/gif",
        "webp": "image/webp",
        "apng": "image/apng",
    }.get(job.get("format", "gif"), "image/gif")
    return send_file(job["output"], mimetype=mime, as_attachment=False)


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if not os.path.exists(job["output"]):
        return jsonify({"error": "Output not ready"}), 404
    fname = os.path.basename(job["output"])
    mime = {
        "gif": "image/gif",
        "webp": "image/webp",
        "apng": "image/apng",
    }.get(job.get("format", "gif"), "image/gif")
    return send_file(job["output"], mimetype=mime, as_attachment=True, download_name=fname)


@app.route("/api/gemini/logo", methods=["POST"])
def gemini_logo():
    """Generate a logo using Gemini with optional reference image."""
    data = request.get_json()
    api_key = data.get("key", "")
    subject = data.get("subject", "")
    style = data.get("style", "")
    ref_image = data.get("ref_image")  # base64 or None
    ref_mime = data.get("ref_mime", "image/png")

    if not api_key or not subject:
        return jsonify({"error": "Missing API key or subject"}), 400

    model = "gemini-3.1-flash-image-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    logo_prompt = (
        f"Generate a 1:1 square logo based on the following user input: {subject}. "
        f"Style: {style}. "
    )

    if ref_image:
        logo_prompt += (
            "Use the provided reference image as your design inspiration. "
            "Look at the style, color, strokes, and overall vibe to be implemented "
            "into the new logo. Please note: do NOT use the design of the reference "
            "logo in the new logo. Your task is only to imitate the style and "
            "transform it according to the user request. "
        )
    logo_prompt += (
        "The logo should be clean, professional, centered in the square canvas, "
        "with a simple solid or transparent background. Make it suitable for use "
        "as an app icon, social media avatar, or brand mark."
    )

    parts = [{"text": logo_prompt}]
    if ref_image:
        parts.insert(0, {
            "inlineData": {"mimeType": ref_mime, "data": ref_image}
        })

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": "1:1"},
        },
    }

    try:
        resp = http_requests.post(
            url, json=body, headers={"x-goog-api-key": api_key}, timeout=120
        )
        resp.raise_for_status()
        result = resp.json()
        for part in result["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return jsonify({
                    "image": part["inlineData"]["data"],
                    "mime": part["inlineData"]["mimeType"],
                })
        return jsonify({"error": "No image in response"}), 500
    except http_requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        return jsonify({"error": err_detail}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gemini", methods=["POST"])
def gemini_proxy():
    """Proxy requests to the Gemini API."""
    data = request.get_json()
    api_key = data.get("key", "")
    model = data.get("model", "gemini-2.0-flash")
    prompt = data.get("prompt", "")
    system = data.get("system", "")

    if not api_key or not prompt:
        return jsonify({"error": "Missing API key or prompt"}), 400

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        resp = http_requests.post(url, json=body, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify({"text": text})
    except http_requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        return jsonify({"error": err_detail}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gemini/image", methods=["POST"])
def gemini_image():
    """Generate an image using Gemini Imagen."""
    data = request.get_json()
    api_key = data.get("key", "")
    prompt = data.get("prompt", "")
    aspect = data.get("aspect", "1:1")

    if not api_key or not prompt:
        return jsonify({"error": "Missing API key or prompt"}), 400

    model = "gemini-3.1-flash-image-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect},
        },
    }

    try:
        resp = http_requests.post(
            url, json=body, headers={"x-goog-api-key": api_key}, timeout=120
        )
        resp.raise_for_status()
        result = resp.json()
        parts = result["candidates"][0]["content"]["parts"]
        for part in parts:
            if "inlineData" in part:
                return jsonify({
                    "image": part["inlineData"]["data"],
                    "mime": part["inlineData"]["mimeType"],
                })
        return jsonify({"error": "No image in response"}), 500
    except http_requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        return jsonify({"error": err_detail}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Video generation (Veo) ---
video_ops: dict = {}


@app.route("/api/gemini/video", methods=["POST"])
def gemini_video():
    """Start video generation with Veo."""
    data = request.get_json()
    api_key = data.get("key", "")
    prompt = data.get("prompt", "")
    aspect = data.get("aspect", "16:9")
    duration = data.get("duration", "8")

    if not api_key or not prompt:
        return jsonify({"error": "Missing API key or prompt"}), 400

    model = "veo-3.1-generate-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning"

    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "aspectRatio": aspect,
            "durationSeconds": str(duration),
        },
    }

    try:
        resp = http_requests.post(
            url, json=body, headers={"x-goog-api-key": api_key}, timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
        op_name = result.get("name", "")
        op_id = str(uuid4())
        video_ops[op_id] = {"op_name": op_name, "api_key": api_key}
        return jsonify({"op_id": op_id})
    except http_requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        return jsonify({"error": err_detail}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gemini/video/<op_id>")
def gemini_video_poll(op_id):
    """Poll video generation status."""
    op = video_ops.get(op_id)
    if not op:
        return jsonify({"error": "Operation not found"}), 404

    url = f"https://generativelanguage.googleapis.com/v1beta/{op['op_name']}"
    try:
        resp = http_requests.get(
            url, headers={"x-goog-api-key": op["api_key"]}, timeout=30
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("done"):
            samples = (
                result.get("response", {})
                .get("generateVideoResponse", {})
                .get("generatedSamples", [])
            )
            if samples:
                video_uri = samples[0].get("video", {}).get("uri", "")
                # Download the video and serve locally
                vid_resp = http_requests.get(
                    video_uri,
                    headers={"x-goog-api-key": op["api_key"]},
                    timeout=120,
                )
                vid_resp.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".mp4", prefix="veo_"
                )
                tmp.write(vid_resp.content)
                tmp.close()
                op["video_path"] = tmp.name
                return jsonify({"done": True, "video_path": tmp.name})
            return jsonify({"done": True, "error": "No video in response"})
        return jsonify({"done": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gemini/video/<op_id>/download")
def gemini_video_download(op_id):
    """Download generated video."""
    op = video_ops.get(op_id)
    if not op or "video_path" not in op:
        return jsonify({"error": "Video not ready"}), 404
    return send_file(op["video_path"], mimetype="video/mp4", as_attachment=True,
                     download_name="generated.mp4")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
