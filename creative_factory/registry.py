"""Prefix and id registry: a JSON cache of what Drive already holds.

The cache maps prefix -> game and prefix -> used creative ids. It is rebuilt
from a Drive scan about once a week; new prefixes and ids are recorded
immediately, under an exclusive file lock, so two tasks starting at once never
get the same id.

The scan is injected (a callable returning {game name: filenames}) so this
module has no Drive dependency.
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from typing import Callable, Iterable, Mapping, Optional

from . import naming

SCAN_MAX_AGE_S = 7 * 24 * 3600

Scan = Callable[[], Mapping[str, Iterable[str]]]


class Registry:
    def __init__(
        self,
        path: str,
        scan: Optional[Scan] = None,
        max_age_s: float = SCAN_MAX_AGE_S,
        clock: Callable[[], float] = time.time,
    ):
        self.path = path
        self.scan = scan
        self.max_age_s = max_age_s
        self.clock = clock

    @contextmanager
    def _locked(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {"scanned_at": None, "prefixes": {}, "ids": {}}

    def _save(self, state: dict) -> None:
        tmp = f"{self.path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _stale(self, state: dict) -> bool:
        at = state["scanned_at"]
        return at is None or self.clock() - at > self.max_age_s

    def _merge_scan(self, state: dict) -> None:
        games = self.scan()
        for prefix, game in naming.build_prefix_map(games).items():
            state["prefixes"].setdefault(prefix, game)
        for filenames in games.values():
            for filename in filenames:
                parsed = naming.parse_filename(filename)
                if parsed:
                    ids = state["ids"].setdefault(parsed.prefix, [])
                    if parsed.id not in ids:
                        ids.append(parsed.id)
        state["scanned_at"] = self.clock()

    def refresh(self, force: bool = False) -> None:
        """Rescan Drive if the cache is stale (or force). Keeps local reservations."""
        if self.scan is None:
            return
        with self._locked():
            state = self._load()
            if force or self._stale(state):
                self._merge_scan(state)
                self._save(state)

    def reserve(self, game: str, manual_prefix: Optional[str] = None) -> tuple[str, int]:
        """Atomically pick the prefix and the next id for a game and record both."""
        with self._locked():
            state = self._load()
            if self.scan is not None and self._stale(state):
                self._merge_scan(state)
            prefix = naming.assign_prefix(game, state["prefixes"], manual_prefix)
            ids = state["ids"].setdefault(prefix, [])
            creative_id = naming.next_id(ids)
            state["prefixes"].setdefault(prefix, naming.normalize_game(game))
            ids.append(creative_id)
            self._save(state)
            return prefix, creative_id
