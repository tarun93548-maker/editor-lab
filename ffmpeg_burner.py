"""Burn captions onto video using FFmpeg drawtext filters via filter_script."""
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Font config: maps caption style name to drawtext rendering params.
# "file" is the .ttf filename in fonts/ (None = system font).
# "size" is the drawtext fontsize for 1080x1920.
FONT_CONFIG: Dict[str, Dict] = {
    "Georgia":          {"file": None,                        "size": 42, "uppercase": False},
    "Playfair Display": {"file": "PlayfairDisplay-Bold.ttf",  "size": 40, "uppercase": False},
    "Bebas Neue":       {"file": "BebasNeue-Regular.ttf",     "size": 48, "uppercase": True},
    "Poppins":          {"file": "Poppins-SemiBold.ttf",      "size": 38, "uppercase": False},
    "Dancing Script":   {"file": "DancingScript-Bold.ttf",    "size": 46, "uppercase": False},
    "Oswald":           {"file": "Oswald-Medium.ttf",         "size": 42, "uppercase": True},
    "Permanent Marker": {"file": "PermanentMarker-Regular.ttf", "size": 37, "uppercase": False},
    "Abril Fatface":    {"file": "AbrilFatface-Regular.ttf",  "size": 39, "uppercase": False},
    "Quicksand":        {"file": "Quicksand-SemiBold.ttf",    "size": 39, "uppercase": False},
    "Lobster":          {"file": "Lobster-Regular.ttf",       "size": 42, "uppercase": False},
    "Lora":             {"file": "Lora-Regular.ttf",          "size": 40, "uppercase": False},
    "Inter":            {"file": "Inter-Regular.ttf",         "size": 39, "uppercase": False},
    "Montserrat":       {"file": "Montserrat-Regular.ttf",    "size": 38, "uppercase": False},
    "DM Sans":          {"file": "DMSans-Regular.ttf",        "size": 39, "uppercase": False},
    "Nunito":           {"file": "Nunito-Regular.ttf",        "size": 38, "uppercase": False},
    "Raleway":          {"file": "Raleway-Bold.ttf",          "size": 39, "uppercase": False},
    "Outfit":           {"file": "Outfit-Regular.ttf",        "size": 39, "uppercase": False},
}

GEORGIA_FALLBACK = FONT_CONFIG["Georgia"]


def get_font_config(caption_style: str) -> Dict:
    """Return font config for a caption style name."""
    return FONT_CONFIG.get(caption_style, GEORGIA_FALLBACK)


def _escape_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")
    text = text.replace(":", "\\:")
    text = text.replace(";", "\\;")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace("%", "%%")
    return text


def _ffmpeg_fontpath(font_file: str) -> str:
    """Build an FFmpeg-safe font file path with escaped colon for Windows drive letter."""
    full = os.path.join(FONTS_DIR, font_file)
    # Forward slashes, escape colon for filter parser: C\:/Users/...
    return full.replace("\\", "/").replace(":", "\\:")


def _build_filter_chain(
    captions: List[Dict],
    font_config: Dict,
) -> str:
    """Build a drawtext filter chain string for all caption chunks."""
    font_file = font_config.get("file")
    fontsize = font_config["size"]
    uppercase = font_config.get("uppercase", False)

    # Resolve font: use fontfile= for custom fonts, font= for system Georgia
    use_fontfile = False
    fontpath = ""
    if font_file:
        full_path = os.path.join(FONTS_DIR, font_file)
        if os.path.isfile(full_path):
            fontpath = _ffmpeg_fontpath(font_file)
            use_fontfile = True
            print(f"[FFmpeg] Using fontfile: {full_path} (exists: True)")
        else:
            print(f"[FFmpeg] Warning: font not found: {full_path}, falling back to system Georgia")
    if not use_fontfile:
        print(f"[FFmpeg] Using system font: Georgia")

    filters = []
    for cap in captions:
        text = cap["text"]
        if uppercase:
            text = text.upper()
        text = _escape_drawtext(text)

        start = f"{cap['start']:.3f}"
        end = f"{cap['end']:.3f}"

        if use_fontfile:
            font_part = f"fontfile='{fontpath}'"
        else:
            font_part = "font='Georgia'"

        dt = (
            f"drawtext={font_part}"
            f":fontsize={fontsize}"
            f":fontcolor=white"
            f":borderw=2"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=h*0.62"
            f":text='{text}'"
            f":enable='between(t,{start},{end})'"
        )
        filters.append(dt)

    return ",".join(filters)


def burn_captions(
    video_path: str,
    captions: List[Dict],
    font_config: Dict,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """Burn caption chunks onto a video using drawtext filters via filter_script."""
    if not captions:
        shutil.copy2(video_path, output_path)
        return

    # De-overlap: trim end times so one caption leaves before the next arrives.
    for i in range(1, len(captions)):
        if captions[i]["start"] < captions[i - 1]["end"]:
            captions[i - 1]["end"] = captions[i]["start"] - 0.033

    # Sticky captions: each caption stays until the next one arrives.
    for i in range(len(captions) - 1):
        captions[i]["end"] = captions[i + 1]["start"] - 0.033

    filter_chain = _build_filter_chain(captions, font_config)

    # Write filter chain to a temp file — avoids command-line length limits
    # and keeps all drawtext entries out of the shell argument.
    script_fd, script_path = tempfile.mkstemp(suffix=".txt", prefix="editorlab_vf_")
    try:
        with os.fdopen(script_fd, "w", encoding="utf-8") as f:
            f.write(filter_chain)

        video_abs = os.path.abspath(video_path)
        output_abs = os.path.abspath(output_path)
        script_abs = os.path.abspath(script_path)

        cmd = f'ffmpeg -y -i "{video_abs}" -filter_script:v "{script_abs}" -c:v libx264 -preset fast -crf 18 -c:a copy "{output_abs}"'

        # Debug logging
        font_file = font_config.get("file", "Georgia.ttf")
        print(f"[FFmpeg] Burning captions: {len(captions)} chunks, font={font_file}")
        print(f"[FFmpeg] Filter script: {script_path} ({os.path.getsize(script_path)} bytes)")
        print(f"[FFmpeg] Full command: {cmd}")
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            print(f"[FFmpeg] STDERR:\n{result.stderr[-2000:]}")
            raise RuntimeError(f"FFmpeg failed (code {result.returncode}): {result.stderr[-500:]}")

        print(f"[FFmpeg] Done: {output_path}")

    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
