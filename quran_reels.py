#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quran_reels.py — Automatic Quran reels generator (9:16, 1080x1920, 30fps, h264+aac).

Inputs:
  --surah       Surah number (e.g. 13)
  --ayah        Ayah number or range (e.g. 28 or 5-6)
  --reciter     AlQuran Cloud reciter edition id (e.g. ar.abdurrahmaansudais)
  --background  Free-text background description (e.g. "sunrise over the Haram")

The program:
  1. Fetches recitation audio per ayah from AlQuran Cloud and concatenates ranges.
  2. Fetches Uthmani text (quran-uthmani) and English translation (en.sahih).
  3. Times every word with local Whisper (faster-whisper, small model by default),
     then aligns Whisper tokens onto the canonical Uthmani words.
  4. Renders the video: large white Uthmani text, spoken word turns gold (#FFD400),
     synchronized English translation, surah/ayah labels, outro card.
  5. Saves {surah}-{ayah}-v{N}.mp4 in the output folder.

Free only ($0): Python 3.12 + FFmpeg + faster-whisper + Pillow + requests.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

W, H = 1080, 1920
FPS = 30
GOLD = (255, 212, 0, 255)          # #FFD400
WHITE = (255, 255, 255, 255)
WHITE80 = (255, 255, 255, 204)     # white at 80%
DIMCAP = (215, 205, 190, 255)
SHADOW = (0, 0, 0, 170)

API = "https://api.alquran.cloud/v1"
OPENVERSE = "https://api.openverse.org/v1/images/"

# Arabic display names for well-known reciter ids; anything else falls back to
# the edition name returned by the API itself.
RECITER_AR = {
    "ar.mahermuaiqly": "ماهر المعيقلي",
    "ar.abdulbasitmurattal": "عبد الباسط عبد الصمد",
    "ar.minshawi": "محمد صديق المنشاوي",
    "ar.abdurrahmaansudais": "عبد الرحمن السديس",
    "ar.alafasy": "مشاري العفاسي",
    "ar.ahmedajamy": "أحمد بن علي العجمي",
}

FONT_CANDIDATES_AR = [
    "assets/AmiriQuran-Regular.ttf",
    "assets/amiri-quran.ttf",
    "C:/Windows/Fonts/amiri-quran.ttf",
    "/usr/share/fonts/truetype/amiri/amiri-quran.ttf",
]
FONT_CANDIDATES_LATIN = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
AMIRI_URL = "https://github.com/google/fonts/raw/main/ofl/amiriquran/AmiriQuran-Regular.ttf"

AR_DIACRITICS = re.compile(
    "[" + "".join(
        chr(c) for c in range(0x0610, 0x061B)
    ) + "".join(
        chr(c) for c in range(0x064B, 0x0660)
    ) + "ٰۣ۟۠ۡۢۤۥۦۧۨ۩۪ۭ۫۬ـ" + "]"
)


def log(msg):
    print(f"[quran-reels] {msg}", flush=True)


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))}\n{proc.stderr[-2000:]}")
    return proc


def ffprobe_duration(path):
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]).stdout.strip()
    return float(out)


# ---------------------------------------------------------------- fetching

def fetch_ayah(ref, reciter):
    """One API call returns Uthmani text, Sahih translation and reciter audio."""
    url = f"{API}/ayah/{ref}/editions/quran-uthmani,en.sahih,{reciter}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"AlQuran Cloud error for {ref}: {payload.get('status')}")
    data = {entry["edition"]["identifier"]: entry for entry in payload["data"]}
    for entry in data.values():
        expected = f"{entry['surah']['number']}:{entry['numberInSurah']}"
        if expected != ref:
            raise RuntimeError("API returned a different ayah; stopped")
    if reciter not in data or not data[reciter].get("audio"):
        raise RuntimeError(f"no audio returned for {ref} / {reciter}")
    uth, eng, rec = data["quran-uthmani"], data["en.sahih"], data[reciter]
    return {
        "ref": ref,
        "number_in_surah": uth["numberInSurah"],
        "uthmani": uth["text"].strip(),
        "english": eng["text"].strip(),
        "audio_url": rec["audio"],
        "reciter_en": rec["edition"].get("englishName", reciter),
        "surah": {
            "number": uth["surah"]["number"],
            "name_ar": uth["surah"]["name"],           # e.g. سُورَةُ الرَّعۡدِ
            "name_en": uth["surah"]["englishName"],     # e.g. Ar-Ra'd
        },
    }


def download(url, dest):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    Path(dest).write_bytes(r.content)
    return dest


def fetch_background(description, dest):
    """Openverse CC0/PDM only. Never assume all free-to-download images are reusable.
    Metadata is recorded, not a guarantee that the uploader owned the image.
    """
    queries=[description]
    keywords={"شروق":"sunrise", "الحرم":"mosque", "مسجد":"mosque", "طبيعة":"nature",
              "نجوم":"stars", "غروب":"sunset", "بحر":"sea", "جبال":"mountain"}
    translated=" ".join(v for k,v in keywords.items() if k in description)
    if translated:
        queries.append(translated)
    for query in dict.fromkeys(queries):
        try:
            r=requests.get(OPENVERSE,params={"q":query,"page_size":5,
                                            "license":"cc0,pdm","extension":"jpg"},timeout=15)
            r.raise_for_status()
            for pick in r.json().get("results",[]):
                if pick.get("license") not in ("cc0","pdm"):
                    continue
                try:
                    img=requests.get(pick["url"],timeout=25)
                    img.raise_for_status()
                    Path(dest).write_bytes(img.content)
                    with Image.open(dest) as test:
                        test.verify()
                    return dest,{k:pick.get(k) for k in
                                 ("title","creator","creator_url","license","license_version",
                                  "license_url","foreign_landing_url","url","attribution")}
                except Exception:
                    continue
        except requests.RequestException as exc:
            log("stock search failed: "+str(exc))
    # Original procedural landscape, only used with explicit fallback opt-in.
    img=Image.new("RGB",(W,H)); d=ImageDraw.Draw(img)
    for y in range(H):
        t=y/H
        d.line((0,y,W,y),fill=(int(18+90*t),int(25+55*t),int(50-30*t)))
    d.ellipse((390,1120,690,1420),fill=(236,175,85))
    d.polygon([(0,1550),(250,1280),(480,1550),(800,1220),(W,1500),(W,H),(0,H)],fill=(12,25,32))
    img.save(dest)
    return dest,None


# ---------------------------------------------------------------- whisper

def transcribe_words(audio_path, model_size):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), language="ar", word_timestamps=True)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"w": w.word, "start": round(float(w.start), 3),
                          "end": round(float(w.end), 3)})
    return words


# ---------------------------------------------------------------- alignment

def normalize_ar(text):
    text = AR_DIACRITICS.sub("", text).replace("ءَا", "آ").replace("ءا", "آ")
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ٱ", "ا").replace("ى", "ي").replace("ئ", "ي")
                .replace("ؤ", "و").replace("ة", "ه"))
    return re.sub(r"[^\u0621-\u064A ]", "", text).strip()


def canonical_tokens(text):
    # Keep every source character. Attach Quran pause ornaments to the preceding
    # word instead of treating them as spoken words.
    tokens = []
    for token in text.split():
        if not normalize_ar(token) and tokens:
            tokens[-1] += " " + token
        else:
            tokens.append(token)
    return tokens


def align_words(uthmani_words, whisper_words, ayah_dur):
    """Exact normalized token matches only. No interpolation is accepted here."""
    canon = [normalize_ar(w) for w in uthmani_words]
    heard = [normalize_ar(w["w"]) for w in whisper_words]
    matcher = difflib.SequenceMatcher(a=heard, b=canon, autojunk=False)
    found = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            found[block.b+k] = whisper_words[block.a+k]
    timings = [(found[i]["start"], found[i]["end"]) if i in found else None
               for i in range(len(canon))]
    missing = [uthmani_words[i] for i,t in enumerate(timings) if t is None]
    return timings, {"method": "local-whisper-transcription-exact-token-match",
                     "match_ratio": (len(canon)-len(missing))/max(1,len(canon)),
                     "unmatched": missing}


def force_align(audio, words, model_size):
    """Local Whisper cross-attention/DTW on canonical words, not guessed spacing.
    Uses faster-whisper's pinned alignment API. For clips over 28s, reject rather
    than silently discard audio past Whisper's context window.
    """
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    from faster_whisper.tokenizer import Tokenizer
    import numpy as np
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    samples = decode_audio(str(audio), sampling_rate=16000)
    if len(samples)/16000 > 28:
        raise RuntimeError("Forced alignment limited to 28s per ayah; transcription did not fully match.")
    features = model.feature_extractor(samples)
    frames = features.shape[-1]
    features = np.pad(features, ((0,0),(0,max(0,3000-frames))))
    encoded = model.encode(features)
    tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                    task="transcribe", language="ar")
    canonical = [re.sub(r"[^\u0621-\u064A ]","",AR_DIACRITICS.sub("",w)
                    .replace("ٱ","ا").replace("ءا","آ")).strip() for w in words]
    aligned = model.find_alignment(tok,[tok.encode(" "+" ".join(canonical))],
                                   encoded,num_frames=frames)[0]
    heard = [{"w":w["word"],"start":float(w["start"]),"end":float(w["end"]),
              "probability":float(w["probability"])} for w in aligned]
    times, report = align_words(words,heard,len(samples)/16000)
    low = [w for w in heard if w["probability"] < 0.2 or w["end"]-w["start"] < .04]
    report.update(method="local-whisper-canonical-cross-attention-DTW",
                  low_confidence=low, forced_words=heard)
    return times, report


def english_parts(ayah):
    # Sentence-to-clause mapping is used ONLY when a Quran pause boundary and
    # English sentence boundary count agree. No arbitrary 50% word split.
    chunks = re.split(r"(?<=[.!?])\s+", ayah["english"].strip('"'))
    ends = [i+1 for i,w in enumerate(ayah["words"])
            if any(mark in w for mark in "ۖۗۘۙۚۛ")]
    if len(chunks) == len(ends)+1 and len(chunks)>1:
        return [(0 if i==0 else ends[i-1],end,chunks[i])
                for i,end in enumerate(ends+[len(ayah["words"])])]
    return [(0,len(ayah["words"]),ayah["english"])]


# ---------------------------------------------------------------- rendering

def load_fonts(workdir):
    ar_path = None
    for cand in FONT_CANDIDATES_AR:
        p = Path(cand)
        if p.is_absolute() and p.exists():
            ar_path = str(p)
            break
        if (Path(workdir) / cand).exists():
            ar_path = str(Path(workdir) / cand)
            break
    if ar_path is None:
        target = Path(workdir) / "assets" / "AmiriQuran-Regular.ttf"
        target.parent.mkdir(parents=True, exist_ok=True)
        log("downloading Amiri Quran font (free, SIL OFL)...")
        download(AMIRI_URL, target)
        ar_path = str(target)
    latin = next((c for c in FONT_CANDIDATES_LATIN if Path(c).exists()), None)
    if latin is None:
        raise RuntimeError("no Latin font found; set FONT_CANDIDATES_LATIN")
    return ar_path, latin


def ar_digits(n):
    return "".join("٠١٢٣٤٥٦٧٨٩"[int(d)] for d in str(n))


def shadowed(draw, pos, text, font, fill, anchor="mm"):
    x, y = pos
    draw.text((x + 3, y + 4), text, font=font, fill=(0,0,0,230), anchor=anchor, stroke_width=3, stroke_fill=(0,0,0,160))
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def draw_tracked(draw, cx, y, text, font, fill, tracking):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking


def wrap_latin(draw, text, font, max_w):
    lines, cur = [], ""
    for tok in text.split():
        trial = (cur + " " + tok).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines


def layout_ayah(draw, words, font_path, max_w=940, max_lines=4):
    """Greedy RTL line wrap with auto-shrink. Returns (lines, font)."""
    size = 104
    while size > 36:
        font = ImageFont.truetype(font_path, size)
        lines, cur = [], []
        for w in words:
            trial = cur + [w]
            width = sum(draw.textlength(t, font=font) for t in trial) + 30 * (len(trial) - 1)
            if width <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = [w]
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return lines, font
        size -= 4
    raise RuntimeError("Ayah is too long for this layout. Choose a shorter ayah/range; no text was silently clipped.")


def render_state(draw_ctx, gold_upto, ayah, ayah_line_words, ayah_word_global,
                 font_ar_path, font_latin, label_ar, label_en, outro=False):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_pill = ImageFont.truetype(font_ar_path, 52)
    f_cap = ImageFont.truetype(font_latin, 30)
    f_en = ImageFont.truetype(font_latin, 44)

    # top pill: surah name + ayah (Arabic), English caps below
    pw = d.textlength(label_ar, font=f_pill)
    pad_x, pad_y = 44, 16
    x0 = (W - (pw + 2 * pad_x)) / 2
    y0 = 150
    d.rounded_rectangle([x0, y0, x0 + pw + 2 * pad_x, y0 + 52 + 2 * pad_y],
                        radius=42, fill=(10, 10, 14, 150))
    d.text((W / 2, y0 + 26 + pad_y), label_ar, font=f_pill, fill=GOLD, anchor="mm")
    # fit long English surah labels inside safe margins
    while d.textlength(label_en,font=f_cap)+3*len(label_en)>940 and f_cap.size>18:
        f_cap=ImageFont.truetype(font_latin,f_cap.size-1)
    draw_tracked(d, W / 2, y0 + 52 + 2 * pad_y + 34, label_en, f_cap, DIMCAP, 3)

    # No card: text stays centered with its own soft shadow for contrast.
    n_lines = len(ayah_line_words)
    line_ys = [900 + i * 155 - 77.5 * (n_lines - 1) for i in range(n_lines)]
    for li, line in enumerate(ayah_line_words):
        first_g = ayah_word_global[li][0]

        lines_font = layout_ayah(d, [w for ln in ayah_line_words for w in ln],
                                 font_ar_path)[1]
        widths = [d.textlength(w, font=lines_font) for w in line]
        total = sum(widths) + 30 * (len(line) - 1)
        x = W / 2 + total / 2
        for wi, (w, wd) in enumerate(zip(line, widths)):
            gi = ayah_word_global[li][wi]
            x -= wd
            fill = GOLD if gi <= gold_upto else WHITE
            shadowed(d, (x + wd / 2, line_ys[li]), w, lines_font, fill)
            x -= 30

    # English follows semantic pause/sentence parts when available, otherwise ayah.
    local_index=gold_upto-ayah_word_global[0][0]
    text_en=next((text for start,end,text in ayah["parts"] if start<=local_index<end),ayah["english"])
    if text_en:
        lines_t = wrap_latin(d, text_en, f_en, 900)
        while len(lines_t)>4 and f_en.size>24:
            f_en=ImageFont.truetype(font_latin,f_en.size-2)
            lines_t=wrap_latin(d,text_en,f_en,900)
        if len(lines_t)>4:
            raise RuntimeError("Translation too long for safe display; choose a shorter ayah")
        ty = 1280 - 30 * (len(lines_t) - 1)
        for tl in lines_t:
            shadowed(d, (W / 2, ty), tl, f_en, WHITE80)
            ty += 60
    draw_tracked(d, W / 2, 1450, f"AYAH {ayah['number_in_surah']}", f_cap, GOLD, 10)
    if outro:
        shadowed(d,(W/2,1620),"تابع للمزيد",ImageFont.truetype(font_ar_path,72),GOLD)
        shadowed(d,(W/2,1725),f"القارئ: {RECITER_AR_LABEL}",ImageFont.truetype(font_ar_path,46),WHITE)
    if ayah.get("requires_review"):
        d.rectangle((170,1810,910,1875),fill=(30,0,0,220))
        d.text((W/2,1840),"REVIEW - approximate word timing",font=f_cap,fill=WHITE,anchor="mm")
    return img


# ---------------------------------------------------------------- pipeline

RECITER_AR_LABEL = ""  # set in main for the outro card


def main():
    ap = argparse.ArgumentParser(description="Automatic Quran reels generator")
    ap.add_argument("--surah", type=int, required=True)
    ap.add_argument("--ayah", required=True, help="e.g. 28 or 5-6")
    ap.add_argument("--reciter", required=True, help="AlQuran Cloud edition id")
    ap.add_argument("--background", required=True, help="background description")
    ap.add_argument("--out", default="out", help="output folder")
    ap.add_argument("--model", default="small", help="whisper model (default: small)")
    ap.add_argument("--allow-approximate", action="store_true",
                    help="Explicit opt-in: render marked REVIEW output if confidence is low")
    ap.add_argument("--allow-generated-background", action="store_true",
                    help="Explicit opt-in: generated landscape if stock search fails; not a literal landmark")
    ap.add_argument("--background-file", type=Path, help="Optional local image you have rights to use")
    args = ap.parse_args()
    if not features.check("raqm"):
        sys.exit("Pillow requires libraqm for correct Arabic shaping. Install a Pillow wheel with raqm support.")
    if not 1 <= args.surah <= 114:
        ap.error("surah must be between 1 and 114")
    if not re.fullmatch(r"ar\.[a-z0-9]+",args.reciter):
        ap.error("invalid reciter edition identifier")

    workdir = Path.cwd()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    if "'" in str(outdir.resolve()):
        ap.error("Choose an --out path without apostrophes (FFmpeg concat path restriction)")
    import tempfile
    assets = Path(tempfile.mkdtemp(prefix="build-",dir=outdir)).resolve()

    m = re.fullmatch(r"(\d+)(?:-(\d+))?", args.ayah)
    if not m:
        sys.exit("--ayah must be a number or range like 28 or 5-6")
    a1 = int(m.group(1))
    a2 = int(m.group(2)) if m.group(2) else a1
    if a1 < 1 or a2 < a1 or a2-a1 > 285:
        ap.error("invalid ayah range")
    refs = [f"{args.surah}:{a}" for a in range(a1, a2 + 1)]

    # 1+2: fetch text, translation, audio
    ayahs = []
    for ref in refs:
        log(f"fetching {ref} ...")
        ayah = fetch_ayah(ref, args.reciter)
        mp3 = assets / f"audio-{ref.replace(':', '-')}.mp3"
        download(ayah["audio_url"], mp3)
        ayah["audio_path"] = mp3
        wav = mp3.with_suffix(".wav")
        run(["ffmpeg","-y","-i",str(mp3),"-ar","44100","-ac","1",str(wav)])
        ayah["audio_path"] = wav
        ayah["duration"] = ffprobe_duration(wav)
        ayahs.append(ayah)

    # concat audio (re-encode to a single wav for stable timing)
    if len(ayahs) == 1:
        audio_all = assets / "audio-all.wav"
        run(["ffmpeg", "-y", "-i", str(ayahs[0]["audio_path"]), "-ar", "44100",
             "-ac", "1", str(audio_all)])
    else:
        lst = assets / "concat.txt"
        lst.write_text("".join(f"file '{a['audio_path'].resolve().as_posix()}'\n" for a in ayahs),
                       encoding="utf-8")
        audio_all = assets / "audio-all.wav"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-ar", "44100", "-ac", "1", str(audio_all)])
    total_dur = ffprobe_duration(audio_all)
    log(f"total recitation: {total_dur:.2f}s ({len(ayahs)} ayah(s))")

    # 3: whisper per ayah, offset into the combined timeline
    offset = 0.0
    all_reports = []
    for ayah in ayahs:
        log(f"whisper: {ayah['ref']} ...")
        heard = transcribe_words(ayah["audio_path"], args.model)  # local timeline
        ayah["whisper"] = heard
        ayah["offset"] = offset
        offset += ayah["duration"]

        uth_words = canonical_tokens(ayah["uthmani"])
        timings, report = align_words(uth_words, heard, ayah["duration"])
        if report["unmatched"]:
            timings, report = force_align(ayah["audio_path"],uth_words,args.model)
        unsafe = bool(report["unmatched"] or report.get("low_confidence"))
        report["ref"] = ayah["ref"]
        report["requires_review"] = unsafe
        (assets / (ayah["ref"].replace(":","-")+"-alignment.json")).write_text(
            json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        if any(t is None for t in timings):
            raise RuntimeError("Canonical word alignment incomplete; stopped. See alignment JSON in "+str(assets))
        if unsafe and not args.allow_approximate:
            raise RuntimeError("Low-confidence canonical alignment; stopped without making a video. "
                               "Inspect alignment JSON. --allow-approximate makes a visibly marked review copy only.")
        if unsafe:
            log("WARNING: explicit approximate REVIEW mode, not publication-ready")
        timings = [(s + ayah["offset"], e + ayah["offset"]) for s, e in timings]
        ayah["words"] = uth_words
        ayah["timings"] = timings
        ayah["parts"] = english_parts(ayah)
        ayah["requires_review"] = unsafe
        all_reports.append(report)

    global_review = any(r["requires_review"] for r in all_reports)
    for ayah in ayahs:
        ayah["requires_review"] = global_review
    for ayah in ayahs:
        previous = -1.0
        for start,end in ayah["timings"]:
            if not (0 <= start < end <= ayah["offset"]+ayah["duration"]+.05) or start < previous:
                raise RuntimeError("Invalid/nonmonotonic alignment; stopped without rendering")
            previous = start
    # 4: background
    if args.background_file:
        bg_path = args.background_file.resolve()
        with Image.open(bg_path) as test_image:
            test_image.verify()
        bg_meta = {"source":"user-supplied local image", "rights":"user must verify"}
    else:
        bg_path, bg_meta = fetch_background(args.background, assets / "background.jpg")
        if bg_meta is None and not args.allow_generated_background:
            raise RuntimeError("No suitable licensed stock found. Stopped. Supply --background-file or explicitly allow generated background.")
        if bg_meta is None:
            bg_meta={"source":"procedural sunrise landscape", "literal_landmark":False,
                     "description_matched":False,"rights":"original generated image"}

    # Build an intentional full-canvas image. A blurred/lifted image fill avoids
    # a near-black bottom half from a silhouette photograph. The sharp image is
    # softly blended in, and a separate scrim protects text contrast.
    from PIL import ImageOps, ImageEnhance
    with Image.open(bg_path) as source:
        cover=ImageOps.fit(source.convert("RGB"),(W,H),method=Image.Resampling.LANCZOS)
    diffuse=cover.filter(ImageFilter.GaussianBlur(60))
    diffuse=ImageEnhance.Brightness(diffuse).enhance(.65)
    diffuse=Image.blend(diffuse,Image.new("RGB",(W,H),(35,27,33)),.30)
    composed=Image.blend(diffuse,cover,.28)
    prepared=assets/"background-prepared.jpg"
    composed.save(prepared,quality=94)
    bg_path=prepared

    # 5: render word-state overlays
    global RECITER_AR_LABEL
    rec0 = ayahs[0]
    RECITER_AR_LABEL = RECITER_AR.get(args.reciter, rec0["reciter_en"])
    surah = rec0["surah"]
    if a1 == a2:
        label_ar = f"سورة {strip_surah_prefix(surah['name_ar'])} - {ar_digits(a1)}"
        label_en = f"{surah['name_en'].upper()} {args.surah}:{a1}"
    else:
        label_ar = f"سورة {strip_surah_prefix(surah['name_ar'])} - {ar_digits(a1)}-{ar_digits(a2)}"
        label_en = f"{surah['name_en'].upper()} {args.surah}:{a1}-{a2}"

    font_ar, font_latin = load_fonts(workdir)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    # per-ayah line layout with global word indices
    gidx = 0
    for ayah in ayahs:
        lines, _font = layout_ayah(probe, ayah["words"], font_ar)
        ayah["lines"] = lines
        ayah["line_global"] = []
        for line in lines:
            idxs = list(range(gidx, gidx + len(line)))
            ayah["line_global"].append(idxs)
            gidx += len(line)

    # timeline of states: one per word boundary + outro in the last second
    events = []  # (start, end, gold_upto, ayah_idx, outro)
    flat = []    # (start, end) per global word index
    for ai, ayah in enumerate(ayahs):
        for t in ayah["timings"]:
            flat.append(t)
    last_word_end = max(e for _, e in flat)
    outro_start = max(0,total_dur - 1.0)

    prev = 0.0
    g = 0
    for ai, ayah in enumerate(ayahs):
        for wi, (s, e) in enumerate(ayah["timings"]):
            start = max(prev, min(s, total_dur))
            events.append([start, None, g, ai, start >= outro_start])
            prev = start
            g += 1
    # close final text state at outro_start
    if events:
        events[0][0] = 0.0  # text visible from the first frames, no fade-in gap
    for i, ev in enumerate(events):
        ev[1] = events[i + 1][0] if i + 1 < len(events) else total_dur
    events = [ev for ev in events if ev[1] - ev[0] > 0.02]
    for i, ev in enumerate(events):  # re-chain after filtering to avoid gaps
        ev[1] = events[i + 1][0] if i + 1 < len(events) else total_dur
    # Insert an exact final-second event without removing the recited text.
    for i,ev in enumerate(events):
        if ev[0] < outro_start < ev[1]:
            tail=[outro_start,ev[1],ev[2],ev[3],True]
            ev[1]=outro_start
            events.insert(i+1,tail)
            break
    if events:
        events[-1][1]=total_dur
        events[-1][4]=events[-1][0]>=outro_start

    states_dir = assets / "states"
    states_dir.mkdir(exist_ok=True)
    concat_lines = []
    for si, (s, e, gold_upto, ai, outro) in enumerate(events):
        ayah = ayahs[ai]
        png = states_dir / f"s{si:03d}.png"
        img = render_state(probe, gold_upto, ayah, ayah["lines"], ayah["line_global"],
                           font_ar, font_latin, label_ar, label_en, outro=outro)
        img.save(png)
        concat_lines.append(f"file '{png.resolve().as_posix()}'\nduration {e - s:.3f}")
    concat_file = assets / "states.txt"
    concat_lines.append(f"file '{(states_dir / f's{len(events)-1:03d}.png').resolve().as_posix()}'")
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

    # 6: compose video (slow zoom background + timed overlays + recitation)
    n = 0
    while True:
        n += 1
        outname = outdir / (f"{args.surah}-{a1}" + (f"-{a2}" if a2 != a1 else "")
                            + ("-REVIEW" if any(r["requires_review"] for r in all_reports) else "") + f"-v{n}.mp4")
        if not outname.exists():
            break
    zoom = (f"zoompan=z='1+0.0006*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:fps={FPS}:s={W}x{H}")
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_path),
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_all),
        "-filter_complex",
        f"[0:v]scale=1216:2160:force_original_aspect_ratio=increase,crop=1216:2160,{zoom},eq=brightness=-0.04[bg];"
        f"[1:v]fps={FPS},format=rgba[ov];"
        f"[bg][ov]overlay=0:0:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{total_dur:.3f}", "-movflags", "+faststart",
        str(outname),
    ])

    log(f"DONE: {outname} ({total_dur:.2f}s)")
    manifest = {
        "output": str(outname), "duration_s": round(total_dur, 2),
        "refs": refs, "reciter": args.reciter, "background": bg_meta,
        "alignment": all_reports, "cost_usd": 0,
        "audio_sources": [a["audio_url"] for a in ayahs],
        "text_source": API,
        "publication_rights": "Recitation redistribution rights NOT verified. Background metadata is not proof of rights.",
        "translation_sync": "Sentence/pause parts when counts agree; otherwise whole ayah at ayah boundary.",
        "test_platform": sys.platform, "python": sys.version.split()[0],
    }
    (outdir / (outname.stem + ".json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def strip_surah_prefix(name_ar):
    # "سُورَةُ الرَّعۡدِ" -> "الرَّعۡدِ"
    m = re.sub(r"^سُورَةُ\s*", "", name_ar)
    return AR_DIACRITICS.sub("", m).replace("ۡ", "")


if __name__ == "__main__":
    main()
