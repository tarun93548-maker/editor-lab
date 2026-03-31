import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Any

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DOWNLOAD_TIMEOUT = httpx.Timeout(timeout=600.0)
GROQ_TIMEOUT = httpx.Timeout(timeout=600.0)

WORD_CORRECTIONS = {
    "eliosa": "Elliosa",
    "eleosa": "Elliosa",
    "eliousa": "Elliosa",
}

_CORRECTION_PATTERN = re.compile(
    "|".join(re.escape(k) for k in WORD_CORRECTIONS),
    re.IGNORECASE,
)


def _apply_corrections(text: str) -> str:
    """Apply word corrections (case-insensitive) to text."""
    if not text:
        return text
    return _CORRECTION_PATTERN.sub(
        lambda m: WORD_CORRECTIONS[m.group(0).lower()], text
    )


def _extract_audio(video_path: str) -> str:
    """Extract audio from video as MP3 using ffmpeg."""
    video_size = os.path.getsize(video_path)
    print(f"[Audio] Extracting audio from {video_path} ({video_size // 1024}KB)...")
    audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
    subprocess.run([
        'ffmpeg', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', '-ab', '64k', '-f', 'mp3', '-y', audio_path
    ], capture_output=True, check=True)
    audio_size = os.path.getsize(audio_path)
    print(f"[Audio] Audio extracted: {audio_size // 1024}KB (was {video_size // 1024}KB video)")
    return audio_path


VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm')
AUDIO_EXTENSIONS = ('.mp3', '.wav')


def _sentences_from_words(words: List[Dict], max_words: int = 10) -> List[Dict]:
    """Build sentences from words by splitting on sentence-ending punctuation.

    Falls back to grouping every max_words words if no punctuation is found.
    """
    sentence_enders = re.compile(r'[.?!]$')
    sentences: List[Dict] = []
    buf: List[Dict] = []

    for w in words:
        buf.append(w)
        is_end = sentence_enders.search(w["word"].strip())
        if is_end or len(buf) >= max_words:
            sentences.append({
                "text": " ".join(b["word"] for b in buf).strip(),
                "start": buf[0]["start"],
                "end": buf[-1]["end"],
            })
            buf = []

    # Flush remaining words
    if buf:
        sentences.append({
            "text": " ".join(b["word"] for b in buf).strip(),
            "start": buf[0]["start"],
            "end": buf[-1]["end"],
        })

    return sentences


def build_caption_chunks(
    words: List[Dict],
    sentences: List[Dict] = None,
    words_per_chunk: int = 2,
) -> List[Dict]:
    """Group words into caption chunks of 2-3 words, never crossing sentence boundaries.

    Each chunk's end time persists to the next chunk's start (no gaps),
    but only within the same sentence.
    """
    if not words:
        return []

    sent_list = sentences or []

    def _word_sentence(w: Dict) -> int:
        """Return the sentence index a word belongs to by maximum overlap."""
        best_idx = -1
        best_overlap = 0.0
        for si, s in enumerate(sent_list):
            overlap_start = max(w["start"], s["start"])
            overlap_end = min(w["end"], s["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = si
        return best_idx

    # Tag each word with its sentence index
    tagged = [(_word_sentence(w), w) for w in words]

    chunks = []
    i = 0
    while i < len(tagged):
        cur_sent = tagged[i][0]
        # Collect words for this chunk, stopping at sentence boundary
        chunk_words = []
        while len(chunk_words) < words_per_chunk and i < len(tagged) and tagged[i][0] == cur_sent:
            chunk_words.append(tagged[i][1])
            i += 1
        # If remaining words in this sentence fit in one chunk (≤3), take them all
        if i < len(tagged) and tagged[i][0] == cur_sent:
            remaining_in_sent = 0
            j = i
            while j < len(tagged) and tagged[j][0] == cur_sent:
                remaining_in_sent += 1
                j += 1
            if len(chunk_words) + remaining_in_sent <= 3:
                while i < len(tagged) and tagged[i][0] == cur_sent:
                    chunk_words.append(tagged[i][1])
                    i += 1

        text = " ".join(w["word"] for w in chunk_words)
        chunks.append({
            "text": _apply_corrections(text),
            "start": chunk_words[0]["start"],
            "end": chunk_words[-1]["end"],
            "_sent": cur_sent,
        })

    # Persist: extend each chunk's end to the next chunk's start,
    # but only within the same sentence
    for idx in range(len(chunks) - 1):
        if chunks[idx]["_sent"] == chunks[idx + 1]["_sent"]:
            chunks[idx]["end"] = chunks[idx + 1]["start"]

    # Remove internal tag
    for c in chunks:
        del c["_sent"]

    return chunks


async def transcribe_from_url(video_url: str) -> Dict[str, Any]:
    """Download video from URL, extract audio, then transcribe with Groq Whisper."""
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        suffix = ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
    audio_path = _extract_audio(tmp_path)
    try:
        return await _call_groq(audio_path)
    finally:
        for p in (audio_path, tmp_path):
            try:
                os.unlink(p)
            except OSError:
                pass


async def _call_groq(audio_path: str) -> Dict[str, Any]:
    """Send an audio file to Groq Whisper and return parsed results."""
    async with httpx.AsyncClient(timeout=GROQ_TIMEOUT) as client:
        with open(audio_path, "rb") as f:
            resp = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '')}"},
                data={
                    "model": "whisper-large-v3",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                },
                files={"file": ("audio.mp3", f, "audio/mpeg")},
            )
        resp.raise_for_status()
        data = resp.json()

    print(f"[Groq] Response keys: {list(data.keys())}")
    print(f"[Groq] Response preview: {str(data)[:200]}")

    words_data = data.get("words") or []
    segments_data = data.get("segments") or []

    words = []
    for w in words_data:
        words.append({
            "word": _apply_corrections(w["word"]),
            "start": float(w["start"]),
            "end": float(w["end"]),
        })

    sentences = []
    for seg in segments_data:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        # Tighten sentence boundaries to actual word timestamps
        # (Groq segments include trailing silence after last word)
        seg_words = [w for w in words if w["start"] >= seg_start - 0.01 and w["end"] <= seg_end + 0.01]
        if seg_words:
            tight_start = seg_words[0]["start"]
            tight_end = seg_words[-1]["end"]
        else:
            tight_start = seg_start
            tight_end = seg_end
        print(f"[Groq] Sentence: {seg_start:.3f}-{seg_end:.3f} -> {tight_start:.3f}-{tight_end:.3f} "
              f"(trimmed {(seg_end - tight_end)*1000:.0f}ms tail) \"{_apply_corrections(seg['text']).strip()[:40]}\"")
        sentences.append({
            "text": _apply_corrections(seg["text"]).strip(),
            "start": tight_start,
            "end": tight_end,
        })

    # If Groq returned no segments, build sentences from words
    if not sentences and words:
        sentences = _sentences_from_words(words)
        print(f"[Groq] Built {len(sentences)} sentences from {len(words)} words (segments was empty)")

    full_text = _apply_corrections(data.get("text") or "")

    return {
        "text": full_text,
        "words": words,
        "sentences": sentences,
    }


async def transcribe_from_file(file_path: str) -> Dict[str, Any]:
    """Transcribe a local audio/video file with Groq Whisper.

    Always extracts audio first to minimize upload size.
    """
    audio_path = _extract_audio(file_path)
    try:
        return await _call_groq(audio_path)
    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass
