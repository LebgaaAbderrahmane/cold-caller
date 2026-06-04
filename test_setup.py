import sys

def check(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
    except Exception as e:
        print(f"  ❌ {name} — {e}")

print("\n🔍 Checking setup...\n")

check("faster-whisper",  lambda: __import__("faster_whisper"))
check("sounddevice",     lambda: __import__("sounddevice"))
check("soundfile",       lambda: __import__("soundfile"))
check("numpy",           lambda: __import__("numpy"))
check("pandas",          lambda: __import__("pandas"))
check("ollama",          lambda: __import__("ollama"))
check("dotenv",          lambda: __import__("dotenv"))
check("TTS (Coqui)",     lambda: __import__("TTS"))
check("ppadb (ADB)",     lambda: __import__("ppadb"))

print("\n🔍 Checking ADB connection...\n")
import subprocess
result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
lines = result.stdout.strip().split("\n")
devices = [l for l in lines[1:] if l.strip() and "device" in l]
if devices:
    print(f"  ✅ ADB — {devices[0]}")
else:
    print("  ❌ ADB — No device found. Check USB cable & USB Debugging")

print("\n🔍 Checking Ollama...\n")
import subprocess
result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
if "llama3" in result.stdout:
    print("  ✅ Ollama — llama3 model ready")
else:
    print("  ❌ Ollama — llama3 not found. Run: ollama pull llama3")

print("\n🏁 Done!\n")