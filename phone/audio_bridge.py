import socket
import threading
import time
from typing import Callable, Optional

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
FRAME_SIZE = SAMPLE_WIDTH * CHANNELS


class AudioBridge:
    """Bidirectional audio streaming between PC and Android device.

    Two TCP connections over ADB forward:
      - Capture port (4567): phone -> PC (MIC audio from phone)
      - Playback port (4568): PC -> phone (TTS audio to phone speaker)

    Half-duplex: capture pauses during playback to avoid echo.
    """

    def __init__(self, adb_controller, capture_port=4567, playback_port=4568):
        self._adb = adb_controller
        self._capture_port = capture_port
        self._playback_port = playback_port
        self._running = False
        self._capture_sock: Optional[socket.socket] = None
        self._playback_sock: Optional[socket.socket] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._capture_callbacks: list[Callable[[bytes], None]] = []
        self._lock = threading.Lock()
        self._currently_playing = False
        self._recording = False

    def on_audio(self, callback: Callable[[bytes], None]):
        """Register callback(pcm_chunk) for captured audio."""
        self._capture_callbacks.append(callback)

    def start(self):
        """Start ADB forward, connect to service, begin capture."""
        if self._running:
            return
        self._running = True

        self._adb.start_audio_bridge()
        self._adb.forward_audio_ports()
        time.sleep(1)

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop(self):
        """Stop all connections and clean up."""
        self._running = False
        self._recording = False
        self._disconnect_capture()
        self._disconnect_playback()
        try:
            self._adb.remove_audio_forward()
        except Exception:
            pass
        try:
            self._adb.stop_audio_bridge()
        except Exception:
            pass

    def play_audio(self, pcm_data: bytes, sample_rate: int = SAMPLE_RATE):
        """Send PCM audio to phone for playback. Blocks until done.

        Pauses capture briefly to avoid echo, then resumes.
        """
        if not self._running:
            return

        with self._lock:
            was_recording = self._recording
            self._recording = False
            self._currently_playing = True

        try:
            self._connect_playback()
            if self._playback_sock:
                self._playback_sock.sendall(pcm_data)
                self._playback_sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        finally:
            self._disconnect_playback()
            with self._lock:
                self._currently_playing = False
                self._recording = was_recording

    def _capture_loop(self):
        while self._running:
            try:
                self._connect_capture()
                with self._lock:
                    self._recording = True
                self._read_capture_stream()
            except Exception:
                pass
            finally:
                with self._lock:
                    self._recording = False
                self._disconnect_capture()
            time.sleep(1)

    def _connect_capture(self):
        self._disconnect_capture()
        self._capture_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._capture_sock.settimeout(10)
        self._capture_sock.connect(("localhost", self._capture_port))

    def _disconnect_capture(self):
        if self._capture_sock:
            try:
                self._capture_sock.close()
            except Exception:
                pass
            self._capture_sock = None

    def _read_capture_stream(self):
        while self._running:
            with self._lock:
                if self._currently_playing:
                    time.sleep(0.05)
                    continue
            try:
                data = self._capture_sock.recv(4096)
                if not data:
                    break
                for cb in self._capture_callbacks:
                    try:
                        cb(data)
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception:
                break

    def _connect_playback(self):
        self._disconnect_playback()
        self._playback_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._playback_sock.settimeout(10)
        self._playback_sock.connect(("localhost", self._playback_port))

    def _disconnect_playback(self):
        if self._playback_sock:
            try:
                self._playback_sock.close()
            except Exception:
                pass
            self._playback_sock = None
