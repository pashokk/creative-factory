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
- Python with the standard library for now; `ffmpeg`/`ffprobe` for media.

## Credentials (never print, log or commit them)
- ElevenLabs: host-scoped network secret for `api.elevenlabs.io`, header `xi-api-key`, no prefix. Code calls the API without a key; the proxy adds it.
- Google Drive: environment variable `GOOGLE_SERVICE_ACCOUNT_B64` holds the service account key JSON, base64-encoded on one line (decode it in code; dotenv cannot hold the multi-line JSON). Service account in project appodeal-395422, Appodeal Accelerator. Environment variables are visible to anyone using the environment, so keep the key's reach small: it can only see Drive folders shared with the service account. The Google APIs are reachable from the container; `drive.google.com` is not, so use the Drive API v3 with the service account. The Drive MCP tool refuses files over 10 MB.

## Drive references
- Footage (4 mp4, 11-48 MB, Word Cipher): folder `1dq8TeCdiM2muTAiFUInF3a-VlxSm3ThY`.
- Game XAPK `com.revortal.wordcipher_0.0.5.xapk`: file `1M2_4jHngwKHJz0B461XGtpyZhRh6iCQq`.
- Store: https://play.google.com/store/apps/details?id=com.revortal.wordcipher
- Output example: shared drive root `0AFIgRksacladUk9PVA`, folder `My Little Spa/2026/Creatives/SP[033]_No_Break_(22.10.26)/`.

## Status
Done: `naming.py`, `sizing.py`, `qa.py` with tests (`python3 -m unittest discover -s tests -t .`).
Next, in order:
1. Verify the service account can read the footage folder and write to the Creatives drive (test upload, then delete it).
2. Download the four videos, probe them (`qa.probe`), and describe them (length, resolution, fps, audio, what happens).
3. Registry: JSON cache with file lock, weekly Drive scan, atomic prefix and id reservation.
4. Spike: one 9:16 and one 4:5 ad for Word Cipher with a hook, ElevenLabs voiceover and music, and a packshot; run the QA gate.
