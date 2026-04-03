"""Tests for ScreenCapture math: scale factor computation and coordinate mapping."""
import math
import pytest

from shannon.computer.screenshot import ScreenCapture


def test_resize_image_reduces_dimensions():
    """_resize_image should scale down images exceeding max dimensions."""
    from shannon.vision.providers.screen import _resize_image
    from PIL import Image
    import io

    # Create a 1920x1080 test image
    img = Image.new("RGB", (1920, 1080), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    resized = _resize_image(original_bytes, max_width=1024, max_height=768)

    resized_img = Image.open(io.BytesIO(resized))
    assert resized_img.width <= 1024
    assert resized_img.height <= 768


def test_resize_image_noop_when_small():
    """_resize_image should return input unchanged when within bounds."""
    from shannon.vision.providers.screen import _resize_image
    from PIL import Image
    import io

    img = Image.new("RGB", (640, 480), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    resized = _resize_image(original_bytes, max_width=1024, max_height=768)
    assert resized == original_bytes


def test_scale_factor_small_screen():
    """Small screens (well within API limits) should have scale factor of 1.0."""
    cap = ScreenCapture(1280, 720)
    assert cap._compute_scale() == 1.0


def test_scale_factor_large_screen():
    """Large screens that exceed API limits should have scale factor < 1.0."""
    cap = ScreenCapture(3840, 2160)  # 4K display
    scale = cap._compute_scale()
    assert scale < 1.0


def test_scale_to_real_identity_when_no_scaling():
    """When scale is 1.0, scale_to_real should return the same coordinates."""
    cap = ScreenCapture(1280, 720)
    assert cap._compute_scale() == 1.0
    x, y = cap.scale_to_real(100, 200)
    assert x == 100
    assert y == 200


def test_scale_to_real_maps_back_correctly():
    """scale_to_real should correctly map scaled coordinates back to real space."""
    cap = ScreenCapture(3840, 2160)
    scale = cap._compute_scale()
    assert scale < 1.0

    # A point in scaled space maps back by dividing by scale
    scaled_x, scaled_y = 200, 150
    real_x, real_y = cap.scale_to_real(scaled_x, scaled_y)

    expected_x = round(scaled_x / scale)
    expected_y = round(scaled_y / scale)
    assert real_x == expected_x
    assert real_y == expected_y


def test_scaled_dimensions_within_api_limits():
    """Scaled dimensions must satisfy both API constraints."""
    MAX_LONG_EDGE = 1568
    MAX_PIXELS = 1_150_000

    for w, h in [(3840, 2160), (5120, 2880), (7680, 4320), (2560, 1440), (1920, 1080)]:
        cap = ScreenCapture(w, h)
        sw = cap.scaled_width
        sh = cap.scaled_height

        long_edge = max(sw, sh)
        total_pixels = sw * sh

        assert long_edge <= MAX_LONG_EDGE, (
            f"Screen {w}x{h}: long edge {long_edge} exceeds {MAX_LONG_EDGE}"
        )
        assert total_pixels <= MAX_PIXELS, (
            f"Screen {w}x{h}: total pixels {total_pixels} exceeds {MAX_PIXELS}"
        )
