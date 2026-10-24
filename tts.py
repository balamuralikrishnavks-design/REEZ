"""REEZ voice output: a natural offline voice (Piper) with a Windows fallback."""

import io
import re
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

VOICE = "en_GB-cori-medium"
DEEPEN = 0.92  # below 1.0 = deeper and slower (try 0.88 for deeper), 1.0 = normal
MODEL = Path(__file__).parent / "voices" / (VOICE + ".onnx")

VOLUME = 1.0
_voice = None
_failed = False


def load():
    global _voice, _failed
    if _voice is None and not _failed:
        try:
            from piper import PiperVoice
            _voice = PiperVoice.load(str(MODEL))
        except Exception:
            _failed = True
    return _voice


def _clean(text):
    return " ".join(re.sub(r"[*#_`~|<>]", " ", text).split())


def _fallback(text):
    import pyttsx3
    engine = pyttsx3.init()
    for v in engine.getProperty("voices"):
        if any(name in v.name.lower() for name in ("zira", "heera", "female")):
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 160)
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def speak(text):
    text = _clean(text)
    if not text:
        return
    voice = load()
    if voice is None:
        _fallback(text)
        return
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        if hasattr(voice, "synthesize_wav"):
            voice.synthesize_wav(text, wf)
        else:
            voice.synthesize(text, wf)
    buf.seek(0)
    with wave.open(buf, "rb") as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    data = np.clip(data.astype(np.float32) * VOLUME, -32768, 32767).astype(np.int16)
    sd.play(data, samplerate=int(rate * DEEPEN))
    sd.wait()


def stop():
    try:
        sd.stop()
    except Exception:
        pass

