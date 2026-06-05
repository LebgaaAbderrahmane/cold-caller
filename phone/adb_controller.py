import subprocess
import time
import re
import os
from config import ADB_DEVICE_ID, SIM_SLOT


HELPER_PACKAGE = "com.coldcaller"
HELPER_ACTIVITY = "com.coldcaller.CallHelper"
HELPER_APK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "call_helper",
    "build",
    "CallHelper.apk",
)


class ADBController:
    def __init__(self):
        self.device_id = ADB_DEVICE_ID
        self.sim_slot = SIM_SLOT
        self._saved_voice_setting = None
        self._verify_connection()
        self._ensure_helper_apk_installed()

    def _run(self, command: list) -> str:
        full_cmd = ["adb"]
        if self.device_id:
            full_cmd += ["-s", self.device_id]
        full_cmd += command
        result = subprocess.run(full_cmd, capture_output=True, text=True)
        return result.stdout.strip()

    def _run_full(self, command: list) -> str:
        full_cmd = ["adb"]
        if self.device_id:
            full_cmd += ["-s", self.device_id]
        full_cmd += command
        result = subprocess.run(full_cmd, capture_output=True, text=True)
        return (result.stdout + result.stderr).strip()

    def _verify_connection(self):
        output = self._run(["devices"])
        lines = [l for l in output.split("\n")[1:] if l.strip()]
        if not lines:
            raise RuntimeError(
                "No ADB device found.\n"
                "   Check USB cable\n"
                "   Check USB Debugging is ON\n"
                "   Run: adb devices"
            )
        print(f"ADB connected: {lines[0]}")

    def _ensure_helper_apk_installed(self):
        installed = self._run(["shell", "pm", "list", "packages", HELPER_PACKAGE])
        if HELPER_PACKAGE in installed:
            return
        if not os.path.exists(HELPER_APK_PATH):
            raise RuntimeError(
                f"Helper APK not found at {HELPER_APK_PATH}\n"
                "   Run: cd call_helper && ./build.sh"
            )
        print("Installing call helper APK...")
        result = self._run_full(["install", "-r", "-g", HELPER_APK_PATH])
        if "Success" in result:
            print("   Helper APK installed")
        else:
            print(f"   Install issue: {result[:100]}")

    # ─────────────────────────────────────────
    # Dual-SIM support
    # ─────────────────────────────────────────

    def _get_voice_call_setting(self) -> str:
        return self._run(["shell", "settings", "get", "global", "multi_sim_voice_call"])

    def _set_voice_call_setting(self, value):
        self._run(
            ["shell", "settings", "put", "global", "multi_sim_voice_call", str(value)]
        )

    def _save_voice_call_setting(self):
        self._saved_voice_setting = self._get_voice_call_setting()
        print(f"   Current voice SIM setting: {self._saved_voice_setting}")

    def _restore_voice_call_setting(self):
        saved = self._saved_voice_setting
        if saved and saved not in ("null", "", "-1"):
            self._set_voice_call_setting(saved)
            print(f"   Restored voice SIM setting: {saved}")

    def _get_subscription_id_for_slot(self, slot: int) -> int:
        output = self._run(
            ["shell", "content", "query", "--uri", "content://telephony/siminfo/"]
        )
        if "Row:" in output:
            current_slot_id = None
            for line in output.split("\n"):
                line = line.strip()
                slot_match = (
                    re.search(r"slot_index\s*=\s*(\d+)", line, re.IGNORECASE)
                    or re.search(r"sim_id\s*=\s*(\d+)", line, re.IGNORECASE)
                    or re.search(r"card_id\s*=\s*(\d+)", line, re.IGNORECASE)
                )
                sub_match = re.search(
                    r"subscription_id\s*=\s*(\d+)", line, re.IGNORECASE
                ) or re.search(r"_id\s*=\s*(\d+)", line, re.IGNORECASE)
                if slot_match:
                    current_slot_id = int(slot_match.group(1))
                if current_slot_id == slot and sub_match:
                    return int(sub_match.group(1))
        return slot + 1

    def prepare_sim(self):
        current = self._get_voice_call_setting()
        self._saved_voice_setting = current
        sub_id = self._get_subscription_id_for_slot(self.sim_slot)
        print(f"   Current voice SIM: {current}")

        self._set_voice_call_setting(sub_id)
        time.sleep(0.5)
        new_val = self._get_voice_call_setting()
        if new_val != current and new_val not in ("null", "-1"):
            print(f"   Voice SIM set via settings: sub_id={sub_id}")
            return

        self._set_voice_call_setting(self.sim_slot)
        time.sleep(0.5)
        new_val = self._get_voice_call_setting()
        if new_val != current and new_val not in ("null", "-1"):
            print(f"   Voice SIM set via settings: slot={self.sim_slot}")
            return

        out = self._run(
            ["shell", "cmd", "phone", "set-default-slot", str(self.sim_slot)]
        )
        print(f"   cmd phone set-default-slot: '{out[:80]}'")

        out = self._run(["shell", "service", "call", "phone", "15", "i32", str(sub_id)])
        print(f"   service call phone 15: '{out[:80]}'")

        print(f"   SIM preparation done")

    # ─────────────────────────────────────────
    # Call control
    # ─────────────────────────────────────────

    def hang_up(self):
        result = self._run_full(["shell", "am", "start", "-a", "com.coldcaller.HANGUP"])
        time.sleep(2)
        if "Error" not in result and self.get_call_state() == "idle":
            print("Call ended")
            return

        print("   Helper hangup failed, trying force-stop dialer...")
        for pkg in [
            "com.android.dialer",
            "com.android.incallui",
            "com.android.phone",
            "com.google.android.dialer",
            "com.android.server.telecom",
        ]:
            self._run(["shell", "am", "force-stop", pkg])
        time.sleep(1)
        if self.get_call_state() == "idle":
            print("Call ended via force-stop")
            return

        print("   Trying airplane mode toggle...")
        self._run(["shell", "settings", "put", "global", "airplane_mode_on", "1"])
        self._run(
            ["shell", "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE"]
        )
        time.sleep(2)
        self._run(["shell", "settings", "put", "global", "airplane_mode_on", "0"])
        self._run(
            ["shell", "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE"]
        )
        time.sleep(5)
        if self.get_call_state() == "idle":
            print("Call ended via airplane mode")
        else:
            print("   Could not end call")

    def accept_call(self):
        self._run(["shell", "input", "keyevent", "5"])

    # ─────────────────────────────────────────
    # Call state detection
    # ─────────────────────────────────────────

    def get_call_state(self) -> str:
        output = self._run(["shell", "dumpsys", "telephony.registry"])
        states = set()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("mCallState="):
                try:
                    states.add(int(line.split("=")[1].strip()))
                except Exception:
                    pass
        if 2 in states:
            return "ringing"
        if 1 in states:
            return "offhook"

        tel = self._run(["shell", "dumpsys", "telecom"])
        for line in tel.split("\n"):
            ls = line.strip()
            if "CallState" in ls and "ACTIVE" in ls:
                return "offhook"
            if "CallState" in ls and "RINGING" in ls:
                return "ringing"
            if "CallState" in ls and "DIALING" in ls:
                return "ringing"
        return "idle"

    # ─────────────────────────────────────────
    # Making calls
    # ─────────────────────────────────────────

    def _launch_helper_call(self, phone_number: str):
        return self._run_full(
            [
                "shell",
                "am",
                "start",
                "-a",
                "com.coldcaller.CALL",
                "--es",
                "android.intent.extra.PHONE_NUMBER",
                phone_number,
                "--ei",
                "sim_slot",
                str(self.sim_slot),
            ]
        )

    def _wait_for_call_register(self, timeout: int = 15) -> bool:
        for _ in range(timeout):
            time.sleep(1)
            state = self.get_call_state()
            if state != "idle":
                print(f"   Call state: {state}")
                return True
        return False

    def make_call(self, phone_number: str):
        print(f"Calling {phone_number} (SIM slot {self.sim_slot})...")
        self.wake_screen()
        self.unlock_screen()
        time.sleep(1)

        self.prepare_sim()

        try:
            for attempt in range(3):
                output = self._launch_helper_call(phone_number)
                print(f"   Helper APK (attempt {attempt + 1}): '{output[:80]}'")

                if self._wait_for_call_register(10):
                    return

                if attempt == 0:
                    print("   Permission review may be in progress...")

            print("   Call did not register")
        finally:
            self._restore_voice_call_setting()

    # ─────────────────────────────────────────
    # Wait for answer / call end
    # ─────────────────────────────────────────

    def wait_for_answer(self, timeout: int = 40) -> bool:
        print("Waiting for answer...")
        start = time.time()
        last_state = None
        saw_ringing = False

        print("   Phase 1: waiting for dialer to register...")
        while time.time() - start < 10:
            state = self.get_call_state()
            if state != "idle":
                print(f"   Dialer registered: {state}")
                break
            time.sleep(0.5)
        else:
            print("   Dialer never registered")
            return False

        print("   Phase 2: waiting for answer...")
        while time.time() - start < timeout:
            state = self.get_call_state()
            if state != last_state:
                print(f"   {last_state} -> {state}")
                last_state = state
            if state == "ringing":
                saw_ringing = True
            elif state == "offhook":
                print("Call answered!")
                return True
            elif state == "idle" and saw_ringing:
                print("Not answered / hung up")
                return False
            time.sleep(1)

        print("Timeout - hanging up")
        self.hang_up()
        return False

    def wait_for_call_end(self, max_duration: int = 300) -> int:
        start = time.time()
        while time.time() - start < max_duration:
            if self.get_call_state() == "idle":
                break
            time.sleep(1)
        return int(time.time() - start)

    # ─────────────────────────────────────────
    # Volume control
    # ─────────────────────────────────────────

    def set_call_volume(self, level: int = 15):
        self._run(["shell", "media", "volume", "--stream", "0", "--set", str(level)])

    def set_media_volume(self, level: int = 15):
        self._run(["shell", "media", "volume", "--stream", "3", "--set", str(level)])

    def mute_microphone(self):
        self._run(["shell", "input", "keyevent", "164"])

    def unmute_microphone(self):
        self._run(["shell", "input", "keyevent", "164"])

    # ─────────────────────────────────────────
    # Audio file playback
    # ─────────────────────────────────────────

    def push_and_play(self, local_audio_path: str):
        remote_path = "/sdcard/ai_response.wav"
        self._run(["push", local_audio_path, remote_path])
        self._run(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                f"file://{remote_path}",
                "-t",
                "audio/wav",
                "--activity-brought-to-front",
            ]
        )

    def play_audio_via_speakerphone(self, local_audio_path: str):
        remote_path = "/sdcard/ai_response.wav"
        self._run(["push", local_audio_path, remote_path])
        self._run(["shell", "service", "call", "phone", "8"])
        self._run(
            [
                "shell",
                f"aplay {remote_path} 2>/dev/null || "
                f"toybox cat {remote_path} > /dev/snd/pcmC0D0p",
            ]
        )

    # ─────────────────────────────────────────
    # Screen control
    # ─────────────────────────────────────────

    def wake_screen(self):
        self._run(["shell", "input", "keyevent", "224"])
        time.sleep(0.5)

    def unlock_screen(self):
        self.wake_screen()
        self._run(["shell", "input", "swipe", "540", "1800", "540", "900"])

    def get_screen_state(self) -> str:
        output = self._run(["shell", "dumpsys", "power"])
        return "on" if "mWakefulness=Awake" in output else "off"

    # ─────────────────────────────────────────
    # Debugging
    # ─────────────────────────────────────────

    def debug_call_state(self):
        print("\n=== telephony.registry ===")
        out1 = self._run(["shell", "dumpsys", "telephony.registry"])
        for line in out1.split("\n"):
            if any(k in line.lower() for k in ["call", "state", "offhook", "ring"]):
                print(f"  {line.strip()}")

        print("\n=== dumpsys phone ===")
        out2 = self._run(["shell", "dumpsys", "phone"])
        for line in out2.split("\n"):
            if any(k in line.lower() for k in ["call", "state", "offhook", "ring"]):
                print(f"  {line.strip()}")

    def debug_call_state_raw(self):
        output = self._run(["shell", "dumpsys", "telephony.registry"])
        print("\n=== RAW TELEPHONY STATE ===")
        for line in output.split("\n"):
            line = line.strip()
            if any(
                k in line
                for k in [
                    "mCallState",
                    "mForeground",
                    "mRinging",
                    "mBackground",
                    "mPrecise",
                ]
            ):
                print(f"  {line}")
        print("===========================")
