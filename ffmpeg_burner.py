"""Burn captions onto video using SRT subtitles filter."""
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Font config: maps caption style name to SRT/ASS rendering params.
# "file" is the .ttf filename in fonts/ (None = system font).
# "size" is the ASS/SRT fontsize for 1080x1920.
FONT_CONFIG: Dict[str, Dict] = {
    "Georgia":          {"file": None,                        "size": 24, "uppercase": False},
    "Playfair Display": {"file": "PlayfairDisplay-Bold.ttf",  "size": 23, "uppercase": False},
    "Bebas Neue":       {"file": "BebasNeue-Regular.ttf",     "size": 28, "uppercase": True},
    "Poppins":          {"file": "Poppins-SemiBold.ttf",      "size": 22, "uppercase": False},
    "Dancing Script":   {"file": "DancingScript-Bold.ttf",    "size": 27, "uppercase": False},
    "Oswald":           {"file": "Oswald-Medium.ttf",         "size": 24, "uppercase": True},
    "Permanent Marker": {"file": "PermanentMarker-Regular.ttf", "size": 21, "uppercase": False},
    "Abril Fatface":    {"file": "AbrilFatface-Regular.ttf",  "size": 23, "uppercase": False},
    "Quicksand":        {"file": "Quicksand-SemiBold.ttf",    "size": 23, "uppercase": False},
    "Lobster":          {"file": "Lobster-Regular.ttf",       "size": 24, "uppercase": False},
    "Lora":             {"file": "Lora-Regular.ttf",          "size": 23, "uppercase": False},
    "Inter":            {"file": "Inter-Regular.ttf",         "size": 23, "uppercase": False},
    "Montserrat":       {"file": "Montserrat-Regular.ttf",    "size": 22, "uppercase": False},
    "DM Sans":          {"file": "DMSans-Regular.ttf",        "size": 23, "uppercase": False},
    "Nunito":           {"file": "Nunito-Regular.ttf",        "size": 22, "uppercase": False},
    "Raleway":          {"file": "Raleway-Bold.ttf",          "size": 23, "uppercase": False},
    "Outfit":           {"file": "Outfit-Regular.ttf",        "size": 23, "uppercase": False},
}

GEORGIA_FALLBACK = FONT_CONFIG["Georgia"]


def get_font_config(caption_style: str) -> Dict:
    """Return font config for a caption style name."""
    return FONT_CONFIG.get(caption_style, GEORGIA_FALLBACK)


def _ffmpeg_path(path: str) -> str:
    """Convert a filesystem path to FFmpeg-safe forward-slash format."""
    return path.replace("\\", "/")


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _generate_srt(captions: List[Dict], uppercase: bool) -> str:
    """Generate SRT subtitle content from caption chunks."""
    lines = []
    for i, cap in enumerate(captions, 1):
        text = cap["text"]
        if uppercase:
            text = text.upper()
        start = _format_srt_time(cap["start"])
        end = _format_srt_time(cap["end"])
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def burn_captions(
    video_path: str,
    captions: List[Dict],
    font_config: Dict,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """Burn caption chunks onto a video using SRT subtitles."""
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

    uppercase = font_config.get("uppercase", False)
    srt_content = _generate_srt(captions, uppercase)

    # Resolve font name for force_style
    font_file = font_config.get("file")
    font_name = "Georgia"
    fontsdir = ""
    if font_file:
        # Use the caption style display name (key in FONT_CONFIG)
        for style_name, cfg in FONT_CONFIG.items():
            if cfg.get("file") == font_file:
                font_name = style_name
                break
        fontsdir = _ffmpeg_path(FONTS_DIR)

    fontsize = font_config["size"]
    force_style = (
        f"FontName={font_name},"
        f"FontSize={fontsize},"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"Outline=2,"
        f"Alignment=2,"
        f"MarginV=730,"
        f"Bold=0"
    )

    # Write SRT to same directory as input video so we can reference
    # it by bare filename — avoids Windows colon-in-path breaking
    # FFmpeg's filter option parser.
    video_dir = os.path.dirname(os.path.abspath(video_path))
    srt_fd, srt_path = tempfile.mkstemp(suffix=".srt", prefix="editorlab_", dir=video_dir)
    srt_filename = os.path.basename(srt_path)
    try:
        with os.fdopen(srt_fd, "w", encoding="utf-8") as f:
            f.write(srt_content)

        if fontsdir:
            vf = f"subtitles='{srt_filename}':fontsdir='{fontsdir}':force_style='{force_style}'"
        else:
            vf = f"subtitles='{srt_filename}':force_style='{force_style}'"

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "copy",
            output_path,
        ]

        # Debug logging
        print(f"[FFmpeg] Burning captions: {len(captions)} chunks, font={font_name}")
        print(f"[FFmpeg] SRT file: {srt_path}")
        print(f"[FFmpeg] SRT exists: {os.path.isfile(srt_path)}, size: {os.path.getsize(srt_path)} bytes")
        print(f"[FFmpeg] SRT filename in filter: {srt_filename}")
        print(f"[FFmpeg] cwd: {video_dir}")
        srt_preview = srt_content.split("\n")[:5]
        print(f"[FFmpeg] SRT first 5 lines: {srt_preview}")
        print(f"[FFmpeg] -vf: {vf}")
        print(f"[FFmpeg] Full command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=video_dir,
        )

        if result.returncode != 0:
            print(f"[FFmpeg] STDERR:\n{result.stderr[-2000:]}")
            raise RuntimeError(f"FFmpeg failed (code {result.returncode}): {result.stderr[-500:]}")

        print(f"[FFmpeg] Done: {output_path}")

    finally:
        try:
            os.unlink(srt_path)
        except OSError:
            pass
