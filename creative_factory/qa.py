"""QA gate: a render must pass every check before delivery."""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from . import naming, sizing

MIN_DURATION_S = 30
MAX_DURATION_S = 59  # 60 s or more is never allowed
ALLOWED_RATIOS = {"9x16", "16x9", "4x5"}
SUBSTITUTE_RATIOS = {"1x1"}  # accepted in place of 4x5, but 4x5 is preferred


@dataclass
class MediaInfo:
    duration_s: float
    width: int
    height: int
    size_bytes: int
    has_audio: bool


@dataclass
class QAResult:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def probe(path: str) -> MediaInfo:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return MediaInfo(
        duration_s=float(data["format"]["duration"]),
        width=int(video["width"]),
        height=int(video["height"]),
        size_bytes=int(data["format"]["size"]),
        has_audio=any(s["codec_type"] == "audio" for s in data["streams"]),
    )


def check_duration(duration_s: float) -> Optional[str]:
    # the filename carries whole seconds, so judge the floor
    if int(duration_s) > MAX_DURATION_S:
        return f"duration {duration_s:.2f}s is over the {MAX_DURATION_S}s maximum"
    if duration_s < MIN_DURATION_S:
        return f"duration {duration_s:.2f}s is under the {MIN_DURATION_S}s minimum"
    return None


def check_size(size_bytes: int, limit_mb: float = sizing.DEFAULT_LIMIT_MB) -> Optional[str]:
    if size_bytes > limit_mb * sizing.MB:
        return f"size {size_bytes / sizing.MB:.2f} MB is over the {limit_mb:g} MB limit"
    return None


def check_ratio(label: str, allow_substitute: bool = False) -> Optional[str]:
    allowed = ALLOWED_RATIOS | (SUBSTITUTE_RATIOS if allow_substitute else set())
    if label not in allowed:
        return f"aspect ratio {label} is not one of {sorted(allowed)}"
    return None


def run_checks(
    filename: str,
    info: MediaInfo,
    limit_mb: float = sizing.DEFAULT_LIMIT_MB,
    allow_substitute_ratio: bool = False,
) -> QAResult:
    result = QAResult()
    parsed = naming.parse_filename(filename)
    if parsed is None:
        result.problems.append(f"filename {filename!r} does not match the naming pattern")
    for problem in (
        check_duration(info.duration_s),
        check_size(info.size_bytes, limit_mb),
        check_ratio(naming.ratio_label(info.width, info.height), allow_substitute_ratio),
    ):
        if problem:
            result.problems.append(problem)
    if not info.has_audio:
        result.problems.append("no audio stream (voiceover and music are required)")
    if parsed:
        actual = naming.ratio_label(info.width, info.height)
        if parsed.ratio != actual:
            result.problems.append(f"filename says {parsed.ratio} but the video is {actual}")
        if parsed.duration != int(info.duration_s):
            result.problems.append(
                f"filename says {parsed.duration}s but the video is {int(info.duration_s)}s"
            )
    return result
