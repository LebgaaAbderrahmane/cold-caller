from dotenv import load_dotenv
import os

load_dotenv()

# Company
COMPANY_NAME = os.getenv("COMPANY_NAME", "YourStartup")
COMPANY_VALUE_PROP = os.getenv("COMPANY_VALUE_PROP", "helping startups grow faster")

# Audio
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 16000))
LISTEN_DURATION = int(os.getenv("LISTEN_DURATION", 6))

# AI
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# ADB
ADB_DEVICE_ID = os.getenv("ADB_DEVICE_ID", "f5cc454f0512")