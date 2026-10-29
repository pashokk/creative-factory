"""Render pipeline: Drive inputs -> hook, voiceover, music, end card -> 9:16 and 4:5 ads -> QA -> Drive.

Everything a job needs is a Drive file id, so the service holds no state between
jobs beyond the registry cache. Steps report progress through a callback.
"""

import math
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont

from . import elevenlabs, naming, qa, sizing
from .drive import Drive
from .registry import Registry

FONT = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
ENDCARD_S = 5.0
VIDEO_FOLDERS = ("Videos", "Video")
FPS = 30
RATIOS = {"9x16": (1080, 1920), "4x5": (1080, 1350), "16x9": (1920, 1080)}
MIN_TOTAL_S, MAX_TOTAL_S = 30, 58  # never 60 s; one second of slack under the 59 s limit
Progress = Callable[[str], None]


@dataclass
class JobSpec:
    game_folder_id: str
    game: str
    concept: str
    footage_id: str
    logo_id: str
    endcard_bg_id: Optional[str] = None
    manual_prefix: Optional[str] = None
    lang: str = "EN"
    trim_start: float = 0.0
    trim_len: float = 40.0
    crop_top_pct: float = 4.0
    crop_bottom_pct: float = 0.0
    hook: str = ""
    lines: list = field(default_factory=list)  # [{"start": seconds, "text": str}]
    voice_id: str = ""
    music_prompt: str = ""
    ratios: list = field(default_factory=lambda: ["9x16", "4x5"])
    limit_mb: float = sizing.DEFAULT_LIMIT_MB


def validate(spec: JobSpec) -> list[str]:
    problems = []
    for name in ("game_folder_id", "game", "concept", "footage_id", "logo_id", "voice_id"):
        if not getattr(spec, name):
            problems.append(f"{name} is required")
    total = spec.trim_len + ENDCARD_S
    if not MIN_TOTAL_S <= total <= MAX_TOTAL_S:
        problems.append(f"total length is {total:g}s (gameplay + {ENDCARD_S:g}s end card); "
                        f"it must be {MIN_TOTAL_S}-{MAX_TOTAL_S}s, so gameplay {MIN_TOTAL_S - ENDCARD_S:g}-{MAX_TOTAL_S - ENDCARD_S:g}s")
    if spec.trim_start < 0:
        problems.append("trim start cannot be negative")
    if not 0 <= spec.crop_top_pct + spec.crop_bottom_pct < 40:
        problems.append("crop percentages must be 0 or more and under 40 in total")
    if not spec.lines or any(not str(l.get("text", "")).strip() for l in spec.lines):
        problems.append("add at least one voiceover line and no empty lines")
    if not spec.ratios or any(r not in RATIOS for r in spec.ratios):
        problems.append(f"ratios must be among {sorted(RATIOS)}")
    if not re.fullmatch(r"[A-Z]{2}", spec.lang):
        problems.append("language must be two capital letters, e.g. EN")
    return problems


def _run(*cmd: str) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr.strip()[-600:]}")


def _fit(w: int, h: int) -> str:
    """Filter graph: input 0 fitted inside w x h over its own blurred, cropped copy."""
    return (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"gblur=sigma=40[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")


def endcard_frames(logo_path: str, title: str, out_dir: str, bg_path: Optional[str] = None,
                   w: int = 1080, h: int = 1920) -> None:
    """Logo, two-tone title and a pulsing down-arrow; no button."""
    os.makedirs(out_dir, exist_ok=True)
    if bg_path:
        bg = Image.open(bg_path).convert("RGB").resize((w, h), Image.LANCZOS)
    else:
        bg = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(bg)
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=(int(235 - 25 * t), int(238 - 20 * t), int(245 - 15 * t)))
    logo = Image.open(logo_path).convert("RGB")
    side = min(logo.size)  # the supplied logo has a margin around the rounded square
    m = int(side * 0.066)
    logo = logo.crop((m, m, side - m, side - m)).resize((560, 560), Image.LANCZOS)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *logo.size], 125, fill=255)
    bg.paste(logo, ((w - 560) // 2, 470), mask)
    d = ImageDraw.Draw(bg)
    first, _, rest = title.partition(" ")
    size = 122
    font = ImageFont.truetype(FONT, size)
    while d.textlength(title, font=font) > w - 160 and size > 40:
        size -= 4
        font = ImageFont.truetype(FONT, size)
    if rest:
        a, b = first + " ", rest
    else:
        a, b = title, ""
    wa, wb = d.textlength(a, font=font), d.textlength(b, font=font)
    x = (w - wa - wb) / 2
    d.text((x, 1130), a, font=font, fill=(18, 40, 84), anchor="lm")
    if b:
        d.text((x + wa, 1130), b, font=font, fill=(42, 118, 208), anchor="lm")
    for n in range(int(ENDCARD_S * FPS)):
        frame = bg.copy()
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for i in range(4):
            phase = (n / FPS) / 1.2 - i / 4 * 0.6  # a wave running down the stack
            alpha = 0.25 + 0.75 * max(0.0, math.cos((phase % 1.0) * 2 * math.pi - math.pi)) ** 2
            y = 1560 + i * 72
            col = (120 - i * 25, 170 - i * 25, 235, int(255 * alpha))
            ld.line([(480, y), (540, y + 46), (600, y)], fill=col, width=26, joint="curve")
        frame.paste(layer, (0, 0), layer)
        frame.save(os.path.join(out_dir, f"{n:03d}.png"))


def place_lines(lines: list, durations: list[float], gap: float = 0.3) -> list[float]:
    """Start time per line: as requested, but never before the previous line ends."""
    starts, end = [], 0.0
    for line, dur in zip(lines, durations):
        start = max(float(line["start"]), end + gap if starts else 0.0)
        starts.append(start)
        end = start + dur
    return starts


def _duration(path: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(p.stdout)


def build_audio(spec: JobSpec, work: str, total_s: float, out: str, say: Progress) -> list[str]:
    warnings: list[str] = []
    paths = []
    for i, line in enumerate(spec.lines):
        say(f"Voiceover line {i + 1} of {len(spec.lines)}")
        mp3 = os.path.join(work, f"vo{i}.mp3")
        elevenlabs.speech(line["text"].strip(), spec.voice_id, mp3)
        paths.append(mp3)
    starts = place_lines(spec.lines, [_duration(p) for p in paths])
    if starts and starts[-1] + _duration(paths[-1]) > total_s:
        warnings.append("The last voiceover line runs past the end of the video and is cut off.")
    music_path = None
    if spec.music_prompt.strip():
        say("Generating music")
        try:
            music_path = os.path.join(work, "music.mp3")
            elevenlabs.music(spec.music_prompt, total_s, music_path)
        except elevenlabs.ElevenLabsError as e:
            music_path = None
            warnings.append(f"Music skipped, the ad has voiceover only: {e}")
    else:
        warnings.append("No music prompt given, the ad has voiceover only.")
    inputs, filters, labels = [], [], []
    for i, (p, start) in enumerate(zip(paths, starts)):
        inputs += ["-i", p]
        ms = int(start * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},aformat=sample_rates=48000:channel_layouts=stereo[v{i}]")
        labels.append(f"[v{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(paths)}:normalize=0,apad=whole_dur={total_s}[vo]")
    if music_path:
        inputs += ["-i", music_path]
        k = len(paths)
        filters.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.25,"
                       f"afade=t=out:st={total_s - 2}:d=2,apad=whole_dur={total_s}[m]")
        filters.append("[vo][m]amix=inputs=2:normalize=0[a]")
    else:
        filters.append("[vo]anull[a]")
    _run("ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[a]",
         "-t", str(total_s), "-c:a", "aac", "-b:a", "128k", out)
    return warnings


def render_master(spec: JobSpec, footage: str, frames_dir: str, audio: str, out: str, total_s: float) -> None:
    hook_file = os.path.join(os.path.dirname(out), "hook.txt")
    with open(hook_file, "w") as f:
        f.write(spec.hook.strip().replace("\\n", "\n"))
    hook = ""
    if spec.hook.strip():
        hook = (f",drawtext=fontfile={FONT}:textfile={hook_file}:fontsize=80:fontcolor=white:text_align=center:"
                f"x=(w-text_w)/2:y=230:box=1:boxcolor=0x173466@0.88:boxborderw=34:enable='lt(t,3.5)'")
    top, bottom = spec.crop_top_pct / 100, spec.crop_bottom_pct / 100
    crop = f"crop=iw:ih*{1 - top - bottom:.4f}:0:ih*{top:.4f}"
    gameplay = (f"[0:v]{crop},fps={FPS}[c];[c]{_fit(1080, 1920).replace('[0:v]', '', 1)}{hook}[g]")
    fc = (f"{gameplay};[1:v]fps={FPS},setsar=1,fade=t=in:d=0.4[p];[g][p]concat=n=2:v=1:a=0[v]")
    kbps = sizing.video_bitrate(total_s, spec.limit_mb) // 1000
    _run("ffmpeg", "-y", "-ss", str(spec.trim_start), "-t", str(spec.trim_len), "-i", footage,
         "-framerate", str(FPS), "-i", os.path.join(frames_dir, "%03d.png"), "-i", audio,
         "-filter_complex", fc, "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "medium",
         "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", "-t", str(total_s), out)


def resize(master: str, ratio: str, out: str, limit_mb: float) -> None:
    w, h = RATIOS[ratio]
    kbps = sizing.video_bitrate(qa.probe(master).duration_s, limit_mb) // 1000
    _run("ffmpeg", "-y", "-i", master, "-filter_complex", _fit(w, h) + "[v]", "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k",
         "-bufsize", f"{2 * kbps}k", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out)


def run_job(spec: JobSpec, drive: Drive, registry: Registry, work: str, say: Progress,
            today: Optional[date] = None) -> dict:
    """Returns {"folder_id", "folder_url", "prefix", "creative_id", "files", "warnings"}."""
    problems = validate(spec)
    if problems:
        raise ValueError("; ".join(problems))
    today = today or date.today()
    os.makedirs(work, exist_ok=True)

    say("Reserving the creative id")
    prefix, creative_id = registry.reserve(spec.game, spec.manual_prefix)

    say("Downloading footage and assets from Drive")
    footage = drive.download(spec.footage_id, os.path.join(work, "footage.mp4"))
    logo = drive.download(spec.logo_id, os.path.join(work, "logo"))
    bg = drive.download(spec.endcard_bg_id, os.path.join(work, "endcard_bg")) if spec.endcard_bg_id else None
    source = qa.probe(footage)
    if spec.trim_start + spec.trim_len > source.duration_s + 0.1:
        raise ValueError(f"footage is {source.duration_s:.1f}s long; start {spec.trim_start:g}s + "
                         f"length {spec.trim_len:g}s runs past the end")

    total = spec.trim_len + ENDCARD_S
    say("Building the end card")
    frames = os.path.join(work, "endcard")
    endcard_frames(logo, re.sub(r"\s*\(.*\)$", "", spec.game), frames, bg)
    audio = os.path.join(work, "audio.m4a")
    warnings = build_audio(spec, work, total, audio, say)

    say("Rendering the 9:16 master")
    master = os.path.join(work, "master.mp4")
    render_master(spec, footage, frames, audio, master, total)

    say("Creating the Drive folder")
    folder_name = naming.folder_name(prefix, creative_id, spec.concept, today)
    creatives = drive.ensure_path(spec.game_folder_id, str(today.year), "Creatives")
    videos = drive.find_folder_ci(creatives, VIDEO_FOLDERS)  # games set up with Creatives/Videos keep videos there
    folder_id = drive.ensure_folder(videos or creatives, folder_name)

    files = []
    for ratio in spec.ratios:
        say(f"Rendering {ratio.replace('x', ':')}")
        path = master
        if ratio != "9x16":
            path = os.path.join(work, f"out_{ratio}.mp4")
            resize(master, ratio, path, spec.limit_mb)
        info = qa.probe(path)
        name = naming.file_name(prefix, creative_id, 1, ratio, int(info.duration_s), spec.lang)
        final = os.path.join(work, name)
        os.replace(path, final) if path != master else os.link(path, final)
        result = qa.run_checks(name, qa.probe(final), spec.limit_mb)
        say(f"Uploading {name}")
        up = drive.upload(final, folder_id)
        files.append({"name": name, "size": info.size_bytes, "url": up.get("webViewLink"),
                      "qa_ok": result.ok, "qa_problems": result.problems})
    return {"folder_id": folder_id, "folder_name": folder_name, "prefix": prefix, "creative_id": creative_id,
            "files": files, "warnings": warnings}
