from typing import Callable


class CallState:
    IDLE = "idle"
    DIALING = "dialing"
    RINGING = "ringing"
    GREETING = "greeting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    CLOSING = "closing"
    HANGUP = "hangup"
    LOGGED = "logged"


_TRANSITIONS = {
    CallState.IDLE: [CallState.DIALING],
    CallState.DIALING: [CallState.RINGING, CallState.IDLE],
    CallState.RINGING: [CallState.GREETING, CallState.IDLE],
    CallState.GREETING: [CallState.LISTENING],
    CallState.LISTENING: [CallState.THINKING, CallState.CLOSING, CallState.IDLE],
    CallState.THINKING: [
        CallState.SPEAKING,
        CallState.LISTENING,
        CallState.CLOSING,
        CallState.IDLE,
    ],
    CallState.SPEAKING: [CallState.LISTENING, CallState.CLOSING, CallState.IDLE],
    CallState.CLOSING: [CallState.HANGUP],
    CallState.HANGUP: [CallState.LOGGED, CallState.IDLE],
    CallState.LOGGED: [CallState.IDLE],
}


class CallStateMachine:
    def __init__(self):
        self.state = CallState.IDLE
        self._listeners: list[Callable[[str, str], None]] = []

    def on_transition(self, callback: Callable[[str, str], None]):
        self._listeners.append(callback)

    def transition(self, new_state: str):
        allowed = _TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid state transition: {self.state} -> {new_state} "
                f"(allowed from {self.state}: {allowed})"
            )
        old = self.state
        self.state = new_state
        for cb in self._listeners:
            try:
                cb(old, new_state)
            except Exception:
                pass

    def can_transition(self, new_state: str) -> bool:
        return new_state in _TRANSITIONS.get(self.state, [])

    def is_active_call(self) -> bool:
        return self.state in (
            CallState.DIALING,
            CallState.RINGING,
            CallState.GREETING,
            CallState.LISTENING,
            CallState.THINKING,
            CallState.SPEAKING,
            CallState.CLOSING,
        )

    def reset(self):
        self.state = CallState.IDLE
