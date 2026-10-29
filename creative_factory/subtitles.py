"""Burned-in subtitles in the short-video styles (TikTok / Instagram Reels).

Word times come from ElevenLabs alignment, so captions follow the voiceover. Output is an ASS
file rendered by ffmpeg's libass. Styles:

- pop:   uppercase, 1-3 words at a time, the spoken word is highlighted and slightly larger
- clean: sentence-style captions, white text on a dark box, a few words at a time
"""

import re
from typing import Iterable

STYLES = ("off", "pop", "clean")
HIGHLIGHT = "&H004DE1FF"  # yellow, ASS is BGR
WHITE = "&H00FFFFFF"
SAFE_BOTTOM = 430  # px above the bottom edge of a 1080x1920 frame, clear of the app UI

Word = tuple[str, float, float]  # text, start s, end s


def words_from_alignment(chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    """Group the per-character timings of a TTS response into words."""
    words: list[Word] = []
    cur, t0, t1 = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, t0, t1))
                cur = ""
            continue
        if not cur:
            t0 = s
        cur, t1 = cur + ch, e
    if cur:
        words.append((cur, t0, t1))
    return words


def estimate_words(text: str, duration_s: float) -> list[Word]:
    """Fallback when no alignment is available: spread the words over the audio by length."""
    tokens = text.split()
    total = sum(len(t) + 1 for t in tokens) or 1
    out, t = [], 0.0
    for tok in tokens:
        span = duration_s * (len(tok) + 1) / total
        out.append((tok, t, t + span * 0.92))
        t += span
    return out


def chunk(words: list[Word], max_words: int, max_chars: int = 24) -> list[list[Word]]:
    """Caption groups: break on sentence ends, long pauses and the size limits."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        chars = sum(len(x[0]) + 1 for x in cur) + len(w[0])
        if cur and (len(cur) >= max_words or chars > max_chars or w[1] - cur[-1][2] > 0.7):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?]$", w[0]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _clock(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def ass_document(words: Iterable[Word], style: str, width: int = 1080, height: int = 1920) -> str:
    if style not in ("pop", "clean"):
        raise ValueError(f"unknown subtitle style {style!r}")
    words = sorted(words, key=lambda w: w[1])
    pop = style == "pop"
    size = 80 if pop else 62
    box = "" if pop else "&H70000000"
    border = "1,7,3" if pop else "3,16,0"  # BorderStyle, Outline, Shadow
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,Inter,{size},{WHITE},{WHITE},&H00000000,{box or '&H64000000'},-1,0,0,0,100,100,0,0,{border},2,70,70,{SAFE_BOTTOM},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for group in chunk(words, 3 if pop else 5, 22 if pop else 30):
        texts = [_clean(w[0].upper() if pop else w[0]) for w in group]
        if not pop:
            lines.append((group[0][1], group[-1][2] + 0.2, " ".join(texts)))
            continue
        for i, w in enumerate(group):
            end = group[i + 1][1] if i + 1 < len(group) else w[2] + 0.15
            shown = " ".join(
                f"{{\\c{HIGHLIGHT}\\fscx112\\fscy112}}{t}{{\\c{WHITE}\\fscx100\\fscy100}}" if j == i else t
                for j, t in enumerate(texts))
            lines.append((w[1], end, shown))
    # overlapping events would stack on screen, so each one ends where the next begins
    lines = [(s, min(e, lines[i + 1][0]) if i + 1 < len(lines) else e, t) for i, (s, e, t) in enumerate(lines)]
    body = "".join(f"Dialogue: 0,{_clock(s)},{_clock(e)},Cap,,0,0,0,,{t}\n" for s, e, t in lines if e > s)
    return head + body
