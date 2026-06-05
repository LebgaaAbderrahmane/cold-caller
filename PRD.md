# PRD: Cold Caller — AI-Powered Automated Outbound Calling

## 1. Product Overview

An AI-powered automated calling system that makes outbound sales/outreach calls using a **dual-SIM Android phone** as the telco interface. The system orchestrates call placement, real-time conversation with a prospect (STT → LLM → TTS), audio routing over ADB, and call logging.

**Core value proposition:** Replace human cold callers with an AI agent that dials, converses, qualifies, and logs — using commodity Android hardware and local AI models.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           main.py (Orchestrator)                            │
│   Manages the call loop: dial → converse (STT→LLM→TTS) → hangup → log      │
└───┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────┘
    │          │          │          │          │          │          │
    ▼          ▼          ▼          ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ config │ │  ai/   │ │ voice/ │ │ phone/ │ │ phone/ │ │ phone/ │ │ data/  │
│  .py   │ │ agent  │ │  stt   │ │adb_ctrl│ │ call_  │ │ audio_ │ │  db    │
│        │ │ prompt │ │  tts   │ │ (done) │ │ monitor│ │ bridge │ │contacts│
│        │ │   sm   │ │ audio_ │ │        │ │        │ │        │ │        │
│        │ │        │ │ utils  │ │        │ │        │ │        │ │        │
├────────┤ ├────────┤ ├────────┤ ├────────┤ ├────────┤ ├────────┤ ├────────┤
│  .env  │ │ Ollama │ │Whisper │ │ ADB    │ │ dumpsys│ │ADB fwd │ │ SQLite │
│        │ │(local) │ │(local) │ │ CLI    │ │ events │ │socket  │ │  CSV   │
└────────┘ └────────┘ └────────┘ └───┬────┘ └────────┘ └───┬────┘ └────────┘
                                     │                      │
                                     ▼                      ▼
                            ┌──────────────────┐   ┌──────────────────┐
                            │ Android Device   │   │ Audio Stream     │
                            │ ┌─────────────┐  │   │ (WAV via ADB     │
                            │ │CallHelper.apk│  │   │  forward/socket) │
                            │ └─────────────┘  │   └──────────────────┘
                            └──────────────────┘
```

---

## 3. Functional Requirements

### 3.1 Phone Control Layer (DONE)

| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| PHONE-01 | Initiate outbound calls via ADB | ✅ DONE | Via CallHelper APK + `am start` |
| PHONE-02 | SIM selection on dual-SIM phones | ✅ DONE | PhoneAccountHandle by slot index |
| PHONE-03 | Detect call state (idle/ringing/offhook) | ✅ DONE | `dumpsys telephony.registry` |
| PHONE-04 | Hang up active calls | ⚠️ PARTIAL | APK reflection + force-stop + airplane mode fallback; reflection may fail on newer Android |
| PHONE-05 | Accept incoming calls | ✅ DONE | `input keyevent 5` |
| PHONE-06 | Wake & unlock screen | ✅ DONE | Swipe coordinates hard-coded |
| PHONE-07 | Set call/media volume | ✅ DONE | `media volume` command |

### 3.2 Audio Bridge (TODO — CRITICAL)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| AUDIO-01 | Capture call audio from phone to PC | P0 | ADB forward + socket or `screencap`-like audio capture |
| AUDIO-02 | Play audio from PC into the call | P0 | ADB push + aplay or audio sink |
| AUDIO-03 | Real-time bidirectional streaming (low-latency) | P0 | Chunked WAV over ADB tunnel |
| AUDIO-04 | Echo cancellation (phone mic feeding back TTS) | P1 | Detect and suppress own TTS playback |

**Challenge:** Android does not expose call audio over ADB. Approaches to evaluate:
- ADB forward TCP socket + custom audio service on device (requires another APK)
- Audio Loopback via `AudioRecord` with `VOICE_DOWNLINK` source (may need root or system app)
- Speakerphone + PC mic (worst case, poor quality)
- MediaProjection API for audio capture (API 29+, system alert window)

**Current fallback:** `push_and_play()` pushes a WAV and opens it via `ACTION_VIEW` intent — not suitable for live conversation.

### 3.3 Speech-to-Text (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| STT-01 | Transcribe captured call audio in real-time | P0 | Stream audio chunks → whisper |
| STT-02 | Language: Arabic + French + English | P0 | Whisper large-v3 supports all three |
| STT-03 | Silence/VAD detection for turn-taking | P1 | Don't transcribe silence |
| STT-04 | Speaker diarization (who said what) | P2 | Optional for conversation history |

**Implementation:** `faster-whisper` with model `large-v3` (or `base` for speed). Run inference on PC GPU/CPU.

### 3.4 Text-to-Speech (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| TTS-01 | Synthesize natural-sounding speech from AI response | P0 | Coqui TTS |
| TTS-02 | Language matching (Arabic/French/English) | P0 | Match prospect's language |
| TTS-03 | Low latency (< 2s from text to playback) | P1 | Streaming TTS if possible |
| TTS-04 | Voice customization (warmth, pace) | P2 | Coqui fine-tuning |

**Implementation:** Coqui TTS (`TTS` package). Models: `tts_models/ar/...` for Arabic, `tts_models/fr/...` for French, `tts_models/en/...` for English.

### 3.5 AI Conversation Agent (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| AI-01 | Maintain conversation state machine | P0 | IDLE → DIALING → GREETING → LISTENING → SPEAKING → ... → ENDED |
| AI-02 | Generate context-aware responses via Ollama | P0 | LLM prompt with company info + conversation history |
| AI-03 | Follow a call script / objective | P0 | System prompt defines goal (qualify, schedule demo, etc.) |
| AI-04 | Handle common objections gracefully | P1 | Prompt engineering |
| AI-05 | Detect human vs voicemail / answering machine | P1 | Duration + silence pattern analysis |
| AI-06 | Decide to persist or hangup based on call outcome | P1 | LLM classification of conversation |

**Implementation:** Ollama with llama3 (or mistral, qwen, etc.). System prompt template in `ai/prompt.py`. State machine in `ai/state_machine.py`. Conversation loop in `ai/agent.py`.

### 3.6 Call Monitoring (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| MON-01 | Detect when a call is answered (human) | P0 | Combine mCallState + voice activity |
| MON-02 | Detect when prospect stops speaking (turn end) | P0 | Silence duration threshold |
| MON-03 | Detect call disconnection (both sides) | P0 | mCallState → idle |
| MON-04 | Voicemail detection | P1 | Short utterance + long silence pattern |

### 3.7 Data Layer (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| DATA-01 | Load contacts from CSV | P0 | `data/contacts.csv` |
| DATA-02 | Log call outcomes (answered, interested, not interested, etc.) | P0 | SQLite via `data/database.py` |
| DATA-03 | Track call history per contact | P1 | |
| DATA-04 | Daily call limits / rate limiting | P1 | Don't get flagged as spam |
| DATA-05 | Skip contacts called recently | P1 | Configurable cooldown period |

### 3.8 Dashboard UI (TODO)

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| UI-01 | Real-time call status display | P1 | Streamlit dashboard |
| UI-02 | Start/stop calling campaign | P1 | |
| UI-03 | View call logs and outcomes | P2 | |
| UI-04 | Override / barge-in during live call | P2 | Emergency stop or take over |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target |
|----|------------|--------|
| NFR-01 | End-to-end latency (prospect speaks → AI replies) | < 5 seconds |
| NFR-02 | Call quality | Prospect should not notice it's an AI |
| NFR-03 | Fully offline (no cloud dependency) | All models run locally |
| NFR-04 | Single concurrent call | 1 call at a time |
| NFR-05 | Hot-swappable LLM | Ollama supports model switching |

---

## 5. Project Structure

```
cold-caller/
├── main.py                    # Orchestrator entry point
├── config.py                  # Central config (from .env)
├── .env                       # Runtime secrets/settings
├── requirements.txt           # Python dependencies
│
├── ai/
│   ├── agent.py               # Conversation loop / agent logic
│   ├── prompt.py              # System prompt templates
│   └── state_machine.py       # Call state machine
│
├── phone/
│   ├── adb_controller.py      # ADB phone control (DONE)
│   ├── audio_bridge.py        # Real-time audio streaming
│   └── call_monitor.py        # Call event detection
│
├── voice/
│   ├── stt.py                 # Speech-to-text (whisper)
│   ├── tts.py                 # Text-to-speech (Coqui)
│   └── audio_utils.py         # Audio processing utilities
│
├── data/
│   ├── contacts.csv           # Contact list
│   └── database.py            # Call log DB
│
├── ui/
│   └── dashboard.py           # Streamlit dashboard
│
├── call_helper/               # Android helper APK
│   ├── build.sh
│   ├── AndroidManifest.xml
│   └── src/com/coldcaller/
│       └── CallHelper.java
│
├── test_adb.py                # ADB integration test
├── test_setup.py              # Environment verification
└── PRD.md                     # This file
```

---

## 6. Dependencies & Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Phone control | ADB CLI + Java APK | Only way to place calls with SIM selection on locked-down ROMs |
| Audio bridge | ADB forward + TCP socket / custom APK | No direct call audio API from ADB |
| STT | faster-whisper (large-v3) | Best local model, supports Arabic+French+English |
| TTS | Coqui TTS (XTTSv2) | Natural voice, multi-language |
| LLM | Ollama (llama3 / mistral / qwen2.5) | Local, fast, good Arabic |
| UI | Streamlit | Rapid prototyping, real-time updates |
| DB | SQLite | Simple, no server needed |
| Contacts | CSV | Easy to import/export |

---

## 7. Known Device Constraints

- **Phone:** Tecno/Infinix/itel, Android ~13 (API 33), MTK chipset
- **ADB device ID:** `f5cc454f0512`
- **SIM 1:** slot=0, subId=1 (Djezzy)
- **SIM 2:** slot=1, subId=24 (Djezzy)
- **SIM selection:** Only works via `TelecomManager.placeCall()` with matching `PhoneAccountHandle`; `SubscriptionManager.setDefaultVoiceSubId()` blocked, `settings put multi_sim_voice_call` blocked, `service call phone 15` no-op
- **PhoneAccountHandles:** SORT_ORDER extras determine slot order (confirmed via MTK ROM)
- **Call audio capture:** Requires investigation — no known working method on non-rooted device
- **Screen unlock:** Coordinates hard-coded for this device's resolution
