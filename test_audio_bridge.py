#!/usr/bin/env python3
"""Test the audio bridge: capture + playback."""

import socket
import time
import math
import numpy as np
from phone.adb_controller import ADBController

SR = 16000


def test_capture(duration=3):
    s = socket.socket()
    s.settimeout(duration + 2)
    s.connect(("localhost", 4567))
    data = b""
    start = time.time()
    while time.time() - start < duration:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        except socket.timeout:
            break
    s.close()
    return data


def test_playback(duration=2, freq=440):
    t = np.arange(int(SR * duration))
    samples = (np.sin(2 * math.pi * freq * t / SR) * 8000).astype(np.int16)
    pcm_data = samples.tobytes()
    s = socket.socket()
    s.settimeout(10)
    s.connect(("localhost", 4568))
    s.sendall(pcm_data)
    s.shutdown(socket.SHUT_WR)
    s.close()
    return len(pcm_data)


def main():
    adb = ADBController()

    print("Starting audio bridge service...")
    adb.start_audio_bridge()
    time.sleep(2)

    print("Setting up ADB forward...")
    adb.forward_audio_ports()
    time.sleep(1)

    print(f"\n--- Capture test (3s) ---")
    data = test_capture(3)
    if len(data) > 100:
        samples = np.frombuffer(data, dtype=np.int16)
        peak = int(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples.astype(float) ** 2)))
        print(f"  Captured {len(data)} bytes, peak={peak}, RMS={rms:.1f}")
        if rms > 10:
            print("  ✓ AUDIO DETECTED - mic works")
        else:
            print("  ✗ Silence only - check mic")
    else:
        print(f"  ✗ Not enough data ({len(data)} bytes)")

    print(f"\n--- Playback test (2s 440Hz tone) ---")
    sent = test_playback(2)
    print(f"  Sent {sent} bytes to playback port")
    print(f"  ✓ You should have heard a 440Hz tone from the phone speaker")

    print(f"\nCleaning up...")
    adb.remove_audio_forward()
    adb.stop_audio_bridge()
    print("Done")


if __name__ == "__main__":
    main()
