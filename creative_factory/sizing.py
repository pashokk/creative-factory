"""Bitrate budget so a render stays under the size limit.

The spec limit is 30 MB; the working budget may be raised to 40 MB (confirm the
networks accept it). MB means 1,000,000 bytes, the stricter reading.
"""

MB = 1_000_000
DEFAULT_LIMIT_MB = 30
SAFETY_MARGIN = 0.02  # aim about 2% under the limit
CONTAINER_OVERHEAD = 0.01  # mp4 muxing overhead on top of the streams


def target_bytes(limit_mb: float = DEFAULT_LIMIT_MB, margin: float = SAFETY_MARGIN) -> int:
    return int(limit_mb * MB * (1 - margin))


def total_bitrate(duration_s: float, limit_mb: float = DEFAULT_LIMIT_MB) -> int:
    """Highest combined audio+video bitrate (bits/s) that fits the limit."""
    if duration_s <= 0:
        raise ValueError("duration must be positive")
    usable = target_bytes(limit_mb) * (1 - CONTAINER_OVERHEAD)
    return int(usable * 8 / duration_s)


def video_bitrate(
    duration_s: float,
    limit_mb: float = DEFAULT_LIMIT_MB,
    audio_bps: int = 128_000,
) -> int:
    """Video bitrate (bits/s) left after reserving audio."""
    video = total_bitrate(duration_s, limit_mb) - audio_bps
    if video <= 0:
        raise ValueError("audio alone exceeds the size budget")
    return video
