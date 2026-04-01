import os
from typing import Dict, List, Any, Optional

import httpx

RENDER_TIMEOUT = httpx.Timeout(timeout=1800.0)


def _base_url():
    return os.environ.get("REMOTION_SERVICE_URL", "http://localhost:3100")


async def _post(path: str, json: dict, timeout: httpx.Timeout | float) -> dict:
    """POST to Remotion service, raising with the actual error body on failure."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{_base_url()}{path}", json=json)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = body.get("error", resp.text)
            except Exception:
                detail = resp.text
            print(f"[Remotion] {path} error ({resp.status_code}): {detail[:500]}")
            raise RuntimeError(
                f"Remotion {path} failed ({resp.status_code}): {detail}"
            )
        # Guard against non-JSON success responses (e.g. HTML error pages from proxy)
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            raw = resp.text[:500]
            print(f"[Remotion] {path} returned non-JSON ({resp.status_code}, {content_type}): {raw}")
            raise RuntimeError(
                f"Remotion {path} returned non-JSON response ({content_type}): {raw}"
            )
        return resp.json()


async def detect_silence(
    video_url: str,
    noise_threshold: float = -30,
    min_duration: float = 0.5,
) -> Dict[str, Any]:
    """Detect silent parts in a video via the Remotion service."""
    return await _post("/api/detect-silence", {
        "videoUrl": video_url,
        "noiseThreshold": noise_threshold,
        "minDuration": min_duration,
    }, timeout=300.0)


async def render_silence_removed(
    video_url: str,
    silent_parts: List[Dict],
    fps: float,
    duration_in_frames: int,
) -> Dict[str, Any]:
    """Render a video with silence removed via the Remotion service."""
    return await _post("/api/render-silence-removed", {
        "videoUrl": video_url,
        "silentParts": silent_parts,
        "fps": fps,
        "durationInFrames": duration_in_frames,
    }, timeout=RENDER_TIMEOUT)


async def render_variation(
    video_url: str,
    segments: List[Dict],
    captions: List[Dict],
    fps: float = 30,
    width: int = 1080,
    height: int = 1920,
    caption_style: str = "Georgia",
) -> Dict[str, Any]:
    """Render a hook variation with captions via the Remotion service."""
    return await _post("/api/render-variation", {
        "videoUrl": video_url,
        "segments": segments,
        "captions": captions,
        "fps": fps,
        "width": width,
        "height": height,
        "captionStyle": caption_style,
    }, timeout=RENDER_TIMEOUT)


async def health_check() -> bool:
    """Check if the Remotion service is healthy."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_base_url()}/health")
            return resp.status_code == 200
    except Exception:
        return False
