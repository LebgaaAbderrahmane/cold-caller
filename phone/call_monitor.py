import threading
import time
from typing import Callable, Optional


class CallMonitor:
    """Event-driven call state observer.

    Polls ADB telephony state on a background thread and fires callbacks
    on state transitions. Provides blocking wait methods for orchestration.
    """

    def __init__(self, adb_controller):
        self._adb = adb_controller
        self._current_state: str = "idle"
        self._previous_state: str = "idle"
        self._call_start_time: Optional[float] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listeners: list[Callable[[str, str], None]] = []
        self._answer_listeners: list[Callable[[], None]] = []
        self._hangup_listeners: list[Callable[[int], None]] = []
        self._lock = threading.Lock()

    # ── Callback registration ──────────────────────────────────────

    def on_state_change(self, callback: Callable[[str, str], None]):
        """Register callback(old_state, new_state) for every state transition."""
        self._listeners.append(callback)

    def on_answered(self, callback: Callable[[], None]):
        """Register callback for when a call is answered (offhook)."""
        self._answer_listeners.append(callback)

    def on_hangup(self, callback: Callable[[int], None]):
        """Register callback(duration_seconds) for when a call ends."""
        self._hangup_listeners.append(callback)

    # ── Blocking waits ─────────────────────────────────────────────

    def wait_for_state(self, target: str, timeout: float = 30) -> bool:
        """Block until state == target. Returns False on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._current_state == target:
                    return True
            time.sleep(0.3)
        return False

    def wait_for_answer(self, timeout: float = 40) -> Optional[float]:
        """Block until call answered (offhook). Returns call duration or None on timeout."""
        deadline = time.time() + timeout
        saw_ringing = False
        while time.time() < deadline:
            with self._lock:
                state = self._current_state
            if state == "ringing":
                saw_ringing = True
            elif state == "offhook":
                return _elapsed(self._call_start_time)
            elif state == "idle" and saw_ringing:
                return None
            time.sleep(0.3)
        return None

    def wait_for_hangup(self, timeout: float = 300) -> Optional[int]:
        """Block until call ends (idle). Returns duration or None on timeout."""
        with self._lock:
            start = self._call_start_time or time.time()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._current_state == "idle":
                    return int(time.time() - start)
            time.sleep(0.3)
        return None

    def is_in_call(self) -> bool:
        with self._lock:
            return self._current_state in ("ringing", "offhook")

    def get_call_duration(self) -> Optional[float]:
        return _elapsed(self._call_start_time)

    def get_state(self) -> str:
        with self._lock:
            return self._current_state

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    # ── Internals ──────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                new_state = self._adb.get_call_state()
                with self._lock:
                    old_state = self._current_state
                    if new_state != old_state:
                        self._previous_state = old_state
                        self._current_state = new_state
                        if new_state == "offhook" and old_state != "offhook":
                            self._call_start_time = time.time()
                        elif new_state == "idle" and old_state != "idle":
                            self._call_start_time = None

                if new_state != old_state:
                    self._fire_state_change(old_state, new_state)
                    if new_state == "offhook" and old_state != "offhook":
                        self._fire_answered()
                    elif new_state == "idle" and old_state != "idle":
                        self._fire_hangup()
            except Exception:
                pass
            time.sleep(0.5)

    def _fire_state_change(self, old_state: str, new_state: str):
        for cb in self._listeners:
            try:
                cb(old_state, new_state)
            except Exception:
                pass

    def _fire_answered(self):
        for cb in self._answer_listeners:
            try:
                cb()
            except Exception:
                pass

    def _fire_hangup(self):
        duration = 0
        with self._lock:
            if self._call_start_time:
                duration = int(time.time() - self._call_start_time)
        for cb in self._hangup_listeners:
            try:
                cb(duration)
            except Exception:
                pass


def _elapsed(start: Optional[float]) -> Optional[float]:
    if start is None:
        return None
    return time.time() - start
