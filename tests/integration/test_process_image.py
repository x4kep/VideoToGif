"""Integration tests for image processing routes.

WHAT: Uses Flask's test client to send real HTTP requests to the image
processing endpoints. Tests the full request → process → response cycle.

WHY INTEGRATION TESTS MATTER:
- Unit tests verify logic in isolation, but can't catch WIRING BUGS:
  wrong status codes, missing JSON fields, broken content-type headers,
  file I/O failures, or routes that crash on valid input.
- These tests are slower than unit tests (tens of ms) but much faster
  than E2E tests (which need a browser).

WHAT WE MOCK:
- subprocess.run: The Swift bg removal binary only works on macOS.
  We mock it to return a copy of the input (simulating "removal happened").
  This lets us test all the route's wiring without needing macOS.
- We DON'T mock Pillow — it runs everywhere and we want to verify
  actual image transformations.

WHAT WE TEST FOR REAL (with @pytest.mark.macos_only):
- The actual Vision framework bg removal, for developers on macOS.
"""

import io
import json
import os
import shutil
import zipfile
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def post_image(client, png_bytes, options=None, filename="test.png"):
    """POST an image to /process-image with optional processing options.

    WHY a helper? Every test in this file needs to upload an image.
    Duplicating the FormData construction in every test would be noisy
    and fragile — if the API changes, you fix it in one place.
    """
    data = {
        "image": (io.BytesIO(png_bytes), filename),
        "options": json.dumps(options or {}),
    }
    return client.post(
        "/process-image",
        data=data,
        content_type="multipart/form-data",
    )


# ---------------------------------------------------------------------------
# /process-image tests
# ---------------------------------------------------------------------------
class TestProcessImage:
    """Tests for POST /process-image."""

    def test_basic_upload_returns_job(self, client, sample_png_bytes):
        """Simplest case: upload PNG, no options. Verify response shape."""
        resp = post_image(client, sample_png_bytes)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data
        assert "size" in data
        assert "width" in data
        assert "height" in data

    def test_original_dimensions_preserved(self, client, sample_png_bytes):
        """100x100 PNG with no resize should stay 100x100."""
        resp = post_image(client, sample_png_bytes)
        data = resp.get_json()
        assert data["width"] == 100
        assert data["height"] == 100

    def test_missing_image_returns_400(self, client):
        """No file attached → 400 error with message.

        WHY: Validates the route's input guard. Without this test, a
        regression could crash with 500 instead of returning a helpful 400.
        """
        resp = client.post(
            "/process-image",
            data={"options": "{}"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_resize_changes_dimensions(self, client, sample_png_bytes):
        """100x100 resized to width=50 should become 50x50."""
        resp = post_image(client, sample_png_bytes, {"width": 50})
        data = resp.get_json()
        assert data["width"] == 50
        assert data["height"] == 50

    def test_auto_crop_shrinks_transparent_border(self, client, sample_png_bytes):
        """sample_png_bytes has 10px transparent border → auto_crop → 80x80.

        WHY: This is the most important integration test for the image
        pipeline. It verifies that Pillow's getbbox() + crop() work
        correctly with our specific test image.
        """
        resp = post_image(client, sample_png_bytes, {"auto_crop": True})
        data = resp.get_json()
        assert data["width"] == 80
        assert data["height"] == 80

    def test_padding_increases_dimensions(self, client, sample_png_bytes):
        """100x100 + 20px padding → 140x140."""
        resp = post_image(client, sample_png_bytes, {"padding": 20})
        data = resp.get_json()
        assert data["width"] == 140
        assert data["height"] == 140

    def test_auto_crop_then_padding(self, client, sample_png_bytes):
        """crop(100→80) then pad(+10*2=100): demonstrates option ordering.

        WHY: The route applies auto_crop BEFORE padding. If the order
        were reversed, we'd pad first (120x120) then crop back. This
        test documents and enforces the correct order.
        """
        resp = post_image(client, sample_png_bytes, {
            "auto_crop": True,
            "padding": 10,
        })
        data = resp.get_json()
        assert data["width"] == 100  # 80 + 10*2
        assert data["height"] == 100

    def test_jpg_output_content_type(self, client, sample_png_bytes):
        """JPG output should serve as image/jpeg."""
        resp = post_image(client, sample_png_bytes, {"format": "jpg"})
        data = resp.get_json()
        result = client.get(f"/image-result/{data['job_id']}")
        assert result.status_code == 200
        assert result.content_type == "image/jpeg"

    def test_webp_output_content_type(self, client, sample_png_bytes):
        resp = post_image(client, sample_png_bytes, {"format": "webp"})
        data = resp.get_json()
        result = client.get(f"/image-result/{data['job_id']}")
        assert result.content_type == "image/webp"

    def test_png_output_content_type(self, client, sample_png_bytes):
        resp = post_image(client, sample_png_bytes, {"format": "png"})
        data = resp.get_json()
        result = client.get(f"/image-result/{data['job_id']}")
        assert result.content_type == "image/png"

    @patch("subprocess.run")
    @patch("os.path.isfile", wraps=os.path.isfile)
    def test_bg_removal_calls_binary(self, mock_isfile, mock_run, client, sample_png_bytes):
        """Verify bg removal invokes the Swift binary and handles output.

        WHY MOCK: The Swift binary only works on macOS 14+. By mocking
        subprocess.run, we test that our route:
        1. Checks if the binary exists
        2. Calls it with correct args (input_path, output_path)
        3. Opens the output file
        All without needing macOS.
        """
        def fake_isfile(path):
            if "remove_bg" in str(path):
                return True
            return os.path.isfile(path)
        mock_isfile.side_effect = fake_isfile

        def fake_run(cmd, **kwargs):
            # When the bg removal binary is called, copy input → output
            if isinstance(cmd, list) and len(cmd) >= 3 and "remove_bg" in str(cmd[0]):
                shutil.copy2(cmd[1], cmd[2])
            return MagicMock(returncode=0)
        mock_run.side_effect = fake_run

        resp = post_image(client, sample_png_bytes, {"remove_bg": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["width"] == 100

    @patch("subprocess.run")
    @patch("os.path.isfile", wraps=os.path.isfile)
    def test_bg_removal_with_white_replacement(self, mock_isfile, mock_run, client, sample_png_bytes):
        """After removing bg, fill transparent areas with white."""
        def fake_isfile(path):
            if "remove_bg" in str(path):
                return True
            return os.path.isfile(path)
        mock_isfile.side_effect = fake_isfile

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 3 and "remove_bg" in str(cmd[0]):
                shutil.copy2(cmd[1], cmd[2])
            return MagicMock(returncode=0)
        mock_run.side_effect = fake_run

        resp = post_image(client, sample_png_bytes, {
            "remove_bg": True,
            "bg_type": "white",
        })
        assert resp.status_code == 200

    @patch("subprocess.run")
    @patch("os.path.isfile", wraps=os.path.isfile)
    def test_bg_removal_with_custom_color(self, mock_isfile, mock_run, client, sample_png_bytes):
        """Custom hex color bg replacement."""
        def fake_isfile(path):
            if "remove_bg" in str(path):
                return True
            return os.path.isfile(path)
        mock_isfile.side_effect = fake_isfile

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 3 and "remove_bg" in str(cmd[0]):
                shutil.copy2(cmd[1], cmd[2])
            return MagicMock(returncode=0)
        mock_run.side_effect = fake_run

        resp = post_image(client, sample_png_bytes, {
            "remove_bg": True,
            "bg_type": "custom",
            "bg_color": "#00b894",
        })
        assert resp.status_code == 200

    @pytest.mark.macos_only
    @pytest.mark.slow
    def test_real_bg_removal(self, client, sample_png_bytes):
        """Run actual Apple Vision bg removal. macOS 14+ only.

        WHY: This is the only test that exercises the real Swift binary.
        It's slow (~1-2s) and platform-specific, so it's marked for
        optional execution. Run it locally on macOS to verify the binary
        works end-to-end.
        """
        resp = post_image(client, sample_png_bytes, {"remove_bg": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job_id"]

    def test_jpeg_input_works(self, client, sample_jpg_bytes):
        """JPEG input (no alpha channel) should process without errors."""
        resp = post_image(client, sample_jpg_bytes, filename="photo.jpg")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /image-result and /image-download tests
# ---------------------------------------------------------------------------
class TestImageResult:

    def test_valid_job_returns_image(self, client, sample_png_bytes):
        resp = post_image(client, sample_png_bytes)
        job_id = resp.get_json()["job_id"]

        result = client.get(f"/image-result/{job_id}")
        assert result.status_code == 200
        assert result.content_type.startswith("image/")
        assert len(result.data) > 0

    def test_invalid_job_returns_404(self, client):
        """Requesting a non-existent job should 404, not 500.

        WHY: A user refreshing a page after server restart would hit this.
        Returning 500 would look like a bug; 404 is expected.
        """
        resp = client.get("/image-result/nonexistent-uuid")
        assert resp.status_code == 404


class TestImageDownload:

    def test_download_has_attachment_header(self, client, sample_png_bytes):
        """Download should set Content-Disposition: attachment.

        WHY: Without this header, the browser would display the image
        inline instead of triggering a file save dialog.
        """
        resp = post_image(client, sample_png_bytes, filename="photo.png")
        job_id = resp.get_json()["job_id"]

        dl = client.get(f"/image-download/{job_id}")
        assert dl.status_code == 200
        disposition = dl.headers.get("Content-Disposition", "")
        assert "attachment" in disposition

    def test_download_preserves_original_filename(self, client, sample_png_bytes):
        """File named 'vacation.png' should download as 'vacation.png'."""
        resp = post_image(client, sample_png_bytes, filename="vacation.png")
        job_id = resp.get_json()["job_id"]

        dl = client.get(f"/image-download/{job_id}")
        disposition = dl.headers.get("Content-Disposition", "")
        assert "vacation.png" in disposition

    def test_download_with_format_change(self, client, sample_png_bytes):
        """Upload 'photo.png', output as JPG → download as 'photo.jpg'."""
        resp = post_image(client, sample_png_bytes, {"format": "jpg"}, filename="photo.png")
        job_id = resp.get_json()["job_id"]

        dl = client.get(f"/image-download/{job_id}")
        disposition = dl.headers.get("Content-Disposition", "")
        assert "photo.jpg" in disposition


# ---------------------------------------------------------------------------
# /download-all tests
# ---------------------------------------------------------------------------
class TestDownloadAll:

    def test_zip_contains_all_processed_images(self, client, sample_png_bytes):
        """Process 2 images, download as ZIP, verify both are inside.

        WHY: The ZIP endpoint is the most complex — it reads from the
        in-memory job store, creates a zipfile, and streams it. This
        test catches bugs in path construction and ZIP assembly.
        """
        job_ids = []
        for name in ["alpha.png", "beta.png"]:
            resp = post_image(client, sample_png_bytes, filename=name)
            job_ids.append(resp.get_json()["job_id"])

        zip_resp = client.post("/download-all", json={
            "job_ids": job_ids,
            "type": "image",
            "folder_name": "test-batch",
        })
        assert zip_resp.status_code == 200
        assert zip_resp.content_type == "application/zip"

        zf = zipfile.ZipFile(io.BytesIO(zip_resp.data))
        names = zf.namelist()
        assert len(names) == 2
        assert any("alpha.png" in n for n in names)
        assert any("beta.png" in n for n in names)

    def test_zip_files_are_in_named_folder(self, client, sample_png_bytes):
        """Files in the ZIP should be inside the folder_name directory."""
        resp = post_image(client, sample_png_bytes, filename="img.png")
        job_id = resp.get_json()["job_id"]

        zip_resp = client.post("/download-all", json={
            "job_ids": [job_id],
            "type": "image",
            "folder_name": "my-images",
        })
        zf = zipfile.ZipFile(io.BytesIO(zip_resp.data))
        for name in zf.namelist():
            assert name.startswith("my-images/")

    def test_empty_job_ids_returns_400(self, client):
        """No jobs to download → 400."""
        resp = client.post("/download-all", json={
            "job_ids": [],
            "type": "image",
            "folder_name": "empty",
        })
        assert resp.status_code == 400

    def test_invalid_job_ids_skipped(self, client, sample_png_bytes):
        """Mix of valid + invalid IDs: ZIP contains only valid ones."""
        resp = post_image(client, sample_png_bytes, filename="real.png")
        real_id = resp.get_json()["job_id"]

        zip_resp = client.post("/download-all", json={
            "job_ids": [real_id, "fake-id-1", "fake-id-2"],
            "type": "image",
            "folder_name": "mixed",
        })
        assert zip_resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(zip_resp.data))
        assert len(zf.namelist()) == 1
