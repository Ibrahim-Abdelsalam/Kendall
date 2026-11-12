#!/usr/bin/env python3
"""
build_audio.py - High-fidelity local speech generation for Kendall guided tours.

Generates sentence-by-sentence audio clips, inserts 300ms silence between sentences,
normalizes loudness with ffmpeg loudnorm (-16 LUFS), and exports mono 64 kbps MP3s.
Caches generation by SHA256(text, voice, backend, speed) and writes manifest.json.

Supported backends:
- kokoro (default, English, local ONNX, default voice af_heart)
- edge (edge-tts, e.g. for Arabic ar-EG-SalmaNeural / ar-EG-ShakirNeural or English)
- piper (piper-tts fallback)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TOURS = os.path.join(BASE_DIR, "web", "tour", "tours.json")
DEFAULT_AUDIO_DIR = os.path.join(BASE_DIR, "web", "tour", "audio")
KOKORO_MODEL_PATH = os.path.join(BASE_DIR, "models", "kokoro", "kokoro-v0_19.onnx")
KOKORO_VOICES_PATH = os.path.join(BASE_DIR, "models", "kokoro", "voices-v1.0.bin")


def check_ffmpeg():
    """Checks if ffmpeg and ffprobe are available."""
    # Ensure current python environment's bin directory is in PATH
    py_bin_dir = os.path.dirname(sys.executable)
    if py_bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{py_bin_dir}:{os.environ.get('PATH', '')}"

    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not ffmpeg_bin or not ffprobe_bin:
        print("ERROR: ffmpeg and ffprobe are required for loudness normalization and MP3 encoding.")
        print("Install via: conda install -c conda-forge ffmpeg")
        sys.exit(1)
    return ffmpeg_bin, ffprobe_bin


def get_audio_duration_seconds(file_path):
    """Measures duration of audio file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return float(res.stdout.strip())


def clean_text_for_speech(text):
    """Refines acronyms, scientific signs, and units for natural TTS pronunciation."""
    t = text
    # Scientific notations & units
    t = re.sub(r"-(\d+\.\d+)", r"minus \1", t)
    t = re.sub(r"\+(\d+\.\d+)", r"plus \1", t)
    t = t.replace("°C", " degrees Celsius")
    t = t.replace("mm/month/decade", " millimeters per month per decade")
    t = t.replace("mm/decade", " millimeters per decade")
    t = t.replace("p-value", "P value")
    t = t.replace("p =", "P equals")
    t = t.replace("p <", "P less than")
    t = t.replace("TRMM", "Trim")
    t = t.replace("GPM", "G P M")
    t = t.replace("GLDAS", "G L D A S")
    t = t.replace("MERRA-2", "Mera two")
    t = t.replace("AOD", "A O D")
    t = t.replace("FDR", "F D R")
    t = t.replace("ENSO", "Enso")
    return t


def split_into_sentences(text):
    """Splits text into spoken sentences on punctuation boundaries."""
    # Split on period, exclamation, question mark followed by space
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


class KokoroEngine:
    def __init__(self, voice_name="af_heart"):
        try:
            from kokoro_onnx import Kokoro
            import soundfile as sf
        except ImportError:
            print("ERROR: kokoro-onnx and soundfile are required for kokoro backend.")
            print("Install via: pip install kokoro-onnx soundfile")
            sys.exit(1)

        if not os.path.exists(KOKORO_MODEL_PATH) or not os.path.exists(KOKORO_VOICES_PATH):
            print(f"ERROR: Kokoro model files missing at {KOKORO_MODEL_PATH} or {KOKORO_VOICES_PATH}")
            print("Download kokoro-v0_19.onnx and voices-v1.0.bin from github.com/thewh1teagle/kokoro-onnx")
            sys.exit(1)

        self.kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
        self.voice_name = voice_name
        self.sample_rate = 24000
        print(f"Kokoro initialized with voice '{self.voice_name}'.")

    def generate_step_audio(self, text, speed=1.0):
        sentences = split_into_sentences(clean_text_for_speech(text))
        silence = np.zeros(int(0.3 * self.sample_rate), dtype=np.float32)

        combined_samples = []
        for i, s in enumerate(sentences):
            samples, sr = self.kokoro.create(s, voice=self.voice_name, speed=speed, lang="en-us")
            if i > 0:
                combined_samples.append(silence)
            combined_samples.append(samples)

        return np.concatenate(combined_samples), self.sample_rate


class EdgeEngine:
    def __init__(self, voice_name="en-US-AriaNeural"):
        try:
            import edge_tts
        except ImportError:
            print("ERROR: edge-tts is required for edge backend.")
            print("Install via: pip install edge-tts")
            sys.exit(1)
        self.voice_name = voice_name
        print(f"EdgeTTS initialized with voice '{self.voice_name}'.")

    def generate_step_audio_file(self, text, out_wav, speed=1.0):
        import asyncio
        import edge_tts

        sentences = split_into_sentences(clean_text_for_speech(text))
        temp_dir = tempfile.mkdtemp()
        clip_paths = []

        rate_str = f"+{int((speed - 1.0) * 100)}%" if speed >= 1.0 else f"{int((speed - 1.0) * 100)}%"

        async def _gen(sent, out_file):
            communicate = edge_tts.Communicate(sent, self.voice_name, rate=rate_str)
            await communicate.save(out_file)

        for i, sent in enumerate(sentences):
            part_path = os.path.join(temp_dir, f"part_{i}.mp3")
            asyncio.run(_gen(sent, part_path))
            clip_paths.append(part_path)

        # Concatenate with 300ms silence using ffmpeg filter_complex
        filter_inputs = []
        filter_str = ""
        for i, p in enumerate(clip_paths):
            filter_inputs.extend(["-i", p])
            if i > 0:
                filter_inputs.extend(["-f", "lavfi", "-t", "0.3", "-i", "anullsrc=r=24000:cl=mono"])

        total_inputs = len(clip_paths) + max(0, len(clip_paths) - 1)
        streams = "".join(f"[{k}:a]" for k in range(total_inputs))
        filter_str = f"{streams}concat=n={total_inputs}:v=0:a=1[aout]"

        cmd = ["ffmpeg", "-y"] + filter_inputs + ["-filter_complex", filter_str, "-map", "[aout]", out_wav]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        shutil.rmtree(temp_dir)


def main():
    parser = argparse.ArgumentParser(description="Build natural audio for Kendall guided tours.")
    parser.add_argument("--backend", choices=["kokoro", "edge", "piper"], default="kokoro", help="TTS Backend")
    parser.add_argument("--voice", default="af_heart", help="Voice identifier (e.g. af_heart, ar-EG-SalmaNeural)")
    parser.add_argument("--lang", default="en", help="Language code ('en' or 'ar')")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech rate multiplier")
    parser.add_argument("--tours", default=DEFAULT_TOURS, help="Path to tours.json")
    parser.add_argument("--output-dir", default=DEFAULT_AUDIO_DIR, help="Audio output directory")
    parser.add_argument("--force", action="store_true", help="Force rebuild all steps")

    args = parser.parse_args()

    check_ffmpeg()

    if not os.path.exists(args.tours):
        print(f"ERROR: tours file not found at {args.tours}. Run scripts/build_tours.py first.")
        sys.exit(1)

    with open(args.tours, "r", encoding="utf-8") as f:
        tours_data = json.load(f)

    lang_dir = os.path.join(args.output_dir, args.lang)
    os.makedirs(lang_dir, exist_ok=True)

    cache_file = os.path.join(args.output_dir, ".cache.json")
    cache = {}
    if os.path.exists(cache_file) and not args.force:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    manifest_file = os.path.join(args.output_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    # Initialize selected backend
    if args.backend == "kokoro":
        engine = KokoroEngine(voice_name=args.voice)
    elif args.backend == "edge":
        voice = args.voice if args.voice != "af_heart" else ("ar-EG-SalmaNeural" if args.lang == "ar" else "en-US-AriaNeural")
        engine = EdgeEngine(voice_name=voice)
    elif args.backend == "piper":
        print("ERROR: piper backend is not yet configured on this system. Install piper-tts and piper voices.")
        print("Install via: pip install piper-tts")
        sys.exit(1)

    all_steps = []
    for tour_id, tour in tours_data.items():
        for step in tour["steps"]:
            all_steps.append((tour_id, step))

    print(f"Processing {len(all_steps)} audio steps using backend '{args.backend}' (voice: {args.voice}, lang: {args.lang})...")

    import soundfile as sf

    for tour_id, step in all_steps:
        step_id = step["id"]
        text = step["text"]
        out_mp3 = os.path.join(lang_dir, f"{step_id}.mp3")

        cache_key = f"{step_id}:{text}:{args.voice}:{args.backend}:{args.speed}"
        text_hash = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

        if not args.force and os.path.exists(out_mp3) and cache.get(step_id) == text_hash and step_id in manifest:
            # Step is cached and already exists
            print(f"  [CACHED] {step_id} ({manifest[step_id]['duration']:.2f}s)")
            continue

        print(f"  [GENERATING] {step_id}: {text[:60]}...")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            tmp_wav_path = tmp_wav.name

        try:
            if args.backend == "kokoro":
                samples, sr = engine.generate_step_audio(text, speed=args.speed)
                sf.write(tmp_wav_path, samples, sr)
            elif args.backend == "edge":
                engine.generate_step_audio_file(text, tmp_wav_path, speed=args.speed)

            # Loudness normalization (-16 LUFS, TP -1.5) and 64k mono MP3 compression
            cmd_norm = [
                "ffmpeg",
                "-y",
                "-i", tmp_wav_path,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame",
                "-b:a", "64k",
                "-ac", "1",
                out_mp3,
            ]
            subprocess.run(cmd_norm, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            dur = get_audio_duration_seconds(out_mp3)
            cache[step_id] = text_hash
            manifest[step_id] = {
                "file": f"audio/{args.lang}/{step_id}.mp3",
                "duration": round(dur, 2),
                "hash": text_hash,
                "title": step["title"],
            }
            print(f"    -> Done: {dur:.2f}s ({os.path.getsize(out_mp3) // 1024} KB)")
        finally:
            if os.path.exists(tmp_wav_path):
                os.remove(tmp_wav_path)

    # Save cache & manifest
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    total_bytes = sum(
        os.path.getsize(os.path.join(BASE_DIR, "web", "tour", item["file"]))
        for item in manifest.values()
        if os.path.exists(os.path.join(BASE_DIR, "web", "tour", item["file"]))
    )
    total_mb = total_bytes / (1024 * 1024)
    print(f"\nAll tour audio steps generated successfully!")
    print(f"Total audio bundle size: {total_mb:.2f} MB (Constraint: < 15 MB)")
    assert total_mb < 15.0, f"Total audio bundle size ({total_mb:.2f} MB) exceeds 15 MB limit!"


if __name__ == "__main__":
    main()
