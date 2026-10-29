# Creative Factory

AI video creatives from gameplay footage: hooks, ElevenLabs voiceover and music, packshot, resizes, delivered to Google Drive in the standard folder structure.

Project plan and decisions: https://appodeal.atlassian.net/wiki/spaces/AP1/pages/7448330294
Naming convention (source of truth): https://appodeal.atlassian.net/wiki/spaces/AP1/pages/6375964682

## Spec

| Rule | Value |
|---|---|
| Ratios | 9:16, 16:9, 4:5 |
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
- `creative_factory/drive.py`: Drive API v3 with the service account (list, folders, resumable upload, download, registry scan).
- `creative_factory/pipeline.py`, `elevenlabs.py`: the render job (hook, voiceover, music, end card, 9:16 and 4:5, QA, upload).
- `creative_factory/jobs.py`, `auth.py`, `web.py`, `static/index.html`: job queue, Google sign-in, API and UI.
- `creative_factory/registry.py`: JSON cache of used prefixes and ids with a file lock, weekly injected Drive scan, atomic `reserve(game)`.

## Web UI

`creative_factory/web.py` (FastAPI) serves a four-step wizard: game and concept, assets and footage, creative (trim, crop, hook, voiceover lines, voice, music prompt, sizes), review and render. Everything is stored in Google Drive:

- Game folders are the folders in the Creatives shared drive; assets go to `Game/year/Assets` (logo and end card background are prefixed `logo__` and `endcard_bg__`), footage to `Assets/Footage`.
- Renders go to `Game/year/Creatives/XY[id]_Concept_(DD.MM.YY)/`. The service holds no state between jobs except the registry cache and job history in `DATA_DIR`.
- Sign-in is Google OAuth restricted to `ALLOWED_DOMAIN` (default appodeal.com). One render runs at a time.

Deploy on Coolify from this repo with the Dockerfile; set the variables from `.env.example` (including `ELEVENLABS_API_KEY`: outside the Claude sandbox there is no key-injecting proxy) (OAuth redirect URI: `BASE_URL/auth/callback`) and mount a persistent volume at `/data`. Run one replica only.

Local run (no Google sign-in): `DEV_USER=you@appodeal.com DATA_DIR=./data uvicorn creative_factory.web:app --port 8000`.

## Develop

Python 3.11+, `ffmpeg`/`ffprobe`, the Inter font, and `pip install -r requirements.txt`. The core modules (naming, sizing, qa, registry) use only the standard library.

```bash
python3 -m unittest discover -s tests -t .
```

## Not built yet

AI footage analysis and script/hook suggestions, 16:9 output, languages beyond EN, per-user job filtering.

The ElevenLabs key is a host-scoped network secret for `api.elevenlabs.io` (header `xi-api-key`); code calls the API without a key and the proxy adds it.
