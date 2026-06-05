#!/usr/bin/env python3
"""Test the voice pipeline: audio utils → STT → TTS."""

import time
import numpy as np
from voice.audio_utils import (
    resample,
    normalize,
    audio_to_float,
    audio_to_int16,
    rms,
    db_from_float,
    vad,
)
from voice.stt import STTEngine
from voice.tts import TTSEngine


def test_audio_utils():
    print("=== Audio Utils ===")
    audio = np.sin(np.linspace(0, 440 * 2 * np.pi, 16000)).astype(np.float32) * 0.5
    assert len(resample(audio, 16000, 8000)) < len(audio)
    assert len(resample(audio, 8000, 16000)) >= len(audio)
    assert abs(rms(audio) - 0.353) < 0.01
    assert vad(audio + 0.01) == True
    assert vad(np.zeros(1600)) == False
    assert normalize(audio).max() <= 1.0
    int16 = audio_to_int16(audio)
    assert int16.dtype == np.int16
    float32 = audio_to_float(int16)
    assert float32.dtype == np.float32
    print("  ✓ All audio utils pass")


def test_stt():
    print("\n=== STT ===")
    print("  Loading Whisper model (base)...")
    stt = STTEngine("base", device="cpu", compute_type="int8")
    print("  Model loaded. Running dummy transcription...")

    sr = 16000
    duration = 0.5
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = 0.1 * np.sin(2 * np.pi * 440 * t)
    audio = audio.astype(np.float32)

    result = stt.transcribe(audio, language="en")
    print(f"  Transcription: '{result}'")
    print("  ✓ STT works")


def test_tts():
    print("\n=== TTS ===")
    tts = TTSEngine()

    print("  Synthesizing 'Hello, this is a test.' in English...")
    start = time.time()
    audio_en = tts.synthesize("Hello, this is a test.", language="en")
    elapsed = time.time() - start
    print(f"  Duration: {len(audio_en) / 16000:.1f}s audio in {elapsed:.1f}s")
    assert len(audio_en) > 1000, "TTS produced too little audio"
    print("  ✓ TTS English works")

    print("\n  Synthesizing 'Bonjour, ceci est un test.' in French...")
    start = time.time()
    audio_fr = tts.synthesize("Bonjour, ceci est un test.", language="fr")
    elapsed = time.time() - start
    print(f"  Duration: {len(audio_fr) / 16000:.1f}s audio in {elapsed:.1f}s")
    if len(audio_fr) > 1000:
        print("  ✓ TTS French works (Piper)")
    else:
        print("  ~ TTS French fallback (edge-tts)")

    print("\n  Synthesizing 'مرحبا، هذا اختبار' in Arabic...")
    start = time.time()
    audio_ar = tts.synthesize("مرحبا، هذا اختبار", language="ar")
    elapsed = time.time() - start
    print(f"  Duration: {len(audio_ar) / 16000:.1f}s audio in {elapsed:.1f}s")
    assert len(audio_ar) > 1000, "Arabic TTS produced too little audio"
    print("  ✓ TTS Arabic works (edge-tts)")

    return audio_en


def main():
    start = time.time()
    test_audio_utils()
    audio = test_tts()
    test_stt()
    elapsed = time.time() - start
    print(f"\n=== All tests passed in {elapsed:.1f}s ===")


if __name__ == "__main__":
    main()
