"""ElevenLabs calls. The network proxy adds the real xi-api-key; code never holds it."""

import json
import urllib.error
import urllib.request

HOST = "https://api.elevenlabs.io"
PLACEHOLDER_KEY = "proxy-injected"


class ElevenLabsError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _call(path: str, payload=None, timeout: int = 180) -> bytes:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, body, {"content-type": "application/json",
                                                     "xi-api-key": PLACEHOLDER_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())["detail"]["message"]
        except Exception:
            detail = e.reason
        raise ElevenLabsError(f"ElevenLabs {e.code}: {detail}", e.code) from None


def voices() -> list[dict]:
    data = json.loads(_call("/v1/voices"))["voices"]
    return [{"id": v["voice_id"], "name": v["name"], "labels": v.get("labels") or {},
             "preview_url": v.get("preview_url")} for v in data]


def speech(text: str, voice_id: str, path: str) -> None:
    audio = _call(f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                  {"text": text, "model_id": "eleven_multilingual_v2"})
    with open(path, "wb") as f:
        f.write(audio)


def music(prompt: str, length_s: float, path: str) -> None:
    """Needs the music_generation permission on the key; raises ElevenLabsError(401) without it."""
    ms = int(min(max(length_s, 3), 300) * 1000)
    audio = _call("/v1/music?output_format=mp3_44100_128",
                  {"prompt": prompt, "music_length_ms": ms}, timeout=300)
    with open(path, "wb") as f:
        f.write(audio)
