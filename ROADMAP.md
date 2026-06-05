# Implementation Roadmap

## Phase Overview

| Phase | Name | Duration Estimate | Dependency |
|-------|------|-----------------|------------|
| 0 | Foundation (DONE) | — | — |
| 1 | Call Loop Core | 2-3 sessions | Phase 0 |
| 2 | Audio Bridge | 3-5 sessions | Phase 1 |
| 3 | Voice Pipeline | 2-3 sessions | Phase 2 |
| 4 | AI Agent | 2-3 sessions | Phase 3 |
| 5 | Data & Persistence | 1 session | Phase 4 |
| 6 | Dashboard & Polish | 2 sessions | Phase 5 |

---

## Phase 0: Foundation ✅ DONE

**Status:** Complete on `fix/sim-selection` branch

### What was built:
- `phone/adb_controller.py` — ADB-based phone control (call, hangup, SIM select, call state)
- `call_helper/` — Java APK for SIM-aware call placement + hangup
- `config.py` / `.env` — Centralized configuration
- `test_adb.py` — Integration test for call flow
- `test_setup.py` — Environment verification

### Key outcomes:
- ✅ Outbound calls placed reliably with correct SIM selection
- ✅ Dual-SIM support (PhoneAccountHandle by slot index)
- ✅ Permission handling (runtime + pm grant fallback)
- ✅ Call state detection (telephony.registry)

### Known limitations carried forward:
- Hangup reflection may fail on newer Android → force-stop fallback
- Screen unlock coordinates are device-specific → needs config
- Mute/unmute is a toggle (no state) → needs fix
- `pure-python-adb` in requirements but unused → remove

---

## Phase 1: Call Loop Core

**Goal:** Build the main orchestration loop that can dial a number, detect call progress, and clean up.

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `main.py` | CREATE | CLI entry point: `python main.py --contacts contacts.csv --slot 1` |
| `phone/call_monitor.py` | IMPLEMENT | Real-time call state observer with event callbacks |
| `phone/adb_controller.py` | MODIFY | Fix mute/unmute (state tracking), make screen unlock coords configurable |

### Detailed tasks:

#### 1.1 `main.py` — Orchestrator
- Parse CLI args: `--contacts`, `--slot`, `--max-calls`, `--cooldown-minutes`
- Load contacts from CSV
- Loop: pick next contact → call → wait for answer → run conversation → hangup → log
- Handle Ctrl+C gracefully (hangup active call, restore SIM setting)
- Rate limiting: wait between calls, respect daily max

#### 1.2 `phone/call_monitor.py` — Event-driven call state
```python
class CallMonitor:
    def wait_for_answer(self, timeout=30) -> bool  # blocks until offhook
    def wait_for_hangup(self, timeout=300) -> int   # blocks until idle, returns duration
    def detect_voicemail(self, initial_silence_sec=3) -> bool  # heuristic
    def on_state_change(callback)  # register callback for state transitions
```
- Poll `telephony.registry` on background thread
- Emit events: `answered`, `hangup`, `timeout`, `voicemail`
- Integrate with `ADBController`

#### 1.3 Fix `adb_controller.py` issues
- **Mute/unmute:** Track state, use KEYCODE_0 (or separate keycodes if available) — or just avoid toggling
- **Screen unlock coords:** Add config option `UNLOCK_SWIPE_START/END` 
- **Remove `pure-python-adb` from requirements.txt** (unused)
- **Add `debug_call_state` improvement:** Show per-phone call state (phone id 0 vs 1)

### Acceptance criteria:
- `python main.py --contacts data/contacts.csv --slot 1 --dry-run` shows which contacts would be called
- `python main.py --single +213XXXXXXXX` dials, detects answer, waits, hangs up
- Graceful Ctrl+C during a call hangs up and restores SIM
- Call monitor can distinguish ringing → answered → idle transitions

---

## Phase 2: Audio Bridge

**Goal:** Establish bidirectional real-time audio between the PC and the phone call.

**This is the hardest phase — requires research and experimentation.**

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `phone/audio_bridge.py` | CREATE | Bidirectional audio streaming over ADB |
| `call_helper/src/.../AudioBridge.java` | CREATE | Android service for audio capture/playback |

### Approach to evaluate:

**Option A: ADB Forward + Socket (recommended first try)**
1. Push a small Java service to the phone that captures `AudioRecord` with `MediaRecorder.AudioSource.VOICE_DOWNLINK` (or `VOICE_UPLINK`, or `VOICE_CALL`)
2. Stream PCM chunks over TCP socket via `adb forward tcp:port tcp:port`
3. On PC side: receive audio → pipe to whisper; send TTS audio → pipe to phone's `AudioTrack`

**Risk:** `VOICE_DOWNLINK`/`VOICE_UPLINK` sources require `android.permission.CAPTURE_AUDIO_OUTPUT` which is signature|privileged — may not work on non-rooted device.

**Option B: Speakerphone + PC Mic**
1. Put phone on speakerphone
2. PC microphone captures prospect's voice
3. PC speaker plays AI response
4. Quality will be poor (echo, background noise)

**Option C: Bluetooth SCO**
1. Pair phone with PC over Bluetooth
2. Use Bluetooth SCO (Synchronous Connection Oriented) for call audio
3. Requires Bluetooth HFP profile support on PC

**Option D: USB Audio Class**
1. Android supports USB audio gadgets
2. Would need kernel support on the phone — unlikely on stock ROM

### Detailed tasks:

#### 2.1 Research call audio capture methods
- Test `AudioRecord` with `VOICE_DOWNLINK` on the target device
- Test if `CAPTURE_AUDIO_OUTPUT` can be granted via `pm grant` or root
- Check if `MediaProjection` audio capture works (API 29+)
- Fallback plan: just use speakerphone + PC mic

#### 2.2 Implement chosen approach
- Create audio capture service (Java/Kotlin APK or shell script using `tinycap`/`aplay`)
- Stream audio over ADB forward tunnel
- Handle chunking, buffering, jitter

#### 2.3 Implement audio playback into call
- Create audio playback service
- Receive PCM chunks from PC, play via `AudioTrack` with `MODE_STREAM`

### Acceptance criteria:
- PC can capture 3+ seconds of call audio from the phone
- PC can play a WAV file into the live call
- Round-trip latency < 2 seconds
- Audio quality is intelligible (8kHz+ sample rate)

---

## Phase 3: Voice Pipeline

**Goal:** Implement STT (prospect speech → text) and TTS (AI response → speech).

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `voice/audio_utils.py` | IMPLEMENT | Resampling, VAD, normalization |
| `voice/stt.py` | IMPLEMENT | Whisper-based transcription |
| `voice/tts.py` | IMPLEMENT | Coqui TTS synthesis |

### Detailed tasks:

#### 3.1 `voice/audio_utils.py`
```python
def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray
def normalize(audio: np.ndarray) -> np.ndarray
def detect_silence(audio: np.ndarray, threshold_db=-40, min_silence_ms=500) -> list[tuple]
def split_on_silence(audio: np.ndarray) -> list[np.ndarray]  # for turn detection
def vad(audio: np.ndarray, sample_rate: int) -> bool  # is there speech?
```

#### 3.2 `voice/stt.py`
```python
class STTEngine:
    def __init__(self, model_size="base", device="cpu", compute_type="int8"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, language: str = None) -> str
    def transcribe_stream(self, audio_stream, on_partial: callable) -> str
    def detect_language(self, audio: np.ndarray) -> str  # detect prospect's language
```
- Support Arabic, French, English
- Streaming mode: send chunks as they arrive, get partial transcripts
- Language detection: first utterance → set language for rest of call

#### 3.3 `voice/tts.py`
```python
class TTSEngine:
    def __init__(self, model_name="tts_models/en/ljspeech/tacotron2-DDC"):
        self.model = TTS(model_name=model_name)

    def synthesize(self, text: str, language: str = "en") -> np.ndarray
    def synthesize_stream(self, text: str) -> Generator[np.ndarray]
    def set_voice(self, speaker_wav: str)  # for XTTS voice cloning
```
- Pre-load models for Arabic, French, English
- Cache common phrases (greetings, closings)
- Target: < 2s synthesis time for typical utterance (< 20 words)

### Acceptance criteria:
- STT transcribes a 5-second Arabic recording with < 30% WER
- STT transcribes a 5-second French recording
- STT transcribes a 5-second English recording
- TTS synthesizes "Hello, this is an AI assistant" in clear Arabic
- TTS synthesizes in French and English
- End-to-end: audio file in → transcript → TTS audio out in < 5 seconds

---

## Phase 4: AI Agent

**Goal:** Build the conversational AI that drives the call — listens, thinks, speaks.

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `ai/state_machine.py` | IMPLEMENT | Call state machine |
| `ai/prompt.py` | IMPLEMENT | System prompt templates |
| `ai/agent.py` | IMPLEMENT | Conversation loop / agent logic |

### Detailed tasks:

#### 4.1 `ai/state_machine.py`
```
States:
  IDLE → DIALING → RINGING → GREETING → LISTENING → THINKING → SPEAKING → LISTENING → ... → CLOSING → HANGUP → LOGGED → IDLE

Transitions:
  DIALING → RINGING        (call placed)
  RINGING → GREETING       (answered, human detected)
  RINGING → IDLE           (no answer / voicemail)
  GREETING → LISTENING     (AI stops speaking, starts listening)
  LISTENING → THINKING     (prospect stops speaking + silence timeout)
  THINKING → SPEAKING      (AI response ready)
  SPEAKING → LISTENING     (AI finishes speaking)
  SPEAKING → CLOSING       (call objective met or max turns reached)
  LISTENING → CLOSING      (prospect hung up)
  CLOSING → HANGUP         (AI says goodbye)
  any → IDLE               (error / timeout / manual abort)
```

#### 4.2 `ai/prompt.py`
```python
SYSTEM_PROMPT_TEMPLATE = """You are a cold caller for {company_name}.
Your value proposition: {value_prop}
Your objective: {call_objective}

Rules:
- Be natural and conversational, NOT robotic
- Speak in {language}
- Keep responses under 20 words
- Do NOT identify yourself as AI unless asked
- If prospect says "not interested", acknowledge and close politely
- If prospect asks to call later, ask for time and confirm
- After achieving objective, close naturally

Current call context:
- Prospect name: {prospect_name}
- Company: {prospect_company}
- Conversation history:
{conversation_history}

Generate ONLY the next response. No meta-commentary."""
```

#### 4.3 `ai/agent.py`
```python
class CallAgent:
    def __init__(self, config: dict):
        self.llm = Ollama(model=config["ollama_model"])
        self.stt = STTEngine(...)
        self.tts = TTSEngine(...)
        self.state_machine = StateMachine()
        self.conversation_history = []

    async def run_call(self, contact: dict) -> CallOutcome:
        # 1. DIAL
        # 2. WAIT_FOR_ANSWER
        # 3. GREETING (TTS)
        # 4. LOOP: listen → think → speak → listen...
        #     - VAD to detect when prospect stops
        #     - STT to transcribe
        #     - LLM to generate response
        #     - TTS to speak
        #     - Check for call objective met, max turns, objection
        # 5. CLOSING (TTS)
        # 6. HANGUP
        # 7. LOG outcome
```
- Integrate with `CallMonitor` for state events
- Integrate with `AudioBridge` for audio I/O
- Integrate with `STTEngine` and `TTSEngine`
- Handle edge cases: crossed speech (both talking at once), long pauses, dropped calls

### Acceptance criteria:
- Agent can complete a full call cycle: dial → greet → listen → think → speak → close → hangup
- Agent responds in the correct language (detected from prospect's first utterance)
- Agent can handle "not interested" objection gracefully
- Agent can qualify a lead (ask 1-2 questions, interpret answer)
- Conversation history is maintained and used for context

---

## Phase 5: Data & Persistence

**Goal:** Log calls, manage contacts, track outcomes.

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `data/database.py` | IMPLEMENT | SQLite call log |
| `data/contacts.csv` | CREATE SAMPLE | Sample contact list |

### Detailed tasks:

#### 5.1 `data/database.py`
```python
class CallDatabase:
    def log_call(self, contact_id, phone, duration, outcome, transcript_path)
    def get_call_history(self, contact_id) -> list[dict]
    def get_daily_call_count(self) -> int
    def get_contacts_to_call(self, cooldown_minutes=1440) -> list[dict]
    def update_contact(self, contact_id, **fields)
```

#### 5.2 Schema
```sql
CREATE TABLE calls (
    id INTEGER PRIMARY KEY,
    contact_id TEXT,
    phone TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_seconds INTEGER,
    outcome TEXT,  -- answered, no_answer, busy, voicemail, interested, not_interested, call_me_back
    transcript_path TEXT,
    sim_slot INTEGER
);

CREATE TABLE contacts (
    id TEXT PRIMARY KEY,
    name TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 5.3 Sample contacts.csv
```csv
name,phone,company,notes
Ahmed Benali,+213555123456,StartupX,CTO
Marie Dupont,+213777654321,TechCorp,Marketing Director
John Smith,+213661111222,GlobalInc,CEO
```

### Acceptance criteria:
- Calls are logged with outcome
- Contacts with recent calls (within cooldown) are skipped
- Daily call count is tracked and enforced
- CSV contacts auto-import to DB on first run

---

## Phase 6: Dashboard & Polish

**Goal:** Streamlit dashboard for monitoring and control, plus refinements.

### Files to create/modify:

| File | Action | What to implement |
|------|--------|-------------------|
| `ui/dashboard.py` | IMPLEMENT | Streamlit dashboard |
| Various | POLISH | Error handling, logging, configurability |

### Detailed tasks:

#### 6.1 Dashboard
```python
# streamlit run ui/dashboard.py
# - Real-time call status (state, duration, current speaker)
# - Live transcript being generated
# - Call log table with filters
# - Start/stop campaign button
# - Emergency stop / barge-in
# - SIM slot selector
```

#### 6.2 Polish items
- **Logging:** Replace `print()` with `logging` throughout, configurable log level
- **Error handling:** Graceful degradation if AI models fail to load
- **Configuration:** Support for `.env` overrides of all parameters
- **Signal handling:** Catch SIGINT/SIGTERM, clean shutdown
- **Device detection:** Auto-detect ADB device if only one connected

### Acceptance criteria:
- Dashboard shows live call state with < 1s refresh
- Campaign can be started/stopped from dashboard
- Call logs are browseable
- Emergency stop works within 2 seconds
- All Python modules use proper logging

---

## Appendix: Branch Strategy

```
main
  └── feature/helper-apk-call        ← Phase 0 (can merge to main)
       └── fix/sim-selection          ← Phase 0 fixes (can merge to main)

After Phase 0 merges to main:
main
  ├── phase/1-call-loop-core
  ├── phase/2-audio-bridge
  ├── phase/3-voice-pipeline
  ├── phase/4-ai-agent
  ├── phase/5-data-persistence
  └── phase/6-dashboard-polish
```

## Appendix: Testing Strategy

| Layer | Test Method | Tool |
|-------|------------|------|
| ADB controller | Manual integration test | `test_adb.py` |
| Call monitor | Manual with real call | `dumpsys` + assert |
| Audio bridge | Research/prototype first | Manual listening |
| STT | Unit test with pre-recorded audio | `pytest` + fixture WAVs |
| TTS | Unit test with reference sentences | `pytest` + audible check |
| AI agent | Simulated conversation replay | `pytest` with mock STT/TTS |
| Full system | End-to-end real call | Manual + dashboard |
