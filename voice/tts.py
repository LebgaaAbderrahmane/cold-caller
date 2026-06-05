import numpy as np

from .audio_utils import SAMPLE_RATE


class TTSEngine:
    """Multi-backend TTS engine.

    Backends tried in order:
      1. Piper (local, fast) — English, French
      2. edge-tts (cloud, free) — Arabic, fallback
    """

    def __init__(self, voice: str = None):
        self._piper = None
        self._piper_voice = voice
        self._voice_map = {
            "en": "en_US-lessac-medium",
            "fr": "fr_FR-mls-medium",
            "ar": None,  # Piper has no Arabic voice — uses edge-tts
        }

    def synthesize(self, text: str, language: str = "en") -> np.ndarray:
        if language == "ar" or self._piper is None:
            if self._try_load_piper(language):
                return self._synthesize_piper(text, language)
            return self._synthesize_edge(text, language)
        return self._synthesize_piper(text, language)

    def synthesize_to_file(self, text: str, path: str, language: str = "en"):
        import soundfile as sf

        audio = self.synthesize(text, language)
        sf.write(path, audio, SAMPLE_RATE)

    def _try_load_piper(self, language: str) -> bool:
        if self._piper is not None:
            return True
        voice_name = self._voice_map.get(language) or self._piper_voice
        if voice_name is None:
            return False
        try:
            from piper import PiperVoice
            import json
            import os

            # Find or download the voice model
            model_path = self._resolve_model(voice_name)
            if model_path is None:
                return False
            self._piper = PiperVoice.load(model_path, use_cuda=False)
            self._piper_voice = voice_name
            return True
        except Exception:
            return False

    def _resolve_model(self, voice_name: str) -> str | None:
        import os

        cache = os.path.expanduser("~/.local/share/piper-tts")
        model_file = os.path.join(cache, f"{voice_name}.onnx")
        config_file = os.path.join(cache, f"{voice_name}.json")

        if os.path.exists(model_file) and os.path.exists(config_file):
            return model_file

        # Try to auto-download
        try:
            from piper.download import find_voice, ensure_voice_exists

            url = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
            ensure_voice_exists(voice_name, [url], cache, cache)
            return os.path.join(cache, f"{voice_name}.onnx")
        except Exception:
            return None

    def _synthesize_piper(self, text: str, language: str) -> np.ndarray:
        if self._piper is None:
            return self._synthesize_edge(text, language)

        chunks = list(self._piper.synthesize(text))
        if not chunks:
            return np.array([], dtype=np.float32)
        audio = np.concatenate([c.audio_float_array for c in chunks])
        return audio

    def _synthesize_edge(self, text: str, language: str) -> np.ndarray:
        import asyncio
        import io
        import edge_tts

        voice_map = {
            "en": "en-US-JennyNeural",
            "fr": "fr-FR-DeniseNeural",
            "ar": "ar-DZ-IsmaelNeural",
        }
        voice = voice_map.get(language, "en-US-JennyNeural")

        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            return audio_data

        audio_bytes = asyncio.run(_run())

        import soundfile as sf

        buf = io.BytesIO(audio_bytes)
        data, sr = sf.read(buf)
        if sr != SAMPLE_RATE:
            from .audio_utils import resample

            data = resample(data, sr, SAMPLE_RATE)
        return data
