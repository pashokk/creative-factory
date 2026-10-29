# Creative Factory: project context for Claude

Owner: Pavel Savinskiy (pavel.savinskiy@appodeal.com). Goal: AI video creatives from gameplay footage (hooks, ElevenLabs voiceover and music, packshot, resizes) delivered to Google Drive. Same idea as Playable Factory in the Monetization Console, for video.

Read first:
- Project plan and decisions: https://appodeal.atlassian.net/wiki/spaces/AP1/pages/7448330294
- Naming convention (source of truth, confirmed current): https://appodeal.atlassian.net/wiki/spaces/AP1/pages/6375964682
- `README.md` for the spec and layout.

## Decisions already made
- Ratios 9:16, 16:9, 4:5 only (no 1:1). MP4, 30-59 s (never 60 s), up to 30 MB (budget may be raised to 40 MB; confirm networks accept it).
- Build a 9:16 master (16:9 if the game is landscape), then resize with borders. No outpainting.
- Voiceover (EN first) and music both from ElevenLabs; the plan grants commercial ad use (confirmed by Pavel).
- Prefix = initials of the first two words; single-word, numeric, non-ASCII or "The ..." names are questionable, so the wizard asks for an optional two-letter abbreviation and suggests the first two letters. Collisions get a digit (BW, BW1, BW2). My Little Spa keeps `SP`.
- Ids: per-game counter from 001, exactly three digits, max 999, reserved at task start.
- Drive prefix scan runs about once a week (cache with a timestamp); new prefixes and ids are recorded immediately under a lock.
- Python; the core modules stay standard-library only, the web app uses FastAPI, Pillow and cryptography (`requirements.txt`). `ffmpeg`/`ffprobe` for media.
- Hosting: Coolify (Dockerfile in the repo), Google sign-in for @appodeal.com, all storage in Google Drive.

## Credentials (never print, log or commit them)
- ElevenLabs: host-scoped network secret for `api.elevenlabs.io`, header `xi-api-key`, no prefix. Code calls the API without a key; the proxy adds it.
- Google Drive: environment variable `GOOGLE_SERVICE_ACCOUNT_B64` holds the service account key JSON, base64-encoded on one line (decode it in code; dotenv cannot hold the multi-line JSON). Service account in project appodeal-395422, Appodeal Accelerator. Environment variables are visible to anyone using the environment, so keep the key's reach small: it can only see Drive folders shared with the service account. The Google APIs are reachable from the container; `drive.google.com` is not, so use the Drive API v3 with the service account. The Drive MCP tool refuses files over 10 MB.

## Drive references
- Footage (4 mp4, 11-48 MB, Word Cipher): folder `1dq8TeCdiM2muTAiFUInF3a-VlxSm3ThY`.
- Game XAPK `com.revortal.wordcipher_0.0.5.xapk`: file `1M2_4jHngwKHJz0B461XGtpyZhRh6iCQq`.
- Store: https://play.google.com/store/apps/details?id=com.revortal.wordcipher
- Output example: shared drive root `0AFIgRksacladUk9PVA`, folder `My Little Spa/2026/Creatives/SP[033]_No_Break_(22.10.26)/`.

## Status
Done: `naming.py`, `sizing.py`, `qa.py`, `registry.py`, `drive.py`, `pipeline.py`, `jobs.py`, `auth.py`, `web.py` with tests (`python3 -m unittest discover -s tests -t .`). Web UI wizard works end to end against Drive and ElevenLabs (tested with `DEV_USER`; Word Cipher WC001 rendered and uploaded, voiceover plus music). Dockerfile and `.env.example` ready for Coolify.
Next, in order:
1. Deploy on Coolify: create the Google OAuth client (redirect `BASE_URL/auth/callback`), set the env vars from `.env.example`, mount `/data`, and test the real Google sign-in (not exercised yet).
2. Hi-res end card backgrounds from design (the current Word Cipher one is upscaled from a 544 px example).
3. AI help for hook and voiceover script; 16:9 output; more languages.
