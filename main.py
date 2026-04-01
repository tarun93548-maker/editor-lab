import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
import uuid
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from jobs import job_store
from hook_generator import generate_hook_variations
import httpx
import r2_storage
import groq_transcriber
import remotion_client
import ffmpeg_burner


def _compute_audible_segments(silence_data: Dict) -> List[Dict]:
    """Invert silent parts to get audible segments in the clean video timeline.

    Mirrors the same inversion that SilenceRemoval.tsx does, then maps each
    audible segment to its position in the concatenated (clean) video.
    """
    silent_parts = silence_data["silentParts"]
    fps = silence_data["fps"]
    duration_in_frames = silence_data["durationInFrames"]

    sorted_parts = sorted(silent_parts, key=lambda p: p["startFrame"])

    # Invert: gaps between silent parts are audible (same algo as SilenceRemoval.tsx)
    audible_original = []
    cursor = 0
    for sp in sorted_parts:
        if sp["startFrame"] > cursor:
            audible_original.append({
                "startFrame": cursor,
                "endFrame": sp["startFrame"],
            })
        cursor = max(cursor, sp["endFrame"])
    if cursor < duration_in_frames:
        audible_original.append({
            "startFrame": cursor,
            "endFrame": duration_in_frames,
        })

    # Map to clean video timeline (segments are concatenated sequentially)
    audible_segments = []
    clean_cursor = 0.0
    for i, seg in enumerate(audible_original):
        duration = (seg["endFrame"] - seg["startFrame"]) / fps
        audible_segments.append({
            "start": round(clean_cursor, 6),
            "end": round(clean_cursor + duration, 6),
            "index": i,
        })
        clean_cursor += duration

    return audible_segments


def _map_sentences_to_segments(
    sentences: List[Dict], audible_segments: List[Dict]
) -> None:
    """Tag each sentence with the audible segment it overlaps most."""
    for sent in sentences:
        best_idx = None
        best_overlap = 0.0
        for seg in audible_segments:
            overlap_start = max(sent["start"], seg["start"])
            overlap_end = min(sent["end"], seg["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = seg["index"]
        sent["audible_segment_index"] = best_idx

app = FastAPI(title="Editor Lab")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"

for d in [UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --- Routes ---

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/health")
async def health():
    remotion_ok = await remotion_client.health_check()
    return {
        "status": "ok",
        "remotion": remotion_ok,
    }


@app.post("/upload")
async def upload_video(
    file: UploadFile = File(None),
    drive_url: str = Form(None),
    preview_mode: str = Form("false"),
    caption_style: str = Form("Georgia"),
):
    job_id = str(uuid.uuid4())
    is_preview = preview_mode.lower() in ("true", "1", "yes")
    job_store.create(job_id)
    job_store.update(job_id, caption_style=caption_style)

    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
            raise HTTPException(400, "Unsupported file type")

        # Save to temp, upload to R2
        tmp_path = os.path.join(tempfile.gettempdir(), f"{job_id}{ext}")
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            result = r2_storage.upload_file(tmp_path, prefix="originals")
            original_url = result["url"]
            original_key = result["key"]
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        job_store.update(
            job_id,
            original_url=original_url,
            original_key=original_key,
            status="uploaded",
            message="File uploaded",
        )

    elif drive_url:
        original_url = drive_url
        job_store.update(
            job_id,
            original_url=drive_url,
            status="uploaded",
            message="URL received",
        )

    else:
        raise HTTPException(400, "No file or URL provided")

    # Auto-start pipeline (frontend expects processing to begin on upload)
    asyncio.create_task(_run_pipeline(job_id, preview_mode=is_preview))
    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job



@app.post("/select-variation/{job_id}")
async def select_variation(job_id: str, payload: dict):
    """Frontend calls this to select AND render a variation in one shot."""
    variation_index = payload.get("variation_index")
    if variation_index is None:
        raise HTTPException(400, "Missing variation_index")
    return await _select_and_render(job_id, variation_index)


@app.post("/job/{job_id}/render/{variation_index}")
async def render_variation_legacy(job_id: str, variation_index: int):
    return await _select_and_render(job_id, variation_index)


def _build_segments(variation: dict, job: dict) -> List[Dict]:
    """Build render segments for a variation.

    Only cuts around the hook sentence. Body plays as continuous chunks.
    Max 3 segments: hook + body-before + body-after.
    """
    audible_segments = job.get("audible_segments") or []
    transcript = job.get("transcript") or {}
    all_sentences = transcript.get("sentences") or []
    script = variation.get("script") or []
    sentence_order = variation.get("sentence_order") or []
    hook_type = variation.get("hook_type", "AS_IS")

    # Clean video duration = end of last audible segment (or last sentence)
    clean_end = audible_segments[-1]["end"] if audible_segments else 0.0
    if clean_end == 0.0 and all_sentences:
        clean_end = float(all_sentences[-1]["end"])
    if clean_end == 0.0 and script:
        clean_end = max(float(e["end"]) for e in script)

    def _clamp(entry: dict) -> tuple:
        groq_start = float(entry["start"])
        groq_end = float(entry["end"])
        seg_idx = entry.get("audible_segment_index")
        if seg_idx is not None and audible_segments:
            aseg = audible_segments[seg_idx]
            cs = max(groq_start, aseg["start"])
            ce = min(groq_end, aseg["end"])
            if ce > cs:
                return (cs, ce)
            # Clamped duration is negative/zero — mapping is off.
            # Fall through to raw Groq timestamps instead of remapping
            # to a different segment (which could be wrong).
            print(f"  [CLAMP] Negative clamp for audible[{seg_idx}], "
                  f"using raw groq: {groq_start:.3f}-{groq_end:.3f}")
        return (groq_start, groq_end)

    first_sent_idx = script[0].get("sentence_index", 0) if script else 0
    is_rearranged = len(script) > 0 and first_sent_idx != 0

    is_trim = False
    if is_rearranged and sentence_order:
        expected = list(range(sentence_order[0], sentence_order[0] + len(sentence_order)))
        is_trim = (sentence_order == expected)

    segments = []

    if not is_rearranged or not script:
        segments.append({"start": 0.0, "end": clean_end})
    elif is_trim:
        body_start, _ = _clamp(script[0])
        segments.append({"start": body_start, "end": clean_end})
    else:
        # Collect ALL hook sentences — not just the first one.
        hook_entries = [e for e in script if e.get("section") == "hook"]
        if not hook_entries:
            hook_entries = [script[0]]

        # Clamp each hook entry and find the overall span.
        hook_start = float("inf")
        hook_end = 0.0
        for entry in hook_entries:
            cs, ce = _clamp(entry)
            hook_start = min(hook_start, cs)
            hook_end = max(hook_end, ce)
            print(f"  [HOOK DEBUG] hook sentence: idx={entry.get('sentence_index','?')} "
                  f"seg={entry.get('audible_segment_index','?')} "
                  f"groq={float(entry['start']):.3f}-{float(entry['end']):.3f} "
                  f"clamped={cs:.3f}-{ce:.3f} "
                  f"\"{entry.get('text','')[:50]}\"")
        print(f"  [HOOK DEBUG] combined hook span: {hook_start:.3f}-{hook_end:.3f} "
              f"({len(hook_entries)} sentences)")

        if hook_end > hook_start:
            segments.append({"start": hook_start, "end": hook_end})
        if hook_start > 0.001:
            segments.append({"start": 0.0, "end": hook_start})
        if hook_end < clean_end - 0.001:
            segments.append({"start": hook_end, "end": clean_end})

    return segments


async def _render_one_variation(
    job_id: str, variation: dict, var_idx: int, total: int,
    clean_url: str, job: dict,
) -> dict | None:
    """Two-pass render of a single variation. Returns render info or None on failure."""
    hook_type = variation.get("hook_type", "?")
    var_id = variation.get("id", var_idx)
    print(f"[JOB {job_id}] Rendering variation {var_idx + 1}/{total} ({hook_type})...")
    job_store.update(
        job_id,
        status="rendering",
        step="rendering",
        message=f"Rendering variation {var_idx + 1}/{total} ({hook_type})...",
    )

    segments = _build_segments(variation, job)
    total_dur = sum(s["end"] - s["start"] for s in segments)
    print(f"[JOB {job_id}]   {len(segments)} segments, {total_dur:.2f}s")
    for i, seg in enumerate(segments):
        print(f"    seg[{i}] {seg['start']:.3f} -> {seg['end']:.3f} "
              f"({seg['end'] - seg['start']:.3f}s)")

    caption_style = job.get("caption_style", "Georgia")

    try:
        # Pass 1: render without captions
        pass1 = await remotion_client.render_variation(
            clean_url, segments, captions=[], fps=30
        )
        nocap_url = pass1["outputUrl"]

        # Transcribe for synced captions
        transcript = await groq_transcriber.transcribe_from_url(nocap_url)

        # --- Debug: Pass 2 transcription results ---
        p2_sents = transcript.get("sentences", [])
        p2_words = transcript.get("words", [])
        p2_duration = p2_sents[-1]["end"] if p2_sents else 0
        print(f"[JOB {job_id}] ===== PASS 2 TRANSCRIPTION RESULTS =====")
        print(f"[JOB {job_id}]   Source: {nocap_url[:80]}...")
        print(f"[JOB {job_id}]   Total duration: {p2_duration:.3f}s")
        print(f"[JOB {job_id}]   Sentences ({len(p2_sents)}):")
        for si, s in enumerate(p2_sents):
            print(f"[JOB {job_id}]     sent[{si}] {s['start']:.3f}-{s['end']:.3f} \"{s['text'][:60]}\"")
        print(f"[JOB {job_id}]   Words (first 20 of {len(p2_words)}):")
        for wi, w in enumerate(p2_words[:20]):
            print(f"[JOB {job_id}]     word[{wi}] {w['start']:.3f}-{w['end']:.3f} \"{w['word']}\"")
        # --- End debug ---

        captions = groq_transcriber.build_caption_chunks(
            transcript["words"], transcript["sentences"]
        )

        # --- Debug: Caption chunks for pass 2 ---
        print(f"[JOB {job_id}]   Caption chunks ({len(captions)}):")
        for ci, c in enumerate(captions):
            print(f"[JOB {job_id}]     chunk[{ci}] {c['start']:.3f}-{c['end']:.3f} \"{c['text']}\"")
        print(f"[JOB {job_id}] ===== END TRANSCRIPTION =====")
        # --- End debug ---

        # Burn captions with FFmpeg (replaces Remotion pass 2)
        tmp_nocap = os.path.join(tempfile.gettempdir(), f"{job_id}-{var_id}-nocap.mp4")
        tmp_captioned = os.path.join(tempfile.gettempdir(), f"{job_id}-{var_id}-captioned.mp4")

        try:
            # Download pass 1 video from R2 (retry up to 3 times —
            # R2 occasionally drops the connection before the full body
            # is transferred on large files).
            print(f"[JOB {job_id}]   Downloading pass 1 for FFmpeg...")
            dl_ok = False
            for dl_attempt in range(1, 4):
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as dl_client:
                        dl_resp = await dl_client.get(nocap_url)
                        dl_resp.raise_for_status()
                        expected = dl_resp.headers.get("content-length")
                        body = dl_resp.content
                        if expected and len(body) != int(expected):
                            raise IOError(
                                f"Incomplete download: got {len(body)} bytes, "
                                f"expected {expected}"
                            )
                        with open(tmp_nocap, "wb") as f:
                            f.write(body)
                    dl_ok = True
                    break
                except Exception as dl_err:
                    print(f"[JOB {job_id}]   R2 download attempt {dl_attempt}/3 failed: {dl_err}")
                    if dl_attempt < 3:
                        await asyncio.sleep(2)
            if not dl_ok:
                raise RuntimeError("R2 download failed after 3 attempts")

            # Burn captions via FFmpeg + ASS
            font_cfg = ffmpeg_burner.get_font_config(caption_style)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, ffmpeg_burner.burn_captions,
                tmp_nocap, captions, font_cfg, tmp_captioned,
            )

            # Upload captioned video to R2
            r2_result = r2_storage.upload_file(tmp_captioned, prefix="variations")
            render_url = r2_result["url"]
            render_key = r2_result["key"]
            filename = render_key.split("/")[-1] if "/" in render_key else render_key

        finally:
            for tmp in [tmp_nocap, tmp_captioned]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        print(f"[JOB {job_id}] Variation {var_idx + 1}/{total} complete: {render_url}")
        return {
            "url": render_url,
            "key": render_key,
            "filename": filename,
            "status": "done",
        }

    except Exception as e:
        print(f"[JOB {job_id}] Variation {var_idx + 1}/{total} ({hook_type}) FAILED: {e}")
        traceback.print_exc()
        return None


async def _render_all_variations(job_id: str):
    """Render every variation sequentially, updating the job as each completes."""
    job = job_store.get(job_id)
    variations = job.get("variations") or []
    clean_url = job.get("clean_url", "")
    total = len(variations)

    # Initialise renders dict — all start as queued
    renders = {}
    for i, v in enumerate(variations):
        renders[str(v.get("id", i))] = {"status": "queued"}
    job_store.update(job_id, renders=renders)

    for idx, variation in enumerate(variations):
        var_id = str(variation.get("id", idx))

        # Mark this one as rendering
        renders[var_id] = {"status": "rendering"}
        job_store.update(job_id, renders=renders)

        # Re-read job so _build_segments sees latest data
        job = job_store.get(job_id)

        result = await _render_one_variation(
            job_id, variation, idx, total, clean_url, job,
        )

        if result:
            renders[var_id] = result
        else:
            renders[var_id] = {"status": "failed"}

        # Persist after each variation so frontend can show results immediately
        job_store.update(job_id, renders=renders)

    job_store.update(
        job_id,
        status="complete",
        step="complete",
        message="All variations rendered",
        progress=100,
    )
    print(f"[JOB {job_id}] All {total} variations rendered")


async def _select_and_render(job_id: str, variation_index: int):
    """Re-render a single variation on demand (legacy / manual trigger)."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    variations = job.get("variations") or []
    variation = None
    for v in variations:
        if v.get("id") == variation_index:
            variation = v
            break
    if not variation:
        raise HTTPException(404, "Variation not found")

    clean_url = job.get("clean_url", "")
    result = await _render_one_variation(
        job_id, variation, variation_index, len(variations), clean_url, job,
    )
    if not result:
        raise HTTPException(500, "Render failed")

    renders = job.get("renders") or {}
    renders[str(variation_index)] = result
    job_store.update(
        job_id,
        renders=renders,
        render_url=result["url"],
        render_key=result["key"],
        status="complete",
        message="Render complete",
    )
    return {"filename": result["filename"], "render_url": result["url"]}


@app.get("/preview/{job_id}")
async def preview_clean(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    clean_url = job.get("clean_url")
    if not clean_url:
        raise HTTPException(404, "Clean video not ready yet")
    return {"clean_url": clean_url}


@app.post("/job/{job_id}/continue")
async def continue_pipeline(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") != "preview_paused":
        raise HTTPException(400, "Job is not paused for preview")

    job_store.update(job_id, status="processing", message="Resuming pipeline...",
                     progress=55)
    asyncio.create_task(_resume_after_preview(job_id))
    return {"status": "resumed"}


@app.get("/download/{job_id}/{filename}")
async def download_file(job_id: str, filename: str):
    """Proxy the R2 file with Content-Disposition: attachment so the browser
    downloads it instead of navigating away from the page."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Look up render URL: check per-variation renders dict first, fall back to latest
    render_url = None
    renders = job.get("renders") or {}
    for entry in renders.values():
        if entry.get("filename") == filename:
            render_url = entry["url"]
            break
    if not render_url:
        render_url = job.get("render_url")
    if not render_url:
        raise HTTPException(404, "Render not available")

    async def _stream():
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", render_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

    return StreamingResponse(
        _stream(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Pipeline ---

async def _run_pipeline(job_id: str, preview_mode: bool = False):
    try:
        job = job_store.get(job_id)
        original_url = job.get("original_url", "")

        # Step 1: Detect silence
        job_store.update(job_id, status="processing", step="detecting_silence",
                         message="Detecting silence...", progress=10)
        silence_data = await remotion_client.detect_silence(original_url, min_duration=0.4)
        print(f"[JOB {job_id}] Silence detected: {len(silence_data['silentParts'])} silent parts")

        # Trim leading silence: if the video starts with a short quiet gap
        # that the detector missed (< 0.5s), inject a synthetic silent part
        # so Remotion removes it. Only affects the leading edge.
        sparts = silence_data["silentParts"]
        if sparts:
            earliest = min(sp["startFrame"] for sp in sparts)
            if 0 < earliest <= int(0.5 * silence_data["fps"]):
                print(f"[JOB {job_id}] Trimming leading silence: frames 0-{earliest}")
                sparts.append({"startFrame": 0, "endFrame": earliest})

        # Compute audible segments (inverted silence) in the clean video timeline
        audible_segments = _compute_audible_segments(silence_data)
        job_store.update(job_id, audible_segments=audible_segments)
        print(f"[JOB {job_id}] Audible segments: {len(audible_segments)}")
        for i, seg in enumerate(audible_segments):
            print(f"  audible[{i}] {seg['start']:.3f} -> {seg['end']:.3f} ({seg['end'] - seg['start']:.3f}s)")

        # Step 2: Render silence-removed video
        job_store.update(job_id, step="removing_silence",
                         message="Removing silence...", progress=25)
        clean_result = await remotion_client.render_silence_removed(
            original_url,
            silence_data["silentParts"],
            silence_data["fps"],
            silence_data["durationInFrames"],
        )
        clean_url = clean_result["outputUrl"]
        job_store.update(job_id, clean_url=clean_url, clean_key=clean_result["r2Key"])
        print(f"[JOB {job_id}] Silence removed: {clean_url}")

        # If preview mode, pause here for user review
        if preview_mode:
            job_store.update(
                job_id,
                status="preview_paused",
                message="Silence removal complete — preview ready",
                progress=45,
                silence_stats={
                    "silence_regions_found": len(silence_data["silentParts"]),
                },
            )
            print(f"[JOB {job_id}] Preview mode: paused after silence removal")
            return

        # Continue with transcription and hook generation
        await _run_pipeline_post_silence(job_id, clean_url)

    except Exception as e:
        print(f"[JOB {job_id}] Pipeline failed: {e}")
        traceback.print_exc()
        job_store.update(job_id, status="error", message=str(e))


async def _resume_after_preview(job_id: str):
    """Resume pipeline after user approves the preview."""
    try:
        job = job_store.get(job_id)
        clean_url = job.get("clean_url", "")
        await _run_pipeline_post_silence(job_id, clean_url)
    except Exception as e:
        print(f"[JOB {job_id}] Pipeline failed after resume: {e}")
        traceback.print_exc()
        job_store.update(job_id, status="error", message=str(e))


async def _run_pipeline_post_silence(job_id: str, clean_url: str):
    """Transcribe, build captions, and generate hook variations."""
    # Step 3: Transcribe clean video
    job_store.update(job_id, status="processing", step="transcribing",
                     message="Transcribing...", progress=50)
    print(f"[JOB {job_id}] Transcribing CLEAN video: {clean_url[:80]}...")
    transcript = await groq_transcriber.transcribe_from_url(clean_url)
    sents = transcript.get("sentences", [])
    last_end = sents[-1]["end"] if sents else 0
    print(f"[JOB {job_id}] Transcription complete: {len(sents)} sentences, last sentence ends at {last_end:.2f}s")

    # Map each sentence to its audible segment (frame-accurate boundaries)
    job = job_store.get(job_id)
    audible_segments = job.get("audible_segments", [])
    if audible_segments:
        _map_sentences_to_segments(sents, audible_segments)
        for i, s in enumerate(sents):
            print(f"  sentence[{i}] -> audible_segment[{s.get('audible_segment_index')}] "
                  f"groq={s['start']:.3f}-{s['end']:.3f} \"{s['text'][:40]}\"")

    # Step 4: Build caption chunks
    caption_chunks = groq_transcriber.build_caption_chunks(transcript["words"], transcript["sentences"])
    job_store.update(job_id, transcript=transcript, caption_chunks=caption_chunks)
    print(f"[JOB {job_id}] Caption chunks built: {len(caption_chunks)}")

    # Step 5: Generate hook variations
    job_store.update(job_id, step="generating_hooks",
                     message="Generating hook variations...", progress=70)
    loop = asyncio.get_event_loop()
    variations = await loop.run_in_executor(None, generate_hook_variations, transcript, last_end)
    print(f"[JOB {job_id}] Hook generation complete: {len(variations)} variations")

    # Sort variations so AS_IS renders last
    variations.sort(key=lambda v: 1 if v.get("hook_type") == "AS_IS" else 0)

    job_store.update(
        job_id,
        variations=variations,
        progress=75,
        status="rendering_all",
        step="rendering",
        message="Rendering all variations...",
    )

    # Step 6: Auto-render all variations
    await _render_all_variations(job_id)



