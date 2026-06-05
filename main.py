#!/usr/bin/env python3
import argparse
import csv
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import (
    SIM_SLOT,
    OLLAMA_MODEL,
    WHISPER_MODEL,
    COMPANY_NAME,
    COMPANY_VALUE_PROP,
    CALL_OBJECTIVE,
    AGENT_NAME,
    MAX_TURNS,
)
from phone.adb_controller import ADBController
from phone.call_monitor import CallMonitor
from phone.audio_bridge import AudioBridge
from voice.stt import STTEngine
from voice.tts import TTSEngine
from ai.agent import CallAgent


@dataclass
class Contact:
    name: str
    phone: str
    company: str = ""
    notes: str = ""


@dataclass
class CallOutcome:
    contact: Contact
    timestamp: datetime = field(default_factory=datetime.now)
    duration: Optional[float] = None
    answered: bool = False
    outcome: str = "unknown"
    error: Optional[str] = None


_current_call = {"in_progress": False}


def load_contacts(path: str) -> list[Contact]:
    contacts = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            phone = row.get("phone", "").strip()
            if not name or not phone:
                continue
            contacts.append(
                Contact(
                    name=name,
                    phone=phone,
                    company=row.get("company", "").strip(),
                    notes=row.get("notes", "").strip(),
                )
            )
    return contacts


def call_contact(
    adb, monitor, audio_bridge, stt, tts, contact: Contact, agent_config: dict
) -> CallOutcome:
    outcome = CallOutcome(contact=contact)
    _current_call["in_progress"] = True

    try:
        agent = CallAgent(agent_config, adb, monitor, audio_bridge, stt, tts)
        result = agent.run_call(contact)

        outcome.answered = result.get("answered", False)
        outcome.duration = result.get("duration")
        outcome.outcome = result.get("outcome", "unknown")
        outcome.error = result.get("error")

        transcript = result.get("transcript")
        if transcript:
            ts = int(time.time())
            transcript_dir = "data/transcripts"
            os.makedirs(transcript_dir, exist_ok=True)
            path = os.path.join(transcript_dir, f"{contact.phone}_{ts}.txt")
            with open(path, "w") as f:
                f.write(transcript)
            print(f"   Transcript saved: {path}")
    except Exception as e:
        outcome.outcome = "error"
        outcome.error = str(e)
        print(f"   Error: {e}")
        try:
            adb.hang_up()
        except Exception:
            pass
    finally:
        _current_call["in_progress"] = False

    return outcome


def print_summary(outcomes: list[CallOutcome], start_time: float):
    elapsed = time.time() - start_time
    answered = sum(1 for o in outcomes if o.answered)
    errors = sum(1 for o in outcomes if o.outcome == "error")

    print("\n" + "=" * 50)
    print("CAMPAIGN SUMMARY")
    print("=" * 50)
    print(f"  Total calls:  {len(outcomes)}")
    print(f"  Answered:     {answered}")
    print(f"  No answer:    {len(outcomes) - answered - errors}")
    print(f"  Errors:       {errors}")
    print(f"  Duration:     {elapsed:.0f}s ({elapsed / 60:.1f}min)")
    if answered:
        total_duration = sum(o.duration or 0 for o in outcomes if o.answered)
        print(f"  Total talk:   {total_duration:.0f}s")
        print(f"  Avg talk:     {total_duration / answered:.0f}s")
    print("=" * 50)
    for o in outcomes:
        dur = f" ({o.duration:.0f}s)" if o.duration else ""
        err = f" — {o.error}" if o.error else ""
        print(f"  {o.contact.name:20s} {o.outcome:12s}{dur}{err}")


_cleanup_resources = []


def signal_handler(sig, frame):
    print("\n\nInterrupt received. Cleaning up...")
    for res in _cleanup_resources:
        try:
            res.stop()
        except Exception:
            pass
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Cold Caller — AI-Powered Automated Outbound Calling"
    )
    parser.add_argument("--contacts", type=str, help="CSV file with contacts")
    parser.add_argument("--single", type=str, help="Single phone number to call")
    parser.add_argument("--slot", type=int, default=None, help="SIM slot override")
    parser.add_argument(
        "--max-calls", type=int, default=0, help="Max calls (0 = unlimited)"
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=1440,
        help="Cooldown minutes between calls to same contact",
    )
    parser.add_argument(
        "--wait-between", type=int, default=30, help="Seconds between calls"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--daily-limit", type=int, default=50, help="Max calls per day")
    args = parser.parse_args()

    if not args.contacts and not args.single:
        parser.error("Provide --contacts or --single")

    signal.signal(signal.SIGINT, signal_handler)

    if args.single:
        contacts = [Contact(name="Unknown", phone=args.single)]
    else:
        if not os.path.exists(args.contacts):
            parser.error(f"Contacts file not found: {args.contacts}")
        contacts = load_contacts(args.contacts)
        if not contacts:
            print("No contacts found in CSV")
            return

    sim_slot = args.slot if args.slot is not None else SIM_SLOT
    print(f"Cold Caller — {len(contacts)} contact(s), SIM slot {sim_slot}")

    if args.dry_run:
        print("\nDRY RUN — no calls will be placed")
        for c in contacts:
            print(f"  Would call: {c.name:20s} {c.phone:15s}  [{c.company}]")
        return

    if args.max_calls > 0 and len(contacts) > args.max_calls:
        contacts = contacts[: args.max_calls]
        print(f"Limited to {args.max_calls} calls")

    print("\nInitializing ADB controller...")
    adb = ADBController()
    monitor = CallMonitor(adb)
    monitor.start()

    print("Initializing audio bridge...")
    audio_bridge = AudioBridge(adb)
    _cleanup_resources.append(audio_bridge)

    print("Loading STT engine...")
    stt = STTEngine(model_size=WHISPER_MODEL)

    print("Loading TTS engine...")
    tts = TTSEngine()

    agent_config = {
        "agent_name": AGENT_NAME,
        "company_name": COMPANY_NAME,
        "value_prop": COMPANY_VALUE_PROP,
        "call_objective": CALL_OBJECTIVE,
        "ollama_model": OLLAMA_MODEL,
        "max_turns": MAX_TURNS,
    }

    outcomes: list[CallOutcome] = []
    start_time = time.time()

    try:
        for i, contact in enumerate(contacts):
            print(
                f"\n[{i + 1}/{len(contacts)}] Calling {contact.name} <{contact.phone}>"
            )
            outcome = call_contact(
                adb, monitor, audio_bridge, stt, tts, contact, agent_config
            )
            outcomes.append(outcome)
            print(f"  Outcome: {outcome.outcome}")

            if i < len(contacts) - 1 and args.wait_between > 0:
                print(f"\n  Waiting {args.wait_between}s before next call...")
                time.sleep(args.wait_between)
    finally:
        monitor.stop()
        audio_bridge.stop()
        print_summary(outcomes, start_time)


if __name__ == "__main__":
    main()
