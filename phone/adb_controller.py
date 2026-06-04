import subprocess
import time
from config import ADB_DEVICE_ID

class ADBController:
    def __init__(self):
        self.device_id = ADB_DEVICE_ID
        self._verify_connection()

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    def _run(self, command: list) -> str:
        """Run any ADB command and return output"""
        full_cmd = ["adb"]
        if self.device_id:
            full_cmd += ["-s", self.device_id]
        full_cmd += command

        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()

    def _verify_connection(self):
        """Check phone is connected on startup"""
        output = self._run(["devices"])
        lines = [l for l in output.split("\n")[1:] if l.strip()]

        if not lines:
            raise RuntimeError(
                "❌ No ADB device found.\n"
                "   → Check USB cable\n"
                "   → Check USB Debugging is ON\n"
                "   → Run: adb devices"
            )
        print(f"✅ ADB connected: {lines[0]}")

    # ─────────────────────────────────────────
    # Call control
    # ─────────────────────────────────────────


    def hang_up(self):
        """End the current call"""
        # Primary method: KeyEvent ENDCALL
        self._run(["shell", "input", "keyevent", "6"])
        time.sleep(1)

        # Backup: broadcast end call intent
        self._run([
            "shell", "am", "broadcast",
            "-a", "android.intent.action.PHONE_STATE"
        ])
        print("📵 Call ended")

    def accept_call(self):
        """Accept an incoming call"""
        self._run(["shell", "input", "keyevent", "5"])

    # ─────────────────────────────────────────
    # Call state detection
    # ─────────────────────────────────────────

    def get_call_state(self) -> str:
        """
        Calibrated for device f5cc454f0512.

        Observed states:
        mCallState=0, mForeground=0  → idle
        mCallState=2, mForeground=3  → dialing (outbound, ringing on other end)
        mCallState=2, mForeground=4  → alerting (their phone ringing)
        mCallState=2, mForeground=1  → offhook (answered, active call)
        """
        output = self._run(["shell", "dumpsys", "telephony.registry"])

        call_state = 0
        foreground_state = 0

        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("mCallState="):
                try:
                    call_state = int(line.split("=")[1].strip())
                except:
                    pass
            elif line.startswith("mForegroundCallState="):
                try:
                    foreground_state = int(line.split("=")[1].strip())
                except:
                    pass

        # Device-specific mapping
        if call_state == 0:
            return "idle"

        if call_state == 2:
            if foreground_state == 1:
                return "offhook"    # call answered and active
            elif foreground_state in [3, 4]:
                return "ringing"    # dialing / their phone ringing
            else:
                return "ringing"    # any other active state = still connecting

        return "idle"

    def debug_call_state_raw(self):
        """Print every relevant line from telephony registry"""
        output = self._run(["shell", "dumpsys", "telephony.registry"])
        print("\n=== RAW TELEPHONY STATE ===")
        for line in output.split("\n"):
            line = line.strip()
            if any(k in line for k in [
                "mCallState", "mForeground", "mRinging",
                "mBackground", "mPrecise"
            ]):
                print(f"  {line}")
        print("===========================\n")

    def make_call(self, phone_number: str):
        """Initiate outbound call via DIAL + tap"""
        print(f"📞 Calling {phone_number}...")
        self.wake_screen()
        self.unlock_screen()
        time.sleep(1)

        # Open dialer with number (no permission needed)
        result = self._run([
            "shell", "am", "start",
            "-a", "android.intent.action.DIAL",
            "-d", f"tel:{phone_number}"
        ])
        print(f"   ADB response: '{result}'")

        # Wait for dialer UI to fully open
        time.sleep(2)

        # Simulate pressing the green call button
        # Coordinates vary by phone — we'll find them below
        self._tap_call_button()
        time.sleep(1)

    def _tap_call_button(self):
        """
        Tap the green call button on the dialer screen.
        We'll find the exact coordinates for your device.
        """
        # First let's dump the UI to find the button
        ui_dump = self._run([
            "shell", "uiautomator", "dump", "/sdcard/ui.xml"
        ])
        self._run(["pull", "/sdcard/ui.xml", "/tmp/ui.xml"])

        # Try to find call button by content-desc
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse("/tmp/ui.xml")
            root = tree.getroot()

            call_keywords = ["call", "dial", "appel"]

            for node in root.iter("node"):
                desc = (node.get("content-desc") or "").lower()
                text = (node.get("text") or "").lower()
                cls  = (node.get("class") or "").lower()

                if any(k in desc or k in text for k in call_keywords):
                    bounds = node.get("bounds")  # e.g. [900,1800][1080,1950]
                    if bounds:
                        # Parse center coordinates
                        import re
                        nums = list(map(int, re.findall(r'\d+', bounds)))
                        if len(nums) == 4:
                            cx = (nums[0] + nums[2]) // 2
                            cy = (nums[1] + nums[3]) // 2
                            print(f"   🎯 Found call button at ({cx}, {cy}) — '{desc or text}'")
                            self._run(["shell", "input", "tap", "534", "2090"])
                            return

        except Exception as e:
            print(f"   ⚠️ UI parse failed: {e}")

        # Fallback: common call button positions
        print("   ⚠️ Call button not found in UI, trying common positions...")
        screen_info = self._run(["shell", "wm", "size"])
        print(f"   Screen: {screen_info}")

        # Try bottom-center (where call button usually is)
        try:
            import re
            nums = list(map(int, re.findall(r'\d+', screen_info)))
            if len(nums) == 2:
                w, h = nums
                cx = w // 2
                cy = int(h * 0.85)  # 85% down the screen
                print(f"   🎯 Tapping fallback position ({cx}, {cy})")
                self._run(["shell", "input", "tap", str(cx), str(cy)])
        except:
            # Hardcoded last resort
            self._run(["shell", "input", "tap", "540", "1800"])

    def wait_for_answer(self, timeout: int = 40) -> bool:
        """
        Wait until call is answered or ends.
        Returns True if answered, False if not answered.
        """
        print("⏳ Waiting for answer...")
        start = time.time()
        last_state = None
        saw_ringing = False

        # ── Phase 1: wait until we leave idle (call is registering) ──
        print("   ⏳ Phase 1: waiting for dialer to register...")
        while time.time() - start < 10:
            state = self.get_call_state()
            if state != "idle":
                print(f"   📶 Dialer registered: {state}")
                break
            time.sleep(0.5)
        else:
            print("   ❌ Dialer never registered — check CALL permission")
            return False

        # ── Phase 2: now watch for answer or end ──
        print("   ⏳ Phase 2: waiting for answer...")
        while time.time() - start < timeout:
            state = self.get_call_state()

            if state != last_state:
                print(f"   📶 {last_state} → {state}")
                last_state = state

            if state == "ringing":
                saw_ringing = True

            elif state == "offhook":
                print("✅ Call answered!")
                return True

            elif state == "idle" and saw_ringing:
                print("❌ Not answered / hung up")
                return False

            time.sleep(1)

        print("⏱ Timeout — hanging up")
        self.hang_up()
        return False

    def wait_for_call_end(self, max_duration: int = 300) -> int:
        """
        Wait until call ends naturally.
        Returns actual call duration in seconds.
        """
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
        """Set in-call volume (0-15)"""
        self._run([
            "shell", "media", "volume",
            "--stream", "0",   # STREAM_VOICE_CALL = 0
            "--set", str(level)
        ])

    def set_media_volume(self, level: int = 15):
        """Set media volume (0-15)"""
        self._run([
            "shell", "media", "volume",
            "--stream", "3",   # STREAM_MUSIC = 3
            "--set", str(level)
        ])

    def mute_microphone(self):
        self._run(["shell", "input", "keyevent", "164"])

    def unmute_microphone(self):
        self._run(["shell", "input", "keyevent", "164"])

    # ─────────────────────────────────────────
    # Audio file playback
    # ─────────────────────────────────────────

    def push_and_play(self, local_audio_path: str):
        """
        Push an audio file to phone and play it
        during the call (goes through speaker into mic)
        """
        remote_path = "/sdcard/ai_response.wav"

        # Copy file to phone
        self._run(["push", local_audio_path, remote_path])

        # Play it via media player
        self._run([
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", f"file://{remote_path}",
            "-t", "audio/wav",
            "--activity-brought-to-front"
        ])

    def play_audio_via_speakerphone(self, local_audio_path: str):
        """
        Enable speakerphone then play audio.
        More reliable for audio injection into calls.
        """
        remote_path = "/sdcard/ai_response.wav"

        # Push file
        self._run(["push", local_audio_path, remote_path])

        # Enable speakerphone
        self._run([
            "shell", "service", "call", "phone", "8"
        ])

        # Play via aplay if available on device
        self._run([
            "shell", f"aplay {remote_path} 2>/dev/null || "
                     f"toybox cat {remote_path} > /dev/snd/pcmC0D0p"
        ])

    # ─────────────────────────────────────────
    # Screen control
    # ─────────────────────────────────────────

    def wake_screen(self):
        """Wake phone screen if sleeping"""
        self._run(["shell", "input", "keyevent", "224"])
        time.sleep(0.5)

    def unlock_screen(self):
        """Swipe up to unlock (no PIN)"""
        self.wake_screen()
        self._run(["shell", "input", "swipe", "540", "1800", "540", "900"])

    def get_screen_state(self) -> str:
        """Returns 'on' or 'off'"""
        output = self._run(["shell", "dumpsys", "power"])
        if "mWakefulness=Awake" in output:
            return "on"
        return "off"

    def debug_call_state(self):
        """Print raw telephony output for debugging"""
        print("\n=== telephony.registry ===")
        out1 = self._run(["shell", "dumpsys", "telephony.registry"])
        # Print only relevant lines
        for line in out1.split("\n"):
            if any(k in line.lower() for k in ["call", "state", "offhook", "ring"]):
                print(f"  {line.strip()}")

        print("\n=== dumpsys phone ===")
        out2 = self._run(["shell", "dumpsys", "phone"])
        for line in out2.split("\n"):
            if any(k in line.lower() for k in ["call", "state", "offhook", "ring"]):
                print(f"  {line.strip()}")