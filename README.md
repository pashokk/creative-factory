# Creative Factory

AI video creatives from gameplay footage: hooks, ElevenLabs voiceover and music, packshot, resizes, delivered to Google Drive in the standard folder structure.

Project plan and decisions: https://appodeal.atlassian.net/wiki/spaces/AP1/pages/7448330294
Naming convention (source of truth): https://appodeal.atlassian.net/wiki/spaces/AP1/pages/6375964682

## Spec

| Rule | Value |
|---|---|
| Ratios | 9:16, 16:9, 4:5 (1:1 only as a substitute for 4:5) |
| Container | MP4 |
| Duration | 30-59 s, never 60 s or more |
| Size | up to 30 MB; working budget may be raised to 40 MB |
| Audio | AI voiceover and music (ElevenLabs), licensed for commercial ads |

File: `XY{id}_v{n}_{ratio}_{duration}s_{lang}.mp4`, e.g. `BW001_v1_9x16_59s_EN.mp4`.
Folder: `XY[001]_ConceptName_(DD.MM.YY)`.

- `XY` is the first letters of the first two words of the game name (Brain Wash = BW, My Little Spa = ML). Single-word, numeric, non-ASCII or "The ..." names are questionable: the user gives an optional two-letter abbreviation.
- A prefix already used by another game gets a digit (BW, BW1, BW2). Existing games keep their prefix (My Little Spa stays SP).
- The id is a per-game counter starting at 001, always three digits, reserved when the task starts.

## Layout

- `creative_factory/naming.py`: prefix derivation and collision handling, id counter, file and folder names, filename parsing.
- `creative_factory/sizing.py`: bitrate budget that keeps a render under the size limit.
- `creative_factory/qa.py`: QA gate (duration, size, ratio, audio present, name matches the video); `probe()` reads a file with `ffprobe`.

## Develop

Python 3.11+ and `ffmpeg`/`ffprobe`. No third-party dependencies yet.

```bash
python3 -m unittest discover -s tests -t .
```

## Not built yet

Atomic id reservation and the Drive prefix scan, footage analysis, script and hook planning, ElevenLabs voice and music, the cut and resize render, Drive upload, the web UI.

The ElevenLabs key is a host-scoped network secret for `api.elevenlabs.io` (header `xi-api-key`); code calls the API without a key and the proxy adds it.
