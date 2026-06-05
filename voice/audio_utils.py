import numpy as np

SAMPLE_RATE = 16000


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    ratio = target_sr / orig_sr
    new_len = max(1, int(len(audio) * ratio))
    return np.interp(
        np.linspace(0, len(audio) - 1, new_len),
        np.arange(len(audio)),
        audio,
    )


def normalize(audio: np.ndarray, target_dbfs: float = -3.0) -> np.ndarray:
    peak = np.max(np.abs(audio))
    if peak < 1e-10:
        return audio
    current_dbfs = 20 * np.log10(peak)
    gain = 10 ** ((target_dbfs - current_dbfs) / 20)
    return np.clip(audio * gain, -1.0, 1.0)


def audio_to_float(audio: np.ndarray) -> np.ndarray:
    if audio.dtype == np.float32 or audio.dtype == np.float64:
        return audio.astype(np.float32)
    if audio.dtype == np.int16:
        return (audio.astype(np.float32) / 32768.0).astype(np.float32)
    if audio.dtype == np.int32:
        return (audio.astype(np.float32) / 2147483648.0).astype(np.float32)
    return audio.astype(np.float32)


def audio_to_int16(audio: np.ndarray) -> np.ndarray:
    if audio.dtype == np.int16:
        return audio
    float_audio = audio.astype(np.float32)
    float_audio = np.clip(float_audio, -1.0, 1.0)
    return (float_audio * 32767.0).astype(np.int16)


def rms(audio: np.ndarray) -> float:
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def db_from_float(audio: np.ndarray) -> float:
    val = rms(audio)
    if val < 1e-10:
        return -100.0
    return float(20 * np.log10(val))


def detect_silence(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    threshold_db: float = -40,
    min_silence_ms: int = 300,
) -> list[tuple[int, int]]:
    frame_len = int(sample_rate * 0.02)
    hop_len = int(sample_rate * 0.01)
    silent_regions = []
    in_silence = False
    silence_start = 0

    for start in range(0, len(audio) - frame_len + 1, hop_len):
        frame = audio[start : start + frame_len]
        energy_db = db_from_float(frame)
        is_silent = energy_db < threshold_db

        if is_silent and not in_silence:
            silence_start = start
            in_silence = True
        elif not is_silent and in_silence:
            if start - silence_start >= min_silence_ms * sample_rate / 1000:
                silent_regions.append((silence_start, start))
            in_silence = False

    if in_silence and len(audio) - silence_start >= min_silence_ms * sample_rate / 1000:
        silent_regions.append((silence_start, len(audio)))

    return silent_regions


def vad(
    audio: np.ndarray, sample_rate: int = SAMPLE_RATE, threshold_db: float = -30
) -> bool:
    if len(audio) < sample_rate * 0.1:
        return False
    frame = audio[-int(sample_rate * 0.1) :]
    return db_from_float(frame) > threshold_db
