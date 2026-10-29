"""Spike: one 9:16 and one 4:5 ad for Word Cipher from screen-recording footage.

Hook text, ElevenLabs voiceover, packshot, 9:16 master, 4:5 resize with blurred
borders, then the QA gate. Music is optional (--music FILE) because the current
ElevenLabs key lacks the music_generation permission.

    python3 scripts/spike_word_cipher.py --footage v2_2.mp4 --icon icon.png --work work
"""

import argparse
import json
import os
import subprocess
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from creative_factory import naming, qa, sizing
from creative_factory.registry import Registry

VOICE = "cgSgspJ2msm6clMCkdW9"  # Jessica: playful, bright, warm
FONT = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
GAME = "Word Cipher"
HOOK = "Can you crack\nthe hidden phrase?"
# (start second in the final video, line)
SCRIPT = [
    (0.3, "Think you're good at word puzzles? Crack the hidden phrase."),
    (8.0, "Solve each clue, fill in the letters, and a secret saying appears."),
    (22.0, "Stuck? Use a letter hint, or reveal a whole word."),
    (35.0, "Every level hides a famous quote. Can you find them all?"),
    (47.0, "Word Cipher. Download it now."),
]
CUT_START, CUT_LEN = 5.0, 46.0  # skip the home and level-select screens
PACK_LEN = 5.0
# Crop the phone status bar (private details) and the XRecorder watermark.
CROP = "crop=1088:1934:0:88"


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def tts(text: str, path: str) -> None:
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
        json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode(),
        {"content-type": "application/json", "xi-api-key": "proxy-injected"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())


def packshot_png(icon_path: str, path: str, w: int = 1080, h: int = 1920) -> None:
    img = Image.new("RGB", (w, h))
    top, bottom = (196, 224, 245), (150, 190, 226)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    icon = Image.open(icon_path).convert("RGBA").resize((460, 460), Image.LANCZOS)
    mask = Image.new("L", icon.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *icon.size], 100, fill=255)
    img.paste(icon, ((w - 460) // 2, 560), mask)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT, 120)
    d.text((w // 2, 1150), GAME, font=title, fill=(23, 52, 102), anchor="mm")
    btn = (w // 2 - 330, 1300, w // 2 + 330, 1450)
    d.rounded_rectangle(btn, 75, fill=(46, 160, 90))
    d.text((w // 2, 1375), "Download now", font=ImageFont.truetype(FONT, 66), fill="white", anchor="mm")
    img.save(path)


def build_voiceover(work: str, music: str | None, total_s: float, out: str) -> None:
    inputs, filters, labels = [], [], []
    for i, (start, text) in enumerate(SCRIPT):
        mp3 = os.path.join(work, f"vo{i}.mp3")
        tts(text, mp3)
        inputs += ["-i", mp3]
        ms = int(start * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},aformat=sample_rates=48000:channel_layouts=stereo[v{i}]")
        labels.append(f"[v{i}]")
    mix = "".join(labels) + f"amix=inputs={len(SCRIPT)}:normalize=0,apad=whole_dur={total_s}[vo]"
    filters.append(mix)
    if music:
        inputs += ["-i", music]
        k = len(SCRIPT)
        filters.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.25,apad=whole_dur={total_s}[m]")
        filters.append("[vo][m]amix=inputs=2:normalize=0[a]")
    else:
        filters.append("[vo]anull[a]")
    run("ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[a]",
        "-t", str(total_s), "-c:a", "aac", "-b:a", "128k", out)


def render_master(footage: str, pack_png: str, audio: str, out: str, total_s: float) -> None:
    hook_file = os.path.join(os.path.dirname(out), "hook.txt")
    with open(hook_file, "w") as f:
        f.write(HOOK)
    hook = (f"drawtext=fontfile={FONT}:textfile={hook_file}:fontsize=80:fontcolor=white:text_align=center:"
            f"x=(w-text_w)/2:y=230:box=1:boxcolor=0x173466@0.88:boxborderw=34:enable='lt(t,3.5)'")
    fc = (f"[0:v]{CROP},scale=1080:1920,fps=30,setsar=1,{hook}[g];"
          f"[1:v]fps=30,setsar=1,fade=t=in:d=0.4[p];[g][p]concat=n=2:v=1:a=0[v]")
    kbps = sizing.video_bitrate(total_s) // 1000
    run("ffmpeg", "-y", "-ss", str(CUT_START), "-t", str(CUT_LEN), "-i", footage,
        "-loop", "1", "-t", str(PACK_LEN), "-i", pack_png, "-i", audio,
        "-filter_complex", fc, "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "slow",
        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", "-t", str(total_s), out)


def render_4x5(master: str, out: str) -> None:
    fc = ("[0:v]split[a][b];[a]scale=1080:1350:force_original_aspect_ratio=increase,"
          "crop=1080:1350,gblur=sigma=40[bg];[b]scale=-2:1350[fg];[bg][fg]overlay=(W-w)/2:0[v]")
    info = qa.probe(master)
    kbps = sizing.video_bitrate(info.duration_s) // 1000
    run("ffmpeg", "-y", "-i", master, "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k",
        "-bufsize", f"{2 * kbps}k", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--footage", required=True)
    ap.add_argument("--icon", required=True)
    ap.add_argument("--work", default="work")
    ap.add_argument("--music")
    ap.add_argument("--lang", default="EN")
    args = ap.parse_args()
    os.makedirs(args.work, exist_ok=True)
    total = CUT_LEN + PACK_LEN
    prefix, cid = Registry(os.path.join(args.work, "registry.json")).reserve(GAME)
    pack = os.path.join(args.work, "packshot.png")
    packshot_png(args.icon, pack)
    audio = os.path.join(args.work, "audio.m4a")
    build_voiceover(args.work, args.music, total, audio)
    master = os.path.join(args.work, "master_9x16.mp4")
    render_master(args.footage, pack, audio, master, total)
    resized = os.path.join(args.work, "master_4x5.mp4")
    render_4x5(master, resized)
    for src in (master, resized):
        info = qa.probe(src)
        name = naming.file_name(prefix, cid, 1, naming.ratio_label(info.width, info.height),
                                int(info.duration_s), args.lang)
        final = os.path.join(args.work, name)
        os.replace(src, final)
        result = qa.run_checks(name, qa.probe(final))
        print(name, f"{os.path.getsize(final) / sizing.MB:.1f} MB", "QA OK" if result.ok else result.problems)


if __name__ == "__main__":
    main()
