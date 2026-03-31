import os
import whisper
from typing import Dict, Any

_model = None


def _get_model():
    global _model
    if _model is None:
        print("[TRANSCRIBER] Loading whisper large model...")
        _model = whisper.load_model("large")
        print("[TRANSCRIBER] Model loaded")
    return _model


def transcribe_video(video_path: str) -> Dict[str, Any]:
    print(f"[TRANSCRIBER] Input video: {video_path} ({os.path.getsize(video_path) / 1024 / 1024:.1f} MB)")

    model = _get_model()
    print("[TRANSCRIBER] Transcribing with openai-whisper...")

    result = model.transcribe(
        video_path,
        word_timestamps=True,
        initial_prompt="UGC video product review comfortable high quality grip stitching obsessed upgrade",
    )

    duration = 0.0
    words = []
    raw_sentences = []
    current_sentence_words = []
    sentence_enders = {".", "!", "?"}

    for segment in result["segments"]:
        if segment["end"] > duration:
            duration = segment["end"]
        for w in segment.get("words", []):
            word = {
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            }
            words.append(word)
            current_sentence_words.append(word)

            if any(w["word"].strip().endswith(p) for p in sentence_enders):
                if current_sentence_words:
                    raw_sentences.append(current_sentence_words)
                    current_sentence_words = []

    if current_sentence_words:
        raw_sentences.append(current_sentence_words)

    sentences = []
    for s_words in raw_sentences:
        if not s_words:
            continue
        sentences.append({
            "text": " ".join(w["word"] for w in s_words).strip(),
            "start": s_words[0]["start"],
            "end": s_words[-1]["end"],
            "words": s_words,
        })

    print(f"[TRANSCRIBER] Done: {len(sentences)} sentences, {len(words)} words, {duration:.1f}s duration")

    return {
        "full_text": " ".join(s["text"] for s in sentences),
        "sentences": sentences,
        "words": words,
        "duration": duration,
    }
