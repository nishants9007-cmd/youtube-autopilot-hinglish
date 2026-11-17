import asyncio
import json
import os
import random
import re
import subprocess
import sys
import textwrap
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont
import edge_tts

ROOT = Path(__file__).parent
OUT = ROOT / "output"
WORK = ROOT / "work"
OUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)

IST = ZoneInfo("Asia/Kolkata")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
VOICE = os.getenv("TTS_VOICE", "hi-IN-MadhurNeural")
PUBLISH = os.getenv("PUBLISH_ENABLED", "false").lower() == "true"

# A single weekly request creates 7 short scripts plus one 5-8 minute story.
PROMPT = r"""
You are the lead writer for a Hinglish YouTube channel about mysteries,
unbelievable facts, space, science and strange-but-true phenomena.

Return ONLY valid JSON with this exact shape:
{
  "shorts": [
    {
      "title": "string, max 65 chars",
      "description": "string",
      "tags": ["string"],
      "scenes": [
        {"narration": "spoken text", "onscreen": "short visual caption"},
        {"narration": "spoken text", "onscreen": "short visual caption"},
        {"narration": "spoken text", "onscreen": "short visual caption"}
      ]
    }
  ],
  "long_video": {
    "title": "string",
    "description": "string",
    "tags": ["string"],
    "scenes": [
      {"narration": "spoken text", "onscreen": "short visual caption"}
    ]
  }
}

Requirements:
- Exactly 7 shorts. Each short has exactly 3 scenes and about 85-105 spoken words total.
- Long video has 10-12 scenes and about 750-950 spoken words total (roughly 5-7 minutes).
- Language: natural Hinglish. Write Hindi in Devanagari and keep common technical terms/names
  in English. Example: "सोचिए, अगर एक दिन..." This helps a Hindi neural voice pronounce it.
- Style: cinematic AI storytelling, suspenseful but not misleading.
- Pick 8 different evergreen topics; don't invent current events.
- Science facts must be established and carefully worded. Clearly label theories, legends,
  disputed claims and speculation. Never present a fictional story as real.
- No fake quotes, fake statistics, fabricated experiments, or unsupported certainty.
- Each scene's narration should be self-contained enough to be spoken naturally.
- Onscreen captions should be short (2-7 words), in Devanagari or English.
- Titles must be compelling but not deceptive. No "100% real" claims.
- Add a short call to action only in the final scene of each video.
- Descriptions should include a concise note that the video uses AI-assisted storytelling
  and that speculative explanations are identified as theories.
- Do not include Markdown fences or text outside the JSON.
"""

def log(msg):
    print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] {msg}", flush=True)

def call_gemini():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY GitHub secret.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    response = requests.post(
        url,
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": PROMPT}]}],
            "generationConfig": {
                "temperature": 0.85,
                "responseMimeType": "application/json",
                "maxOutputTokens": 12000
            }
        },
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:1200]}")
    data = response.json()
    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        pack = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"Could not parse Gemini JSON response: {data}") from exc

    shorts = pack.get("shorts", [])
    long_video = pack.get("long_video", {})
    if len(shorts) != 7:
        raise ValueError(f"Gemini returned {len(shorts)} shorts, expected 7.")
    for i, item in enumerate(shorts):
        if len(item.get("scenes", [])) < 3:
            raise ValueError(f"Short {i+1} has fewer than 3 scenes.")
    if len(long_video.get("scenes", [])) < 8:
        raise ValueError("Long video has too few scenes.")
    return pack

def font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def make_scene_image(path, caption, index, total, vertical):
    w, h = (720, 1280) if vertical else (1280, 720)
    im = Image.new("RGB", (w, h))
    px = im.load()
    # Original procedural background; no stock footage or external image licence dependency.
    top = (7, 13, 35)
    bottom = (34, 18, 66)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[k] * (1-t) + bottom[k] * t) for k in range(3))
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(im, "RGBA")
    rng = random.Random(index * 91 + (1 if vertical else 2))
    for _ in range(90):
        x, y = rng.randrange(w), rng.randrange(h)
        r = rng.choice([1, 2, 3])
        d.ellipse((x-r, y-r, x+r, y+r), fill=(180, 205, 255, rng.randrange(50, 170)))
    # Atmospheric rings and a glowing focal point.
    cx, cy = int(w * .78), int(h * (.34 if vertical else .43))
    for r, a in [(int(w*.30), 22), (int(w*.22), 32), (int(w*.14), 45)]:
        d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(108, 156, 255, a), width=4)
    d.ellipse((cx-int(w*.045), cy-int(w*.045), cx+int(w*.045), cy+int(w*.045)),
              fill=(92, 112, 255, 90))
    # Top label and progress marker.
    small = font(max(18, int(w*.026)))
    d.text((int(w*.07), int(h*.07)), "RAAZ • SCIENCE FILE", font=small, fill=(155, 195, 255, 235))
    d.rounded_rectangle((int(w*.07), int(h*.12), int(w*.93), int(h*.125)),
                        radius=5, fill=(255,255,255,55))
    d.rounded_rectangle((int(w*.07), int(h*.12), int(w*(.07+.86*index/max(1,total))), int(h*.125)),
                        radius=5, fill=(103, 224, 214, 230))
    # Main caption.
    cap_font = font(43 if vertical else 54)
    max_chars = 18 if vertical else 28
    words = str(caption or "एक अनोखा रहस्य").split()
    lines, line = [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) > max_chars and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    lines = lines[:4]
    line_h = 66 if vertical else 76
    y0 = int(h * (.60 if vertical else .62))
    d.rounded_rectangle((int(w*.055), y0-30, int(w*.945), y0+len(lines)*line_h+35),
                        radius=28, fill=(3, 7, 22, 190), outline=(120, 170, 255, 100), width=2)
    for j, line in enumerate(lines):
        box = d.textbbox((0,0), line, font=cap_font)
        tw = box[2] - box[0]
        d.text(((w-tw)//2, y0+j*line_h), line, font=cap_font, fill=(255,255,255,255),
               stroke_width=1, stroke_fill=(0,0,0,180))
    footer = font(max(16, int(w*.022)), bold=False)
    d.text((int(w*.07), int(h*.94)), "AI-ASSISTED STORYTELLING", font=footer, fill=(175,190,220,210))
    im.save(path, quality=94)

async def make_audio(text, path):
    communicate = edge_tts.Communicate(text=str(text), voice=VOICE, rate="+0%", volume="+0%")
    await communicate.save(str(path))

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def render_video(item, label, vertical):
    folder = WORK / label
    folder.mkdir(parents=True, exist_ok=True)
    segment_files = []
    scenes = item["scenes"]
    for idx, scene in enumerate(scenes, start=1):
        image_path = folder / f"scene_{idx:02d}.png"
        audio_path = folder / f"scene_{idx:02d}.mp3"
        video_path = folder / f"scene_{idx:02d}.mp4"
        make_scene_image(image_path, scene.get("onscreen", ""), idx, len(scenes), vertical)
        asyncio.run(make_audio(scene["narration"], audio_path))
        width, height = (720, 1280) if vertical else (1280, 720)
        run([
            "ffmpeg", "-y", "-loop", "1", "-framerate", "24", "-i", str(image_path),
            "-i", str(audio_path), "-vf", f"scale={width}:{height},format=yuv420p",
            "-r", "24", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
            str(video_path)
        ])
        segment_files.append(video_path)

    concat_file = folder / "concat.txt"
    concat_file.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_files), encoding="utf-8")
    out_path = OUT / f"{label}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c", "copy", "-movflags", "+faststart", str(out_path)])
    # Thumbnail uses the first scene's original art.
    thumb = OUT / f"{label}_thumbnail.jpg"
    Image.open(folder / "scene_01.png").convert("RGB").save(thumb, quality=92)
    return out_path, thumb

def next_monday():
    today = datetime.now(IST).date()
    days = (7 - today.weekday()) % 7
    if days == 0:
        days = 7
    return today + timedelta(days=days)

def youtube_client():
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    missing = [x for x in required if not os.getenv(x)]
    if missing:
        raise RuntimeError("Missing YouTube secrets: " + ", ".join(missing))
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds), MediaFileUpload

def upload_one(youtube, MediaFileUpload, video_path, item, publish_dt, thumbnail_path=None):
    body = {
        "snippet": {
            "title": str(item["title"])[:100],
            "description": str(item.get("description", ""))[:4900],
            "tags": [str(t)[:30] for t in item.get("tags", [])[:20]],
            "categoryId": "27",
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=8*1024*1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=False)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Upload progress: {int(status.progress() * 100)}% for {video_path.name}")
    video_id = response["id"]
    log(f"Uploaded {video_path.name}: https://youtu.be/{video_id} scheduled {publish_dt.isoformat()}")
    # Custom thumbnail upload is best-effort; video upload itself remains successful.
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            ).execute()
        except Exception as exc:
            log(f"Thumbnail upload skipped for {video_id}: {exc}")
    return video_id

def main():
    log("Generating weekly Hinglish mystery/science content pack...")
    pack = call_gemini()
    (OUT / "content_pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    rendered = []
    monday = next_monday()
    for i, short in enumerate(pack["shorts"]):
        title = short["title"]
        short["title"] = (title if "#Shorts" in title else title + " #Shorts")[:100]
        label = f"short_{i+1:02d}"
        video, thumb = render_video(short, label, vertical=True)
        rendered.append(("short", short, video, thumb, datetime.combine(monday + timedelta(days=i), time(18,30), IST)))
        log(f"Rendered {label}: {video.stat().st_size // (1024*1024)} MB")

    long_item = pack["long_video"]
    video, thumb = render_video(long_item, "long_video", vertical=False)
    rendered.append(("long", long_item, video, thumb, datetime.combine(monday + timedelta(days=6), time(11,0), IST)))
    log(f"Rendered long video: {video.stat().st_size // (1024*1024)} MB")

    if not PUBLISH:
        log("PUBLISH_ENABLED is false. Videos were rendered but NOT uploaded.")
        log("Download the youtube-autopilot-output artifact from this GitHub Actions run.")
        return

    youtube, MediaFileUpload = youtube_client()
    for kind, item, path, thumb, publish_dt in rendered:
        upload_one(youtube, MediaFileUpload, path, item, publish_dt, thumb)
    log("Weekly batch uploaded and scheduled.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {e}")
        raise
