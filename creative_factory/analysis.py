"""AI suggestions: look at the footage and propose the cut, crop, hook, voiceover and music.

Frames are sampled from the video and sent to a vision model with a forced tool call, so the
answer is structured. The result is only a suggestion: the UI fills the form and the user can
edit it. Providers (standard library HTTP, no SDK): OpenAI when OPENAI_API_KEY is set, otherwise
Anthropic when ANTHROPIC_API_KEY is set; ANALYSIS_PROVIDER=openai|anthropic forces one.
"""

import base64
import glob
import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Callable, Optional

from .pipeline import ENDCARD_S, MAX_TOTAL_S, MIN_TOTAL_S

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o"}
KEY_VARS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
MAX_FRAMES = 40
WORDS_PER_SECOND = 2.5
MIN_GAMEPLAY_S = MIN_TOTAL_S - ENDCARD_S
MAX_GAMEPLAY_S = MAX_TOTAL_S - ENDCARD_S

TOOL = {
    "name": "propose_edit",
    "description": "Propose how to cut the footage into a video ad and what to say in it.",
    "input_schema": {
        "type": "object",
        "required": ["trim_start", "trim_len", "crop_top_pct", "crop_bottom_pct", "hook", "lines",
                     "music_prompt", "rationale"],
        "properties": {
            "trim_start": {"type": "number", "description": "Second of the source footage where the ad starts."},
            "trim_len": {"type": "number", "description": "Gameplay length in seconds, before the end card."},
            "crop_top_pct": {"type": "number", "description": "Percent of the frame height to cut from the top (phone status bar, notifications)."},
            "crop_bottom_pct": {"type": "number", "description": "Percent to cut from the bottom (recorder watermark, navigation bar)."},
            "hook": {"type": "string", "description": "On-screen hook for the first 3.5 s: at most 6 words, one line break allowed."},
            "lines": {
                "type": "array",
                "items": {"type": "object", "required": ["at", "text"],
                          "properties": {"at": {"type": "number", "description": "Second in the FINAL video when the line starts."},
                                         "text": {"type": "string"}}},
            },
            "music_prompt": {"type": "string"},
            "rationale": {"type": "string", "description": "Two sentences: why this cut and these words."},
        },
    },
}


class AnalysisError(RuntimeError):
    pass


def sample_frames(video: str, out_dir: str, duration_s: float) -> list[tuple[float, str]]:
    """Frames spread over the whole footage, as [(second, jpeg path)]."""
    os.makedirs(out_dir, exist_ok=True)
    every = max(2.0, duration_s / MAX_FRAMES)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"fps=1/{every},scale=360:-2",
                    "-q:v", "6", os.path.join(out_dir, "f%03d.jpg")], check=True, capture_output=True)
    paths = sorted(glob.glob(os.path.join(out_dir, "f*.jpg")))
    return [(round(i * every, 1), p) for i, p in enumerate(paths)]


def provider() -> Optional[str]:
    """Which provider is configured, or None."""
    forced = os.environ.get("ANALYSIS_PROVIDER", "").lower()
    if forced in KEY_VARS:
        return forced if os.environ.get(KEY_VARS[forced]) else None
    return next((p for p in ("openai", "anthropic") if os.environ.get(KEY_VARS[p])), None)


def _model(prov: str) -> str:
    return os.environ.get("ANALYSIS_MODEL") or DEFAULT_MODELS[prov]


def _parts(frames: list[tuple[float, str]], game: str, brief: str, duration_s: float, lang: str) -> list[tuple[str, str]]:
    """The prompt as ("text", str) and ("image", base64 jpeg) parts, shared by all providers."""
    parts: list[tuple[str, str]] = [("text", (
        f"Game: {game}\nFootage length: {duration_s:.1f} s\nLanguage of voiceover and hook: {lang}\n"
        f"Brief from the user: {brief.strip() or '(none)'}\n\n"
        "Below are frames from a screen recording of gameplay, each labelled with its second in the source footage."))]
    for t, path in frames:
        with open(path, "rb") as f:
            parts += [("text", f"Source second {t}:"), ("image", base64.standard_b64encode(f.read()).decode())]
    parts.append(("text", (
        "Propose a mobile video ad built from this footage by calling propose_edit.\n"
        f"- Gameplay length {MIN_GAMEPLAY_S:g}-{MAX_GAMEPLAY_S:g} s (a {ENDCARD_S:g} s end card with the logo is added), "
        "inside the footage. Start where something engaging is already happening; skip menus, loading and idle time; "
        "end on a satisfying moment (a solved level, a reward).\n"
        "- Crop only what must be hidden: the phone status bar, notification shade, recorder watermark. Usually "
        "top 3-5 %, bottom 0-6 %. Do not cut into the game's own interface.\n"
        "- Hook: a curiosity or challenge question in at most 6 words that fits what the viewer sees first.\n"
        f"- Voiceover: 3-5 short lines, about {WORDS_PER_SECOND:g} words per second, never overlapping. Each line starts "
        "(`at`, seconds in the FINAL video, which starts at your trim_start) when what it says is on screen. The first "
        "line starts at 0.3. The last line is the call to action with the game name: it starts at trim_len + 0.5 "
        "(on the end card) and has at most 8 words.\n"
        "- Say only what the frames show. No invented features, ratings, prices or claims such as 'free'.\n"
        "- Music: one sentence describing an instrumental bed that fits the game, no vocals.")))
    return parts


def build_request(frames: list[tuple[float, str]], game: str, brief: str, duration_s: float,
                  lang: str = "EN", prov: str = "anthropic") -> dict:
    parts = _parts(frames, game, brief, duration_s, lang)
    if prov == "openai":
        content = [{"type": "text", "text": v} if k == "text" else
                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + v}} for k, v in parts]
        return {"model": _model(prov), "max_completion_tokens": 1500,
                "tools": [{"type": "function", "function": {
                    "name": TOOL["name"], "description": TOOL["description"], "parameters": TOOL["input_schema"]}}],
                "tool_choice": {"type": "function", "function": {"name": TOOL["name"]}},
                "messages": [{"role": "user", "content": content}]}
    content = [{"type": "text", "text": v} if k == "text" else
               {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": v}} for k, v in parts]
    return {"model": _model(prov), "max_tokens": 1500, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": content}]}


def _post(payload: dict, key: str, prov: str = "anthropic") -> dict:
    url = OPENAI_URL if prov == "openai" else ANTHROPIC_URL
    headers = {"content-type": "application/json"}
    headers.update({"authorization": "Bearer " + key} if prov == "openai"
                   else {"x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, json.dumps(payload).encode(), headers), timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            error = json.loads(e.read())["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
        except Exception:
            detail = e.reason
        raise AnalysisError(f"{'OpenAI' if prov == 'openai' else 'Claude'} API {e.code}: {detail}") from None


def _proposal(response: dict, prov: str) -> Optional[dict]:
    if prov == "openai":
        for call in (response.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []:
            if call.get("function", {}).get("name") == TOOL["name"]:
                try:
                    return json.loads(call["function"]["arguments"])
                except ValueError:
                    return None
        return None
    for block in response.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == TOOL["name"]:
            return block["input"]
    return None


def normalize(raw: dict, duration_s: float) -> dict:
    """Clamp the model's answer to what the pipeline accepts."""
    if duration_s < MIN_GAMEPLAY_S:
        raise AnalysisError(f"footage is {duration_s:.0f}s; at least {MIN_GAMEPLAY_S:g}s of gameplay is needed")
    length = min(max(float(raw["trim_len"]), MIN_GAMEPLAY_S), MAX_GAMEPLAY_S, duration_s)
    start = min(max(float(raw["trim_start"]), 0.0), duration_s - length)
    lines = sorted(({"start": round(min(max(float(l["at"]), 0.0), length + ENDCARD_S - 1.0), 1), "text": str(l["text"]).strip()}
                    for l in raw.get("lines", []) if str(l.get("text", "")).strip()), key=lambda l: l["start"])
    return {
        "trim_start": round(start, 1), "trim_len": round(length, 1),
        "crop_top_pct": round(min(max(float(raw["crop_top_pct"]), 0.0), 15.0), 1),
        "crop_bottom_pct": round(min(max(float(raw["crop_bottom_pct"]), 0.0), 15.0), 1),
        "hook": str(raw["hook"]).strip(), "lines": lines,
        "music_prompt": str(raw.get("music_prompt", "")).strip(), "rationale": str(raw.get("rationale", "")).strip(),
    }


def suggest(video: str, work: str, game: str, brief: str, duration_s: float, lang: str = "EN",
            post: Optional[Callable[[dict, str], dict]] = None, prov: Optional[str] = None) -> dict:
    prov = prov or provider()
    if prov is None and post is None:
        raise AnalysisError("AI suggestions are not configured (set OPENAI_API_KEY or ANTHROPIC_API_KEY)")
    prov = prov or "anthropic"
    key = os.environ.get(KEY_VARS[prov], "").strip()
    frames = sample_frames(video, os.path.join(work, "frames"), duration_s)
    payload = build_request(frames, game, brief, duration_s, lang, prov)
    response = post(payload, key) if post else _post(payload, key, prov)
    raw = _proposal(response, prov)
    if raw is None:
        raise AnalysisError("the model did not return a proposal; try again")
    return normalize(raw, duration_s)
