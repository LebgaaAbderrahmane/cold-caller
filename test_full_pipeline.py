#!/usr/bin/env python3
"""Full pipeline: phone capture → STT → TTS → phone playback."""

import socket
import time
import numpy as np
from phone.adb_controller import ADBController
from voice.stt import STTEngine
from voice.tts import TTSEngine


def main():
    adb = ADBController()

    print("Loading STT (base)...")
    stt = STTEngine("base", device="cpu", compute_type="int8")

    print("Loading TTS...")
    tts = TTSEngine()

    print("\nStarting audio bridge...")
    adb.start_audio_bridge()
    adb.forward_audio_ports()
    time.sleep(2)

    print("\nSpeak into the phone now — capturing 5 seconds...")
    s = socket.socket()
    s.settimeout(10)
    s.connect(("localhost", 4567))
    captured = b""
    start = time.time()
    while time.time() - start < 5:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            captured += chunk
        except socket.timeout:
            break
    s.close()
    print(f"Captured {len(captured)} bytes")

    if len(captured) < 1000:
        print("Too little audio captured")
        adb.remove_audio_forward()
        adb.stop_audio_bridge()
        return

    audio = np.frombuffer(captured, dtype=np.int16).astype(np.float32) / 32768.0

    print("\nTranscribing...")
    start = time.time()
    text = stt.transcribe(audio, language="en")
    elapsed = time.time() - start
    print(f"Transcription ({elapsed:.1f}s): '{text}'")

    if not text:
        text = "I did not catch that. Could you please repeat?"
        print(f"Using fallback: '{text}'")

    print(f"\nSynthesizing response...")
    start = time.time()
    response_audio = tts.synthesize(text, language="en")
    elapsed = time.time() - start
    print(f"Synthesized {len(response_audio) / 16000:.1f}s audio in {elapsed:.1f}s")

    print("\nPlaying back through phone speaker...")
    pcm = (response_audio * 32767).astype(np.int16).tobytes()
    s2 = socket.socket()
    s2.settimeout(10)
    s2.connect(("localhost", 4568))
    s2.sendall(pcm)
    s2.shutdown(socket.SHUT_WR)
    s2.close()
    print(f"Sent {len(pcm)} bytes to phone")

    print("\nCleaning up...")
    adb.remove_audio_forward()
    adb.stop_audio_bridge()
    print("Done!")


if __name__ == "__main__":
    main()
