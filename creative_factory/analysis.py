"""AI suggestions: look at the footage and propose the cut, crop, hook, voiceover and music.

Frames are sampled from the video and sent to Claude with a forced tool call, so the answer is
structured. The result is only a suggestion: the UI fills the form and the user can edit it.
Needs ANTHROPIC_API_KEY (standard library HTTP, no SDK).
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

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-5-5")
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


def build_request(frames: list[tuple[float, str]], game: str, brief: str, duration_s: float,
                  lang: str = "EN") -> dict:
    content: list = [{"type": "text", "text": (
        f"Game: {game}\nFootage length: {duration_s:.1f} s\nLanguage of voiceover and hook: {lang}\n"
        f"Brief from the user: {brief.strip() or '(none)'}\n\n"
        "Below are frames from a screen recording of gameplay, each labelled with its second in the source footage.")}]
    for t, path in frames:
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        content += [{"type": "text", "text": f"Source second {t}:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]
    content.append({"type": "text", "text": (
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
        "- Music: one sentence describing an instrumental bed that fits the game, no vocals.")})
    return {"model": MODEL, "max_tokens": 1500, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": content}]}


def _post(payload: dict, key: str) -> dict:
    req = urllib.request.Request(API_URL, json.dumps(payload).encode(), {
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())["error"]["message"]
        except Exception:
            detail = e.reason
        raise AnalysisError(f"Claude API {e.code}: {detail}") from None


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
            post: Optional[Callable[[dict, str], dict]] = None) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and post is None:
        raise AnalysisError("AI suggestions are not configured (ANTHROPIC_API_KEY is not set)")
    frames = sample_frames(video, os.path.join(work, "frames"), duration_s)
    response = (post or _post)(build_request(frames, game, brief, duration_s, lang), key or "")
    for block in response.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == TOOL["name"]:
            return normalize(block["input"], duration_s)
    raise AnalysisError("the model did not return a proposal; try again")
