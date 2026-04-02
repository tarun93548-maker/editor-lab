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
3. The "why" (core message) must survive in EVERY variation.
4. Check if content is sequential/dependent first — if each sentence builds on the previous, only trim the opener or cold-open on one line then resume from the top. Do NOT reorder dependent content.
5. Generate the number of variations specified in the user message. AS_IS counts as one.

## HOOK SELECTION RULES (STRICT — violating these makes the hook INVALID):
1. Every hook MUST be a COMPLETE thought. Never cut a sentence mid-word or mid-thought. If someone heard ONLY the hook with zero context, it must make complete sense on its own.
2. NEVER start a hook with conjunctions: "and", "but", "so", "or", "because", "which". These are continuations, not openers. If a sentence starts with one of these words, it CANNOT be a hook.
3. NEVER end a hook with trailing conjunctions or incomplete phrases: "but honestly,", "and i", "so if". The hook must feel finished.
4. A hook can be 1-3 sentences, but every sentence must be complete and self-contained.
5. Use the exact original_index to reference sentences — the text and timestamps will be looked up from the transcript automatically.
6. DO NOT include start_ms or end_ms — they are ignored. Only original_index matters.

## WHAT MAKES A BAD HOOK (NEVER do these — automatic rejection):
- Sentence fragments: "you do pilates or any kind of studio workouts i" — CUT OFF
- Starting mid-conversation: "and cutesy not like your typical workout socks so if" — NO CONTEXT
- Trailing hooks: "I feel way more stable during my workouts but honestly," — UNFINISHED
- Generic statements with no curiosity gap: "This is a really good product" — BORING
- Multiple unrelated sentences stitched together that don't flow naturally
- Any sentence that REQUIRES the previous sentence to make sense
- Sentences beginning with lowercase conjunctions (and, but, so, or, because)

## HOOK PSYCHOLOGY (based on UGC ad science — apply these when selecting hooks):
1. PATTERN INTERRUPT — violate the viewer's expectations in the first second. Counterintuitive statements, unexpected outcomes, bold claims.
2. CURIOSITY GAP — create an information gap. Make them NEED to keep watching to close it.
3. LOSS AVERSION — suggest not watching means missing something important. 2x more powerful than gain framing.
4. IDENTITY TARGETING — speak directly to a specific audience. "If you do Pilates..." or "For anyone who..." creates ingroup feeling and immediate relevance.
5. RESULT-FIRST — lead with the outcome/transformation. "I am obsessed." "This changed everything." "Best purchase I've made." Short, emotional, definitive.
6. CONTRAST PRINCIPLE — "Most people do X, but this..." positions the content as a superior alternative.
7. SOCIAL PROOF THROUGH IMPLICATION — "What I discovered..." "The thing nobody talks about..." implies insider knowledge.
8. SPECIFICITY — concrete details (materials, numbers, sensations) signal real knowledge and credibility.

## SEQUENTIAL/DEPENDENT CHECK:
Ask: would removing or reordering early sentences make later ones confusing or unearned?
- YES → sequential. Variations limited to: AS_IS, TRIM_OPENER, or cold-open on one line then play from beginning.
- NO → sentences can be reordered freely as long as message stays coherent.

## VARIATION TYPES (use the exact type names):
- AS_IS: Original order. Always include this. Must be ranked LAST.
- TRIM_OPENER: Remove 1-2 intro/filler sentences, start deeper into the content.
- COLD_OPEN_PAYOFF: Lead with the emotional result/transformation. Best for "I am obsessed", "This changed my life", "Best thing I've ever bought".
- COLD_OPEN_IDENTITY: Target the audience directly. "If you do Pilates...", "For anyone who struggles with...". Creates immediate relevance.
- COLD_OPEN_RESULT: Lead with a specific measurable outcome or benefit.
- COLD_OPEN_CURIOSITY: Create a mystery or information gap. "The one thing nobody tells you about..."
- COLD_OPEN_CONTRAST: Set up what's common then introduce the unexpected. "Everyone says X but actually..."
- COLD_OPEN_PROBLEM: Lead with the pain/problem sentence.
- COLD_OPEN_SOCIAL_PROOF: Lead with a compliment or third-party validation line.
- COLD_OPEN_FEELING: Lead with an emotional/sensory line.

## ANALYSIS STEP — do this FIRST before generating variations:
1. Determine if the content is sequential/dependent (is_sequential: true/false)
2. Identify the "why" statement — the core message that must survive
3. Assign a role to each sentence: hook, intro, problem, product, benefit, social_proof, cta, payoff
4. For each sentence, note whether it could work as a standalone hook (yes/no and why)

## OUTPUT FORMAT — return ONLY valid JSON, no markdown, no preamble:

{
  "analysis": {
    "is_sequential": true,
    "why_statement": "The core message/argument of the video in one sentence",
    "sentence_roles": [
      {"index": 0, "role": "hook", "text": "exact sentence text", "standalone_hook": true, "reason": "Complete thought, strong emotion"}
    ]
  },
  "variations": [
    {
      "id": 1,
      "name": "Descriptive Name",
      "hook_type": "COLD_OPEN_PAYOFF",
      "strategy": "One sentence explaining the strategic logic.",
      "why_it_works": ["Pattern interrupt: violates expectation by...", "Curiosity gap: viewer needs to know..."],
      "sentence_order": [4, 0, 1, 2, 3, 5, 6],
      "sentences": [
        {
          "original_index": 4,
          "text": "exact sentence text copied verbatim",
          "section": "hook"
        },
        {
          "original_index": 0,
          "text": "exact sentence text",
          "section": "intro"
        }
      ]
    }
  ]
}

## SECTION LABELS — assign one per sentence:
- hook: the opening line(s) designed to stop the scroll
- intro: introduces the creator or sets context
- problem: describes the pain point or issue
- product: names or describes the product
- benefit: explains a feature or advantage
- social_proof: compliments, reviews, or third-party validation
- cta: call to action ("go get these", "link in bio")
- payoff: the final result, transformation, or emotional conclusion

## QUALITY OVER QUANTITY:
- Only generate hooks that are genuinely GOOD. If you can only find 2 great hooks in a 50s video, generate 2 + AS_IS. Don't fill the quota with bad hooks.
- Rank variations by impact — strongest hook first, AS_IS always last.
- Every non-AS_IS variation must clearly outperform the original opening.
- Apply at least one hook psychology principle to each variation and explain it in why_it_works."""


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

Generate up to {max_vars} hook variations (including AS_IS as one of them).

CRITICAL REMINDERS:
- Every hook must be a COMPLETE thought — no fragments, no trailing conjunctions, no mid-sentence cuts.
- Never start a hook with: and, but, so, or, because, which.
- Only use original_index to reference sentences. Do NOT include start_ms or end_ms.
- Quality over quantity: if only 2 hooks are genuinely good, generate 2 + AS_IS. Don't force bad hooks.
- Apply hook psychology (pattern interrupt, curiosity gap, identity targeting, result-first) to each variation.
- Rank by impact — strongest hook first, AS_IS always last.
- Only use sentences from the transcript above."""

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
