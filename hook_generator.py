import os
import re
import json
import anthropic
from typing import List, Dict, Any

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an expert UGC video editor specializing in TikTok-style ad content.

Your job is to analyze a video transcript and generate hook variation scripts by reordering existing sentences.

## ABSOLUTE RULES — never break these:
1. NEVER write new words — only use exact sentences from the transcript, verbatim.
2. NEVER cut mid-sentence — cuts happen only at sentence boundaries.
3. The "why" (core message) must survive in EVERY variation. If the viewer doesn't get the full message, the variation is invalid.
4. Check if content is sequential/dependent first — if each sentence builds on the previous to form the argument, only trim the opener or cold-open on one line then resume from the top. Do NOT reorder dependent content.
5. Generate the number of variations specified in the user message. Always aim for the maximum count given — include AS_IS plus as many strong hook variations as specified.

## SEQUENTIAL/DEPENDENT CHECK:
Ask: would removing or reordering early sentences make later ones confusing or unearned?
- YES → sequential. Variations limited to: AS_IS, TRIM_OPENER, or cold-open on one line then play from beginning.
- NO → sentences can be reordered freely as long as message stays coherent.

## VARIATION TYPES (use the exact type names):
- AS_IS: Original order. Always include this. Must be ranked LAST (it's the fallback).
- TRIM_OPENER: Remove 1-2 intro/filler sentences, start deeper.
- COLD_OPEN_PAYOFF: Lead with the result/transformation line, then cut to beginning and play through.
- COLD_OPEN_PROBLEM: Lead with the pain/problem sentence, then play through.
- COLD_OPEN_SOCIAL_PROOF: Lead with a compliment or third-party validation line, then play through.
- COLD_OPEN_IDENTITY: Lead with a "this is so me" or ingroup targeting line, then play through.
- COLD_OPEN_DIFFERENTIATOR: Lead with what makes the product unique, then play through.
- COLD_OPEN_FEELING: Lead with an emotional/sensory line, then play through.
- COLD_OPEN_RESULT: Lead with a specific outcome or stat, then play through.

## HOOK PSYCHOLOGY — reference these in why_it_works:
- Pattern interrupt: violates what the brain expects in first 1.5s — increases watch time
- Curiosity gap: creates information asymmetry — viewer must keep watching to close it
- Loss aversion: "not watching = missing out" is 2x more powerful than gain framing
- Mystery loop: opens an unresolved question that pulls the viewer forward
- Tension loop: introduces conflict or stakes that demand resolution
- Transformation loop: shows before/after or change that viewers want to witness
- Identity targeting: ingroup signals ("Pilates girls, you'll get it") increase retention from the right viewer
- Specificity: concrete details (materials, numbers, sensations) signal real knowledge and credibility

## ANALYSIS STEP — do this FIRST before generating variations:
1. Determine if the content is sequential/dependent (is_sequential: true/false)
2. Identify the "why" statement — the core message that must survive
3. Assign a role to each sentence: hook, intro, problem, product, benefit, social_proof, cta, payoff

## OUTPUT FORMAT — return ONLY valid JSON, no markdown, no preamble:

{
  "analysis": {
    "is_sequential": true,
    "why_statement": "The core message/argument of the video in one sentence",
    "sentence_roles": [
      {"index": 0, "role": "hook", "text": "exact sentence text"}
    ]
  },
  "variations": [
    {
      "id": 1,
      "name": "Descriptive Name",
      "hook_type": "AS_IS",
      "strategy": "One sentence explaining the strategic logic.",
      "why_it_works": ["Pattern interrupt: violates expectation by...", "Curiosity gap: viewer needs to know..."],
      "sentence_order": [0, 1, 2, 3],
      "sentences": [
        {
          "original_index": 0,
          "text": "exact sentence text copied verbatim",
          "start_ms": 0,
          "end_ms": 2400,
          "section": "hook"
        }
      ]
    }
  ]
}

## SECTION LABELS — assign one per sentence:
- hook: the opening line designed to stop the scroll
- intro: introduces the creator or sets context
- problem: describes the pain point or issue
- product: names or describes the product
- benefit: explains a feature or advantage
- social_proof: compliments, reviews, or third-party validation
- cta: call to action ("go get these", "link in bio")
- payoff: the final result, transformation, or emotional conclusion

## RANKING — this order matters:
Rank variations by impact — strongest hook first, AS_IS always last.
Only include variations you're confident will outperform the original.
Generate the number of variations specified in the user message."""


def _strip_markdown(raw: str) -> str:
    """Remove markdown code fences from response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip().rstrip("```").strip()


def _repair_json(raw: str):
    """Try to fix common JSON issues and parse."""
    # Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try closing unterminated structures
    for suffix in ['"}]}', '"]}', ']}', '}]', ']', '}']:
        try:
            return json.loads(fixed + suffix)
        except json.JSONDecodeError:
            continue

    return None


def _call_and_parse(user_msg: str, retries: int = 1):
    """Call Claude API, parse JSON response with retry on failure."""
    for attempt in range(1 + retries):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )

        raw = _strip_markdown(response.content[0].text)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[HOOK_GEN] JSON parse failed (attempt {attempt + 1}): {e}")
            repaired = _repair_json(raw)
            if repaired is not None:
                print("[HOOK_GEN] JSON repaired successfully")
                return repaired
            if attempt < retries:
                print("[HOOK_GEN] Retrying API call...")
                continue
            raise RuntimeError(f"Failed to parse hook variations JSON after {1 + retries} attempts: {e}")


def _max_variations(duration_sec: float) -> int:
    """Return max variation count based on video duration."""
    if duration_sec <= 30:
        return 3
    elif duration_sec <= 40:
        return 4
    else:
        return 5


def generate_hook_variations(transcript: Dict[str, Any], duration_sec: float = None) -> List[Dict[str, Any]]:
    sentences = transcript["sentences"]
    numbered = "\n".join(
        f"[{i}] ({s['start']}s–{s['end']}s) {s['text']}"
        for i, s in enumerate(sentences)
    )

    if duration_sec is None:
        duration_sec = sentences[-1]["end"] if sentences else 60
    max_vars = _max_variations(duration_sec)
    print(f"[HOOK_GEN] Duration: {duration_sec:.1f}s -> max_variations: {max_vars}")

    user_msg = f"""Transcript sentences with timestamps:

{numbered}

Full text:
{transcript['text']}

Video duration: {duration_sec:.1f}s

Analyze the content structure first, then generate EXACTLY {max_vars} hook variations (including AS_IS as one of them).
You MUST generate {max_vars} variations total. Use different hook types for each — AS_IS counts as one.
Rank by impact — strongest hook first, AS_IS always last. Only use sentences from the transcript above."""

    result = _call_and_parse(user_msg)

    # Handle both old array format and new {analysis, variations} format
    if isinstance(result, list):
        variations = result
    else:
        variations = result.get("variations", [])

    # Normalize: ensure each variation has a consistent "script" field for the renderer
    for v in variations:
        # New format uses "sentences" instead of "script"
        if "sentences" in v and "script" not in v:
            script = []
            for seg in v["sentences"]:
                idx = seg.get("original_index")
                start_ms = seg.get("start_ms")
                end_ms = seg.get("end_ms")
                # Use actual transcript timestamps when we have a valid index —
                # LLM sometimes returns wrong start_ms/end_ms for a sentence.
                if idx is not None and 0 <= idx < len(sentences):
                    actual = sentences[idx]
                    s = {
                        "sentence_index": idx,
                        "text": actual["text"],
                        "start": float(actual["start"]),
                        "end": float(actual["end"]),
                        "section": seg.get("section", ""),
                        "words": actual.get("words", []),
                        "audible_segment_index": actual.get("audible_segment_index"),
                    }
                    # Log if LLM timestamps disagree with transcript
                    if start_ms is not None:
                        llm_start = start_ms / 1000
                        if abs(llm_start - s["start"]) > 0.1:
                            print(f"  [HOOK_GEN] Timestamp mismatch for sentence[{idx}]: "
                                  f"LLM={llm_start:.3f}s, actual={s['start']:.3f}s")
                else:
                    s = {
                        "sentence_index": idx,
                        "text": seg.get("text", ""),
                        "start": start_ms / 1000 if start_ms is not None else seg.get("start", 0),
                        "end": end_ms / 1000 if end_ms is not None else seg.get("end", 0),
                        "section": seg.get("section", ""),
                    }
                script.append(s)
            v["script"] = script
        else:
            # Old format — enrich with word-level data
            for seg in v.get("script", []):
                idx = seg.get("sentence_index")
                if idx is not None and 0 <= idx < len(sentences):
                    seg["words"] = sentences[idx].get("words", [])
                    seg["audible_segment_index"] = sentences[idx].get("audible_segment_index")

    return variations
