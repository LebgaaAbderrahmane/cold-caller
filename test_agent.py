#!/usr/bin/env python3
"""Test the CallAgent with mocked dependencies."""

from unittest.mock import MagicMock, patch
import numpy as np

from ai.agent import CallAgent
from ai.state_machine import CallState


SR = 16000


def _make_mocks():
    adb = MagicMock()
    monitor = MagicMock()
    audio_bridge = MagicMock()
    stt = MagicMock()
    tts = MagicMock()
    return adb, monitor, audio_bridge, stt, tts


def _make_config(**overrides):
    cfg = {
        "agent_name": "Alex",
        "company_name": "TestCo",
        "value_prop": "saving you money",
        "call_objective": "qualify the lead",
        "ollama_model": "llama3",
        "max_turns": 10,
    }
    cfg.update(overrides)
    return cfg


def _fake_audio(duration_sec=1.0):
    n = int(SR * duration_sec)
    t = np.linspace(0, duration_sec, n, endpoint=False)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t)
    return (audio * 32767).astype(np.int16)


class TestCallAgent:
    def setup_method(self):
        self.adb, self.monitor, self.audio_bridge, self.stt, self.tts = _make_mocks()
        self.config = _make_config()

        self.monitor.is_in_call.return_value = True
        self.monitor.wait_for_answer.return_value = 5.0
        self.monitor.get_call_duration.return_value = 60.0
        self.stt.transcribe.return_value = "Hello, this is a test."
        self.stt.detect_language.return_value = "en"
        self.tts.synthesize.return_value = np.zeros(SR, dtype=np.float32)

    def _make_agent(self):
        return CallAgent(
            self.config, self.adb, self.monitor, self.audio_bridge, self.stt, self.tts
        )

    def _make_contact(self, name="John", phone="+213555123456", company="Acme"):
        return type("Contact", (), {"name": name, "phone": phone, "company": company})()

    def _run(self, agent, contact):
        fake_audio = _fake_audio(1.0)
        with patch.object(agent, "_listen_for_turn", return_value=fake_audio):
            with patch("ai.agent.ollama.chat") as mock_ollama:
                mock_ollama.return_value = {
                    "message": {"content": "Sure, let me check."}
                }
                return agent.run_call(contact)

    # ── Tests ─────────────────────────────────────────────────────

    def test_complete_call_flow(self):
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["answered"] is True, f"Expected True, got {result}"
        assert result["outcome"] == "completed", f"Expected completed, got {result}"
        assert result["transcript"] is not None
        assert agent.sm.state == CallState.IDLE

    def test_no_answer(self):
        self.monitor.wait_for_answer.return_value = None
        agent = self._make_agent()
        contact = self._make_contact()
        result = agent.run_call(contact)

        assert result["answered"] is False
        assert result["outcome"] == "no_answer"
        self.adb.hang_up.assert_called_once()
        assert agent.sm.state == CallState.IDLE

    def test_objection_not_interested(self):
        self.stt.transcribe.return_value = "I am not interested, goodbye."
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["outcome"] == "not_interested"
        assert agent.sm.state == CallState.IDLE

    def test_empty_transcript_retries(self):
        self.stt.transcribe.return_value = "  "
        agent = self._make_agent()
        contact = self._make_contact()

        fake_audio = _fake_audio(1.0)
        with patch.object(agent, "_listen_for_turn", return_value=fake_audio):
            with patch("ai.agent.ollama.chat") as mock_ollama:
                mock_ollama.return_value = {"message": {"content": "Hello there."}}
                result = agent.run_call(contact)

        assert result["outcome"] == "completed"
        assert agent.sm.state == CallState.IDLE

    def test_call_drops_during_conversation(self):
        self.monitor.is_in_call.side_effect = [True] + [False]
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["answered"] is True
        assert agent.sm.state == CallState.IDLE

    def test_language_detection_fallback(self):
        self.stt.detect_language.side_effect = Exception("detection failed")
        self.stt.transcribe.return_value = "Bonjour."
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["answered"] is True
        assert result["outcome"] == "completed"
        assert agent.sm.state == CallState.IDLE

    def test_ollama_failure(self):
        agent = self._make_agent()
        contact = self._make_contact()
        with patch.object(agent, "_listen_for_turn", return_value=_fake_audio(1.0)):
            with patch("ai.agent.ollama.chat") as mock_ollama:
                mock_ollama.side_effect = Exception("Ollama not running")
                result = agent.run_call(contact)

        assert result["answered"] is True
        assert agent.sm.state == CallState.IDLE

    def test_adb_error_during_call(self):
        self.adb.make_call.side_effect = Exception("ADB device disconnected")
        agent = self._make_agent()
        contact = self._make_contact()
        result = agent.run_call(contact)

        assert result["answered"] is False
        assert result["outcome"] == "error"
        assert result["error"] is not None
        assert agent.sm.state == CallState.IDLE

    def test_max_turns_respected(self):
        self.config["max_turns"] = 2
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["answered"] is True
        assert result["outcome"] == "completed"
        assert agent.sm.state == CallState.IDLE

    def test_state_machine_transitions_full_cycle(self):
        self.monitor.wait_for_answer.return_value = 3.0
        agent = self._make_agent()
        contact = self._make_contact()

        transitions = []
        agent.sm.on_transition(lambda old, new: transitions.append((old, new)))

        self._run(agent, contact)

        states = [t[1] for t in transitions]
        required = [
            CallState.DIALING,
            CallState.RINGING,
            CallState.GREETING,
            CallState.LISTENING,
            CallState.THINKING,
            CallState.SPEAKING,
            CallState.CLOSING,
            CallState.HANGUP,
            CallState.LOGGED,
        ]
        for s in required:
            assert s in states, f"Missing state: {s}"
        assert agent.sm.state == CallState.IDLE

    def test_transcript_contains_both_speakers(self):
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert "Agent:" in result["transcript"]
        assert "Prospect:" in result["transcript"]

    def test_greeting_includes_contact_name(self):
        agent = self._make_agent()
        contact = self._make_contact(name="Ahmed")
        result = self._run(agent, contact)

        assert "Ahmed" in result["transcript"]

    def test_audio_bridge_started(self):
        agent = self._make_agent()
        contact = self._make_contact()
        self._run(agent, contact)

        self.audio_bridge.start.assert_called_once()

    def test_hangup_called_on_cleanup(self):
        agent = self._make_agent()
        contact = self._make_contact()
        self._run(agent, contact)

        self.adb.hang_up.assert_called_once()

    def test_smoke_many_turns(self):
        self.config["max_turns"] = 5
        agent = self._make_agent()
        contact = self._make_contact()
        result = self._run(agent, contact)

        assert result["answered"] is True
        assert result["outcome"] == "completed"
        assert agent.sm.state == CallState.IDLE


if __name__ == "__main__":
    t = TestCallAgent()
    total = 0
    passed = 0
    failures = []

    for name in sorted(dir(t)):
        if name.startswith("test_"):
            t.setup_method()
            total += 1
            try:
                getattr(t, name)()
                print(f"  \u2713 {name}")
                passed += 1
            except Exception as e:
                import traceback

                print(f"  \u2717 {name}: {e}")
                failures.append(name)

    print(f"\n{passed}/{total} tests passed")
    if failures:
        print(f"Failed: {', '.join(failures)}")
    import sys

    sys.exit(0 if passed == total else 1)
