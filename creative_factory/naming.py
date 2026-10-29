"""File and folder naming for video creatives.

Spec: https://appodeal.atlassian.net/wiki/spaces/AP1/pages/7448330294
Convention: https://appodeal.atlassian.net/wiki/spaces/AP1/pages/6375964682

File:   XY{id}_v{n}_{ratio}_{duration}s_{lang}.mp4   e.g. BW001_v1_9x16_59s_EN.mp4
Folder: XY[{id}]_ConceptName_(DD.MM.YY)

XY is a two-letter game prefix, optionally followed by a collision digit
(BW, BW1, BW2). The id is always exactly three digits, so "BW1001" parses
unambiguously as prefix "BW1" + id "001".
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Optional

MAX_ID = 999

# Existing games whose prefix predates (or breaks) the derivation rule.
PREFIX_OVERRIDES = {"my little spa": "SP"}

_ARTICLES = {"the", "a", "an"}

FILE_RE = re.compile(
    r"^(?P<prefix>[A-Z]{2}\d*)(?P<id>\d{3})_v(?P<version>\d+)_"
    r"(?P<ratio>\d+x\d+)_(?P<duration>\d+)s_(?P<lang>[A-Z]{2})"
    r"(?:_(?P<suffix>[A-Za-z]+))?\.mp4$"
)


FOLDER_RE = re.compile(r"^(?P<prefix>[A-Z]{2}\d*)\[(?P<id>\d{3})\]_")


@dataclass(frozen=True)
class ParsedName:
    prefix: str
    id: int
    version: int
    ratio: str
    duration: int
    lang: str
    suffix: Optional[str] = None


def normalize_game(name: str) -> str:
    return " ".join(name.casefold().split())


def derive_prefix(name: str) -> Optional[str]:
    """Two-letter prefix from a game name, or None when the name is questionable.

    Initials of the first two words (Brain Wash -> BW, My Little Spa -> ML).
    Single words (Outrun is OR, which no rule over its letters yields), names
    with digits or non-ASCII letters, and a leading article are questionable:
    the caller should ask the user for a manual two-letter abbreviation, and
    may offer suggest_prefix() as the default.
    """
    words = re.split(r"[^0-9A-Za-z\u0080-￿]+", name.strip())
    words = [w for w in words if w]
    if not words:
        return None
    if any(not w.isascii() or any(c.isdigit() for c in w) for w in words):
        return None
    if len(words) > 1 and words[0].casefold() in _ARTICLES:
        return None
    if len(words) == 1:
        return None
    return (words[0][0] + words[1][0]).upper()


def suggest_prefix(name: str) -> Optional[str]:
    """Default to offer when asking for a manual abbreviation."""
    letters = re.sub(r"[^A-Za-z]", "", name)
    return letters[:2].upper() if len(letters) >= 2 else None


def validate_manual_prefix(prefix: str) -> str:
    prefix = prefix.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", prefix):
        raise ValueError("manual abbreviation must be exactly two letters A-Z")
    return prefix


def parse_filename(filename: str) -> Optional[ParsedName]:
    m = FILE_RE.match(filename)
    if not m:
        return None
    return ParsedName(
        prefix=m["prefix"],
        id=int(m["id"]),
        version=int(m["version"]),
        ratio=m["ratio"],
        duration=int(m["duration"]),
        lang=m["lang"],
        suffix=m["suffix"],
    )


def prefix_and_id(name: str) -> Optional[tuple[str, int]]:
    """(prefix, id) from a creative file name or a creative folder name, else None."""
    parsed = parse_filename(name)
    if parsed:
        return parsed.prefix, parsed.id
    m = FOLDER_RE.match(name)
    return (m["prefix"], int(m["id"])) if m else None


def build_prefix_map(games: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """prefix -> normalized game name, from {game name: filenames on Drive}."""
    prefixes: dict[str, str] = {}
    for game, filenames in games.items():
        for filename in filenames:
            found = prefix_and_id(filename)
            if found:
                prefixes.setdefault(found[0], normalize_game(game))
    return prefixes


def assign_prefix(
    game: str,
    prefix_map: Mapping[str, str],
    manual: Optional[str] = None,
) -> str:
    """Pick the prefix for a game.

    Reuses a prefix this game already owns, applies overrides, then the manual
    abbreviation or the derived one. A prefix owned by another game gets a
    collision digit (BW -> BW1 -> BW2).
    """
    key = normalize_game(game)
    owned = sorted(p for p, owner in prefix_map.items() if owner == key)
    if owned:
        return owned[0]
    if key in PREFIX_OVERRIDES:
        return PREFIX_OVERRIDES[key]
    base = validate_manual_prefix(manual) if manual else derive_prefix(game)
    if base is None:
        raise ValueError(
            f"cannot derive a prefix from {game!r}: ask for a manual two-letter abbreviation"
        )
    candidate, n = base, 0
    while candidate in prefix_map:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def next_id(used_ids: Iterable[int]) -> int:
    """Next creative id for a game; a new game starts at 1."""
    nxt = max(used_ids, default=0) + 1
    if nxt > MAX_ID:
        raise ValueError("creative ids are three digits; this game is out of ids")
    return nxt


def ratio_label(width: int, height: int) -> str:
    from math import gcd

    g = gcd(width, height)
    return f"{width // g}x{height // g}"


def file_name(
    prefix: str,
    creative_id: int,
    version: int,
    ratio: str,
    duration_s: int,
    lang: str = "EN",
) -> str:
    if not 1 <= creative_id <= MAX_ID:
        raise ValueError("creative id must be 1-999")
    return f"{prefix}{creative_id:03d}_v{version}_{ratio}_{duration_s}s_{lang}.mp4"


def folder_name(prefix: str, creative_id: int, concept: str, on: date) -> str:
    concept = re.sub(r"[^0-9A-Za-z]+", "_", concept).strip("_")
    return f"{prefix}[{creative_id:03d}]_{concept}_({on:%d.%m.%y})"
