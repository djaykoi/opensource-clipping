import html
import importlib.util
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import textwrap
import time
import urllib.parse
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
import requests
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from PIL import Image, ImageDraw, ImageFont
from yt_dlp import YoutubeDL

FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"

def _load_studio_internal_module(file_name: str, module_alias: str):
    module_path = os.path.join(os.path.dirname(__file__), file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_helpers = _load_studio_internal_module("helpers.py", "clipping_studio_helpers")
_ffmpeg_utils = _load_studio_internal_module("ffmpeg_utils.py", "clipping_studio_ffmpeg_utils")
format_seconds = _helpers.format_seconds
escape_ffmpeg_filter_value = _helpers.escape_ffmpeg_filter_value
detect_video_encoder = _ffmpeg_utils.detect_video_encoder
get_ts_encode_args = _ffmpeg_utils.get_ts_encode_args
get_mp4_encode_args = _ffmpeg_utils.get_mp4_encode_args
open_ffmpeg_video_writer = _ffmpeg_utils.open_ffmpeg_video_writer
build_ffmpeg_progress_cmd = _ffmpeg_utils.build_ffmpeg_progress_cmd
run_ffmpeg_with_progress = _ffmpeg_utils.run_ffmpeg_with_progress


def buat_thumbnail(video_path, output_image_path, teks, cfg):
    """
    Extract a frame from the video, composite the clip title on top, and save as a thumbnail image.

    Args:
        input_video (str): Path to the source video file.
        output_image (str): Destination path for the generated JPEG thumbnail.
        start_clip (float): Clip start time in seconds (to locate a frame).
        end_clip (float): Clip end time in seconds.
        judul (str): The title text to be written on the thumbnail.
        rasio (str): Target output ratio string ('9:16' or '16:9').
        cfg: Runtime configuration object.

    Returns:
        str: The path to the created image, or None if creation fails.

    Side Effects:
        Uses `cv2.VideoCapture` to extract a frame from `input_video`.
        Writes a JPEG file to `output_image`.

    Raises:
        Exception: If image processing or saving fails.
    """
    if getattr(cfg, "thumb_style", "classic") == "modern":
        return _thumbnail_modern(video_path, output_image_path, teks, cfg)

    if not os.path.exists(cfg.file_font_thumbnail):
        urllib.request.urlretrieve(cfg.url_font_thumbnail, cfg.file_font_thumbnail)

    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, 5000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return

    img = Image.alpha_composite(
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA"),
        Image.new("RGBA", (frame.shape[1], frame.shape[0]), (0, 0, 0, 128)),
    ).convert("RGB")

    draw = ImageDraw.Draw(img)
    font_sz = int(img.size[0] * 0.12)
    font = ImageFont.truetype(cfg.file_font_thumbnail, font_sz)
    lines = textwrap.wrap(teks, width=12)

    y_text = (img.size[1] - (len(lines) * (font_sz + 10))) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x_text = (img.size[0] - line_w) // 2
        draw.text(
            (x_text, y_text),
            line,
            font=font,
            fill="white",
            stroke_width=5,
            stroke_fill="black",
        )
        y_text += font_sz + 10

    img.save(output_image_path)




MODERN_FONT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "Unbounded-Bold.ttf")
)


def _pick_frame(video_path, at_seconds):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, at_seconds * 1000)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _thumbnail_modern(video_path, output_image_path, teks, cfg):
    """Clean thumbnail: one bold geometric title, no outline, soft bottom gradient."""
    # Skip the hook + transition so the frame comes from the clip itself.
    at = float(getattr(cfg, "durasi_hook", 3)) + float(getattr(cfg, "mire_duration", 1.0)) + 4.0
    frame = _pick_frame(video_path, at)
    if frame is None:
        frame = _pick_frame(video_path, 1.0)
    if frame is None:
        return None

    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    w, h = img.size

    # Bottom gradient: transparent at 55% height to 75% black at the bottom.
    grad = Image.new("L", (1, h), 0)
    start = int(h * 0.55)
    for y in range(start, h):
        grad.putpixel((0, y), int(190 * ((y - start) / max(1, h - start)) ** 1.4))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    shade.putalpha(grad.resize((w, h)))
    img = Image.alpha_composite(img, shade)

    font_path = getattr(cfg, "thumb_font", None) or MODERN_FONT
    text = (teks or "").strip().upper()
    draw = ImageDraw.Draw(img)

    # Largest size that fits 82% of the width on one line.
    size = int(w * 0.16)
    tracking = 0.04
    while size > 12:
        font = ImageFont.truetype(font_path, size)
        spacing = int(size * tracking)
        total = sum(draw.textlength(c, font=font) for c in text) + spacing * max(0, len(text) - 1)
        if total <= w * 0.82:
            break
        size -= 2

    ascent, descent = font.getmetrics()
    y = int(h * 0.80) - ascent
    x = (w - total) / 2
    for c in text:
        draw.text((x, y), c, font=font, fill=(255, 255, 255, 255))
        x += draw.textlength(c, font=font) + spacing

    # Thin accent line above the title.
    line_w = int(w * 0.08)
    ly = y - int(size * 0.45)
    draw.rectangle([(w - line_w) // 2, ly, (w + line_w) // 2, ly + max(2, size // 22)], fill=(255, 255, 255, 230))

    img.convert("RGB").save(output_image_path, quality=92)
    return output_image_path
