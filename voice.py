"""REEZ voice: listen (Whisper), understand, answer, speak."""

from collections import deque

import numpy as np
import pyttsx3
import sounddevice as sd
from faster_whisper import WhisperModel

import brain
import understanding

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.1

stt = WhisperModel("base.en", device="cpu", compute_type="int8")


def record(max_seconds=15, silence_seconds=1.0):
    """Record from the microphone until you stop talking. Returns audio or None."""
    block = int(SAMPLE_RATE * BLOCK_SECONDS)
    before = deque(maxlen=3)
    chunks = []
    started = False
    silent = 0.0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="float32", blocksize=block) as stream:
        noise = []
        for _ in range(5):
            data, _overflow = stream.read(block)
            noise.append(float(np.abs(data).mean()))
        threshold = max(0.01, float(np.mean(noise)) * 3)
        for _ in range(int(max_seconds / BLOCK_SECONDS)):
            data, _overflow = stream.read(block)
            volume = float(np.abs(data).mean())
            if volume > threshold:
                if not started:
                    chunks.extend(before)
                started = True
                silent = 0.0
            elif started:
                silent += BLOCK_SECONDS
            if started:
                chunks.append(data)
                if silent >= silence_seconds:
                    break
            else:
                before.append(data)
    if not chunks:
        return None
    return np.concatenate(chunks).flatten()


ACCURATE = True  # True: use the slower small.en model for the mic button and for commands
_accurate = None


ONLINE = True  # True: use Google's free speech service for commands (your voice is sent to Google)


def _vocab_prompt():
    """A natural example sentence with your real names, so Whisper expects that kind of speech."""
    import re
    names = []
    for stem in understanding._hints().split(", "):
        for token in re.findall(r"[A-Za-z]{5,}", stem):
            if token.lower() not in ("resume", "updated", "final", "document", "latest", "krishna", "surprise"):
                names.append(token.title())
                break
    names = list(dict.fromkeys(names))[:4]
    a = names[0] if names else "Balamurali"
    b = names[1] if len(names) > 1 else a
    return ("REEZ, what skills are in %s's resume? How many certificates does %s have? "
            "What projects and internships are in %s's resume?") % (a, b, a)


def _online(audio):
    """Recognise with Google's free speech service (needs internet; your voice is sent to Google)."""
    try:
        import speech_recognition as sr
        pcm = (np.clip(np.asarray(audio, dtype="float32"), -1, 1) * 32767).astype("<i2").tobytes()
        return sr.Recognizer().recognize_google(sr.AudioData(pcm, 16000, 2), language="en-IN").strip()
    except Exception:
        return ""


def _run(model, audio, beams):
    audio = np.asarray(audio, dtype="float32")
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if 0 < peak < 0.2:
        audio = (audio / peak * 0.5).astype("float32")
    prompt = _vocab_prompt()
    segments, _info = model.transcribe(audio, language="en", task="transcribe",
                                       beam_size=beams, vad_filter=True, initial_prompt=prompt, condition_on_previous_text=False)
    return " ".join(seg.text for seg in segments).strip()


def transcribe(audio):
    """Speech to English text (fast model)."""
    return _run(stt, audio, 3)


def accurate_model():
    global _accurate
    if _accurate is None:
        try:
            _accurate = WhisperModel("small.en", device="cpu", compute_type="int8")
        except Exception:
            _accurate = stt
    return _accurate


def transcribe_accurate(audio):
    if ONLINE:
        text = _online(audio)
        if text:
            return text
    if not ACCURATE:
        return transcribe(audio)
    return _run(accurate_model(), audio, 3)

def speak(text):
    import tts
    tts.speak(text)

def run():
    history = []
    speak("Hello, I am REEZ. How can I help you?")
    while True:
        print("\nListening...")
        audio = record()
        if audio is None:
            continue
        heard = transcribe(audio)
        if not heard:
            continue
        print("Heard:", heard)
        result = understanding.process(heard, history)
        if result["intent"] == "exit":
            speak("Goodbye!")
            break
        if result["intent"] == "chat":
            reply = understanding.small_talk(heard, history)
        else:
            reply, _sources = brain.answer(result["question"], spoken=True)
        print("REEZ:", reply)
        understanding.remember(history, result["question"], reply)
        speak(reply)


if __name__ == "__main__":
    run()














