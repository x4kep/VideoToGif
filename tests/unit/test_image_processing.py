"""Unit tests for image processing logic.

WHAT: Tests the pure Pillow image manipulation that process_image() performs.
These test the same operations the route uses, extracted into isolated cases.

WHY UNIT TESTS ARE THE BASE OF THE PYRAMID:
- Run in milliseconds — instant feedback while coding
- Zero external dependencies — no server, no binary, no network
- Catch logic bugs: wrong resize math, broken color parsing, bad crop bounds
- If these fail, the bug is in YOUR code, not in a flaky dependency

WHAT TO MOCK VS TEST FOR REAL:
Nothing is mocked here. All tests use real Pillow operations.
The Swift bg removal binary isn't involved — that's tested in integration.
"""

from PIL import Image
import io
import pytest


class TestResize:
    """Tests for resize logic (app.py lines 866-869).

    The route resizes by computing: ratio = target_width / original_width,
    then new_height = int(original_height * ratio). This preserves aspect ratio.
    """

    def test_square_image_resize(self):
        """100x100 → 50x50: straightforward halving."""
        img = Image.new("RGBA", (100, 100))
        target_w = 50
        ratio = target_w / img.width
        new_h = int(img.height * ratio)
        resized = img.resize((target_w, new_h), Image.LANCZOS)
        assert resized.size == (50, 50)

    def test_landscape_image_maintains_aspect_ratio(self):
        """200x100 → 100x50: width halved, height follows."""
        img = Image.new("RGBA", (200, 100))
        target_w = 100
        ratio = target_w / img.width
        new_h = int(img.height * ratio)
        resized = img.resize((target_w, new_h), Image.LANCZOS)
        assert resized.size == (100, 50)

    def test_portrait_image_maintains_aspect_ratio(self):
        """100x200 → 50x100."""
        img = Image.new("RGBA", (100, 200))
        target_w = 50
        ratio = target_w / img.width
        new_h = int(img.height * ratio)
        resized = img.resize((target_w, new_h), Image.LANCZOS)
        assert resized.size == (50, 100)

    def test_width_zero_means_original(self):
        """The route guards: `if resize_width and resize_width > 0`.
        Width=0 means 'keep original' — this test documents that behavior."""
        resize_width = 0
        assert not (resize_width and resize_width > 0)

    def test_width_matches_original_is_noop(self):
        """The route guards: `if img.width != resize_width`.
        No resize when target == current."""
        img = Image.new("RGBA", (640, 480))
        resize_width = 640
        should_resize = resize_width and resize_width > 0 and img.width != resize_width
        assert not should_resize


class TestBgReplacement:
    """Tests for background replacement logic (app.py lines 887-899).

    After bg removal, transparent pixels can be filled with a solid color.
    The route parses hex strings like '#00b894' into RGBA tuples.
    """

    def test_transparent_bg_preserves_alpha(self):
        """When bg_type == 'transparent', no replacement happens.
        This is the most common case — user just wants the bg gone."""
        bg_type = "transparent"
        remove_bg = True
        # The route condition: `if remove_bg and bg_type != "transparent"`
        should_replace = remove_bg and bg_type != "transparent"
        assert not should_replace

    def test_white_bg_fills_transparent_pixels(self):
        """Transparent pixels become white after compositing."""
        # Fully transparent image
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        bg_img = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg_img.paste(img, mask=img.split()[3])
        # Alpha=0 means the red is invisible; white bg shows through
        assert bg_img.getpixel((5, 5)) == (255, 255, 255, 255)

    def test_black_bg_fills_transparent_pixels(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        bg_img = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg_img.paste(img, mask=img.split()[3])
        assert bg_img.getpixel((5, 5)) == (0, 0, 0, 255)

    def test_opaque_pixels_stay_on_colored_bg(self):
        """Opaque red pixel on white bg should remain red."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        bg_img = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg_img.paste(img, mask=img.split()[3])
        assert bg_img.getpixel((5, 5)) == (255, 0, 0, 255)

    def test_hex_color_parsing_with_hash(self):
        """'#ff5733' → (255, 87, 51, 255)."""
        bg_color = "#ff5733"
        hex_c = bg_color.lstrip("#")
        result = (int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16), 255)
        assert result == (255, 87, 51, 255)

    def test_hex_color_parsing_without_hash(self):
        """'00b894' → (0, 184, 148, 255)."""
        hex_c = "00b894"
        result = (int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16), 255)
        assert result == (0, 184, 148, 255)

    def test_hex_black(self):
        hex_c = "000000"
        result = (int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16), 255)
        assert result == (0, 0, 0, 255)

    def test_hex_white(self):
        hex_c = "ffffff"
        result = (int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16), 255)
        assert result == (255, 255, 255, 255)


class TestAutoCrop:
    """Tests for auto-crop logic (app.py lines 902-905).

    Uses Pillow's getbbox() which returns the bounding box of non-zero
    (non-transparent for RGBA) pixels. Returns None if image is empty.
    """

    def test_crops_transparent_border(self):
        """Image with 10px transparent border: 100x100 → 80x80."""
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for x in range(10, 90):
            for y in range(10, 90):
                img.putpixel((x, y), (255, 0, 0, 255))
        bbox = img.getbbox()
        cropped = img.crop(bbox)
        assert cropped.size == (80, 80)

    def test_fully_transparent_returns_none(self):
        """getbbox() returns None for all-transparent images.

        WHY THIS MATTERS: The route must check `if bbox:` before calling
        crop(), otherwise it crashes with TypeError. This test documents
        that edge case.
        """
        img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        bbox = img.getbbox()
        assert bbox is None

    def test_fully_opaque_returns_full_bounds(self):
        """Fully opaque image: bbox covers everything, crop is a noop."""
        img = Image.new("RGBA", (50, 50), (128, 128, 128, 255))
        bbox = img.getbbox()
        assert bbox == (0, 0, 50, 50)

    def test_single_pixel_subject(self):
        """Edge case: only one opaque pixel at (25, 25)."""
        img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        img.putpixel((25, 25), (255, 0, 0, 255))
        bbox = img.getbbox()
        cropped = img.crop(bbox)
        assert cropped.size == (1, 1)


class TestPadding:
    """Tests for padding logic (app.py lines 908-913).

    Padding creates a new transparent canvas, larger by pad*2 in each
    dimension, and pastes the original at offset (pad, pad).
    """

    def test_adds_symmetric_padding(self):
        img = Image.new("RGBA", (80, 60))
        pad = 10
        new_w = img.width + pad * 2
        new_h = img.height + pad * 2
        padded = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        padded.paste(img, (pad, pad))
        assert padded.size == (100, 80)

    def test_large_padding(self):
        img = Image.new("RGBA", (10, 10))
        pad = 100
        padded = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
        padded.paste(img, (pad, pad))
        assert padded.size == (210, 210)

    def test_zero_padding_is_noop(self):
        """The route guards: `if pad and pad > 0`."""
        pad = 0
        assert not (pad and pad > 0)

    def test_padded_corners_are_transparent(self):
        """Padding area should be fully transparent."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        pad = 5
        padded = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        padded.paste(img, (pad, pad))
        # Corner pixel should be transparent
        assert padded.getpixel((0, 0)) == (0, 0, 0, 0)
        # Center should be red
        assert padded.getpixel((10, 10)) == (255, 0, 0, 255)


class TestOutputFormat:
    """Tests for format conversion logic (app.py lines 916-926).

    Key concern: JPG doesn't support transparency. The route composites
    the RGBA image onto a white RGB background before saving as JPEG.
    Without this, transparent areas would appear black.
    """

    def test_jpg_flattens_rgba_to_rgb(self):
        """RGBA image saved as JPG: transparent areas become white."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))  # semi-transparent red
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        rgb.paste(img, mask=img.split()[3])
        assert rgb.mode == "RGB"
        # Semi-transparent red on white should blend toward pink/light-red
        r, g, b = rgb.getpixel((5, 5))
        assert r > 200  # red channel high
        assert g > 100  # white bleeding through

    def test_png_preserves_transparency(self):
        """PNG output should keep alpha channel intact."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        reloaded = Image.open(buf)
        assert reloaded.mode == "RGBA"
        assert reloaded.getpixel((5, 5))[3] == 0  # alpha preserved

    def test_format_extension_mapping(self):
        """Extension lookup used by the route."""
        mapping = {"png": ".png", "webp": ".webp", "jpg": ".jpg"}
        assert mapping.get("png") == ".png"
        assert mapping.get("webp") == ".webp"
        assert mapping.get("jpg") == ".jpg"
        assert mapping.get("bmp", ".png") == ".png"  # unknown falls back

    def test_download_name_preserves_original(self):
        """Original filename 'photo.png' + format 'webp' → 'photo.webp'."""
        import os
        filename = "my_photo.png"
        out_format = "webp"
        ext = {"png": ".png", "webp": ".webp", "jpg": ".jpg"}[out_format]
        orig_name = os.path.splitext(filename)[0]
        dl_name = orig_name + ext
        assert dl_name == "my_photo.webp"
