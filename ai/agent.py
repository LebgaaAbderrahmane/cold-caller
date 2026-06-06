import queue
import time
from typing import Optional

import numpy as np
import ollama

from phone.adb_controller import ADBController
from phone.audio_bridge import AudioBridge
from phone.call_monitor import CallMonitor
from voice.audio_utils import SAMPLE_RATE, audio_to_float, vad
from voice.stt import STTEngine
from voice.tts import TTSEngine
from .prompt import build_closing, build_greeting, build_system_prompt
from .state_machine import CallState, CallStateMachine


class CallAgent:
    def __init__(
        self,
        config: dict,
        adb: ADBController,
        monitor: CallMonitor,
        audio_bridge: AudioBridge,
        stt: STTEngine,
        tts: TTSEngine,
    ):
        self.config = config
        self.adb = adb
        self.monitor = monitor
        self.audio_bridge = audio_bridge
        self.stt = stt
        self.tts = tts
        self.sm = CallStateMachine()
        self.conversation_history: list[tuple[str, str]] = []
        self._audio_queue: queue.Queue = queue.Queue()
        self._detected_language: Optional[str] = None

        self.agent_name = config.get("agent_name", "Alex")
        self.company_name = config.get("company_name", "YourStartup")
        self.value_prop = config.get("value_prop", "helping businesses grow")
        self.call_objective = config.get("call_objective", "qualify the lead")
        self.ollama_model = config.get("ollama_model", "llama3")
        self.max_turns = int(config.get("max_turns", 10))
        self.silence_timeout = 1.5

        self._objection_keywords = [
            "not interested",
            "stop calling",
            "don't call",
            "take me off",
            "not now",
            "busy",
            "no thanks",
            "leave me alone",
            "unsubscribe",
            "stop",
            "never mind",
        ]

    def run_call(self, contact) -> dict:
        outcome = {
            "contact": contact,
            "answered": False,
            "duration": None,
            "outcome": "unknown",
            "error": None,
            "transcript": None,
        }

        try:
            self.audio_bridge.on_audio(self._on_audio_chunk)
            self.audio_bridge.start()

            self.sm.transition(CallState.DIALING)
            self.adb.make_call(contact.phone)

            self.sm.transition(CallState.RINGING)
            if not self._wait_for_answer_audio():
                outcome["outcome"] = "no_answer"
                self.adb.hang_up()
                return outcome

            outcome["answered"] = True
            outcome["duration"] = self.monitor.get_call_duration()
            time.sleep(0.3)

            detected_lang = "en"
            self.sm.transition(CallState.GREETING)
            greeting = build_greeting(
                name=contact.name or "",
                agent_name=self.agent_name,
                company=self.company_name,
                value_prop=self.value_prop,
                language=detected_lang,
            )
            self._speak(greeting, language=detected_lang)
            self.conversation_history.append(("assistant", greeting))

            self.sm.transition(CallState.LISTENING)
            turn_count = 0
            call_ended = False

            while turn_count < self.max_turns and not call_ended:
                audio = self._listen_for_turn(max_duration=30)
                if audio is None:
                    call_ended = True
                    break

                self.sm.transition(CallState.THINKING)
                if self._detected_language is None:
                    try:
                        self._detected_language = self.stt.detect_language(audio)
                    except Exception:
                        self._detected_language = "en"

                transcript = self.stt.transcribe(
                    audio, language=self._detected_language
                )
                transcript = transcript.strip()
                if not transcript:
                    turn_count += 1
                    self.sm.transition(CallState.LISTENING)
                    continue

                self.conversation_history.append(("prospect", transcript))

                if self._check_objection(transcript):
                    response = self._build_closing_response(contact)
                    self._speak(response, language=self._detected_language)
                    self.conversation_history.append(("assistant", response))
                    outcome["outcome"] = "not_interested"
                    call_ended = True
                    break

                response = self._llm_generate(contact)
                if response is None:
                    call_ended = True
                    break

                self.sm.transition(CallState.SPEAKING)
                self._speak(response, language=self._detected_language)
                self.conversation_history.append(("assistant", response))
                turn_count += 1
                self.sm.transition(CallState.LISTENING)

            if not call_ended:
                outcome["outcome"] = "completed"
            elif outcome["outcome"] == "unknown":
                outcome["outcome"] = "completed"

            self.sm.transition(CallState.CLOSING)
            closing = build_closing(
                name=contact.name or "",
                language=self._detected_language or "en",
            )
            self._speak(closing, language=self._detected_language or "en")
            self.conversation_history.append(("assistant", closing))

            self.sm.transition(CallState.HANGUP)
            self.adb.hang_up()
            self.monitor.wait_for_hangup(timeout=10)

            outcome["transcript"] = self._format_transcript()

        except Exception as e:
            outcome["outcome"] = "error"
            outcome["error"] = str(e)
            try:
                self.adb.hang_up()
            except Exception:
                pass

        finally:
            try:
                self.sm.transition(CallState.LOGGED)
            except ValueError:
                pass
            self.sm.reset()
            self.conversation_history.clear()
            self._detected_language = None
            self._drain_queue()

        return outcome

    # ── Internal: audio ingestion ──────────────────────────────────

    # ── Internal: answer detection (MTK workaround) ──────────────

    def _wait_for_answer_audio(self, ring_timeout: float = 8) -> bool:
        """Wait for call answer.

        Normal path: detects offhook from telephony state.
        MTK workaround: MTK devices never report mCallState=1.
        After call rings for `ring_timeout` seconds, assume answered.
        The audio bridge will detect silence if nobody is there.
        """
        start = time.time()

        # Wait for ringing to register (max 15s)
        while time.time() < start + 15:
            state = self.monitor.get_state()
            if state == "ringing":
                break
            if state == "offhook":
                return True
            time.sleep(0.3)
        else:
            return False  # Never saw ringing

        # Wait for ring_timeout seconds for the person to pick up
        # On MTK, the call stays in "ringing" even when answered,
        # so we proceed to conversation regardless after the delay.
        ring_start = time.time()
        while time.time() < ring_start + ring_timeout:
            state = self.monitor.get_state()
            if state == "offhook":
                return True
            if state == "idle":
                return False
            time.sleep(0.3)

        # Proceed — call either answered (MTK) or still ringing (voicemail soon)
        return True

    def _on_audio_chunk(self, pcm_bytes: bytes):
        if self.sm.state == CallState.LISTENING:
            self._audio_queue.put(pcm_bytes)

    def _listen_for_turn(self, max_duration: float = 30) -> Optional[np.ndarray]:
        buffer = bytearray()
        last_speech_time = time.time()
        start_time = time.time()

        while time.time() - start_time < max_duration:
            if not self.monitor.is_in_call():
                return None

            received = False
            while True:
                try:
                    chunk = self._audio_queue.get_nowait()
                    buffer.extend(chunk)
                    received = True
                    audio_float = audio_to_float(np.frombuffer(chunk, dtype=np.int16))
                    if vad(audio_float, SAMPLE_RATE):
                        last_speech_time = time.time()
                except queue.Empty:
                    break

            if received and len(buffer) >= SAMPLE_RATE * 2:
                if time.time() - last_speech_time > self.silence_timeout:
                    break

            time.sleep(0.05)

        if len(buffer) < SAMPLE_RATE * 1:
            return None

        return np.frombuffer(bytes(buffer), dtype=np.int16)

    # ── Internal: speak ────────────────────────────────────────────

    def _speak(self, text: str, language: str = "en"):
        try:
            audio = self.tts.synthesize(text, language=language)
            if len(audio) > 0:
                self.adb.set_speakerphone(True)
                time.sleep(0.2)
                pcm = (audio * 32767).astype(np.int16).tobytes()
                self.audio_bridge.play_audio(pcm)
                time.sleep(0.3)
                self.adb.set_speakerphone(False)
        except Exception:
            pass

    # ── Internal: LLM ──────────────────────────────────────────────

    def _llm_generate(self, contact) -> Optional[str]:
        lang = self._detected_language or "en"
        full_prompt = build_system_prompt(
            company_name=self.company_name,
            value_prop=self.value_prop,
            call_objective=self.call_objective,
            language=lang,
            prospect_name=contact.name or "",
            prospect_company=contact.company or "",
            conversation_history=self.conversation_history,
        )
        try:
            resp = ollama.chat(
                model=self.ollama_model,
                messages=[{"role": "user", "content": full_prompt}],
                options={"num_predict": 150, "temperature": 0.7},
            )
            text = resp["message"]["content"].strip()
            return text if text else None
        except Exception:
            return None

    def _check_objection(self, transcript: str) -> bool:
        lower = transcript.lower()
        return any(kw in lower for kw in self._objection_keywords)

    def _build_closing_response(self, contact) -> str:
        name = contact.name or ""
        if self._detected_language == "ar":
            return f"شكرًا لك {name}، فهمت تمامًا. يوم سعيد!"
        elif self._detected_language == "fr":
            return f"Je comprends parfaitement {name}. Merci et bonne journée!"
        return f"I completely understand, {name}. Thank you and have a great day!"

    # ── Internal: helpers ──────────────────────────────────────────

    def _format_transcript(self) -> str:
        lines = []
        for speaker, text in self.conversation_history:
            prefix = "Agent" if speaker == "assistant" else "Prospect"
            lines.append(f"{prefix}: {text}")
        return "\n".join(lines)

    def _drain_queue(self):
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
