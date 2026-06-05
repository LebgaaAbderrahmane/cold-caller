import os
import numpy as np
from faster_whisper import WhisperModel

from .audio_utils import resample, audio_to_float, SAMPLE_RATE


class STTEngine:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        cache_dir: str = None,
    ):
        self.model_size = model_size
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir,
        )

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        language: str = None,
        **kwargs,
    ) -> str:
        audio_float = audio_to_float(audio)
        if sample_rate != SAMPLE_RATE:
            audio_float = resample(audio_float, sample_rate, SAMPLE_RATE)
        segments, info = self.model.transcribe(audio_float, language=language, **kwargs)
        text = " ".join(seg.text for seg in segments)
        return text.strip()

    def transcribe_file(self, path: str, language: str = None) -> str:
        import soundfile as sf

        audio, sr = sf.read(path)
        return self.transcribe(audio, sample_rate=sr, language=language)

    def detect_language(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        audio_float = audio_to_float(audio)
        if sample_rate != SAMPLE_RATE:
            audio_float = resample(audio_float, sample_rate, SAMPLE_RATE)
        segments, info = self.model.transcribe(audio_float, language=None)
        return info.language
