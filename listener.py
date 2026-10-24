"""REEZ always-on listener: hears speech and reacts to the wake word."""

import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = int(SAMPLE_RATE * 0.1)
REFINE = True  # second, more accurate listening pass for commands (False = faster but less accurate)
LOG = Path(__file__).parent / "data" / "listener.log"
EXTRA = Path(__file__).parent / "data" / "wake_words.txt"
WAKE_WORDS = {"reez", "rees", "reese", "reas", "riz", "rhys", "ries", "reis", "reaz",
              "rez", "rease", "reeze", "reeves", "ryze", "reeds"}
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "yo"}
JUNK = {"thank you", "thanks", "thanks for watching", "you", "bye", "okay", "ok", "hmm", "uh", "um", "peace"}
_extra_cache = (0.0, set())


def _log(message):
    try:
        LOG.parent.mkdir(exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 200000:
            LOG.write_text("")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + message + "\n")
    except Exception:
        pass


def _extra_words():
    """Wake spellings you add yourself, one per line, in data/wake_words.txt."""
    global _extra_cache
    try:
        stamp = EXTRA.stat().st_mtime
    except OSError:
        return set()
    if stamp != _extra_cache[0]:
        words = {re.sub(r"[^a-z]", "", w.lower()) for w in EXTRA.read_text(encoding="utf-8-sig").split()}
        _extra_cache = (stamp, {w for w in words if w})
    return _extra_cache[1]


def _is_wake(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if w in WAKE_WORDS or w in _extra_words():
        return True
    return 3 <= len(w) <= 6 and SequenceMatcher(None, w, "reez").ratio() >= 0.7


def split_wake(text):
    """None if no wake word, "" if only the wake word, otherwise the command."""
    words = text.strip().split()
    i = 0
    if words and re.sub(r"[^a-z]", "", words[0].lower()) in GREETINGS:
        i = 1
    if i < len(words) and _is_wake(words[i]):
        return " ".join(words[i + 1:]).strip(" ,.:;!?-")
    return None


class Listener(threading.Thread):
    def __init__(self, on_heard, is_paused, transcribe, on_status=None, refine=None):
        super().__init__(daemon=True)
        self.on_heard = on_heard
        self.is_paused = is_paused
        self.transcribe = transcribe
        self.on_status = on_status
        self.refine = refine
        self.awake_until = 0.0
        self.running = True
        self.level = 0.0
        self.ok = False
        self.processing = False
        self.voice_until = 0.0

    def _status(self, message):
        _log("status: " + message)
        if self.on_status:
            try:
                self.on_status(message)
            except Exception:
                pass

    def run(self):
        pre = deque(maxlen=4)
        levels = deque([0.004] * 40, maxlen=300)
        chunks, started, silent, active = [], False, 0.0, 0
        was_paused = False
        announced = False
        last_error = 0.0
        while self.running:
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                    dtype="float32", blocksize=BLOCK) as stream:
                    self.ok = True
                    _log("microphone opened")
                    if not announced:
                        announced = True
                        self._status("Always listening. Say REEZ, then your question.")
                    while self.running:
                        data, _overflow = stream.read(BLOCK)
                        volume = float(np.abs(data).mean())
                        self.level = 0.6 * self.level + 0.4 * volume
                        paused = bool(self.is_paused())
                        if paused != was_paused:
                            was_paused = paused
                            _log("paused" if paused else "resumed")
                        if paused:
                            pre.clear()
                            chunks, started, silent, active = [], False, 0.0, 0
                            continue
                        levels.append(volume)
                        floor = min(0.03, float(np.percentile(levels, 15)))
                        threshold = max(0.008, floor * 2.8 + 0.003)
                        if volume > threshold:
                            if not started:
                                chunks = list(pre)
                                started = True
                                active = 0
                            silent = 0.0
                            active += 1
                            if active >= 2:
                                self.voice_until = time.time() + 1.2
                        elif started:
                            silent += 0.1
                        if started:
                            chunks.append(data)
                            limit = 1.2 if time.time() < self.awake_until else 0.8
                            if silent >= limit or len(chunks) > 120:
                                audio = np.concatenate(chunks).flatten()
                                keep = active >= 3 and len(audio) > SAMPLE_RATE * 0.5
                                chunks, started, silent, active = [], False, 0.0, 0
                                pre.clear()
                                if keep:
                                    loudest = float(np.abs(audio).max())
                                    _log("speech %.1fs, loudest %.3f%s, noise floor %.4f"
                                         % (len(audio) / SAMPLE_RATE, loudest,
                                            " (CLIPPING - lower the mic boost)" if loudest > 0.97 else "", floor))
                                    self._handle(audio)
                        else:
                            pre.append(data)
            except Exception as error:
                self.ok = False
                _log("microphone error: " + repr(error))
                if time.time() - last_error > 60:
                    last_error = time.time()
                    self._status("I cannot use the microphone: " + str(error)[:80])
                time.sleep(3)

    def _handle(self, audio):
        self.processing = True
        try:
            self._handle_inner(audio)
        finally:
            self.processing = False

    def _refined(self, audio):
        """Second, more accurate listening pass."""
        if not (REFINE and self.refine):
            return ""
        began = time.time()
        try:
            better = self.refine(audio).strip()
        except Exception as error:
            _log("accurate pass error: " + repr(error))
            return ""
        _log("accurate pass %.1fs: %s" % (time.time() - began, better))
        return better

    def _handle_inner(self, audio):
        try:
            text = self.transcribe(audio).strip()
        except Exception as error:
            _log("transcribe error: " + repr(error))
            return
        _log("heard: " + text)
        if not text:
            return
        now = time.time()
        command = split_wake(text)
        if command is not None:
            if command:
                better = self._refined(audio)
                again = split_wake(better) if better else None
                if again:
                    command = again
                self.awake_until = 0.0
                _log("wake + command: " + command)
                self.on_heard(command, False)
            else:
                self.awake_until = now + 8
                _log("wake only")
                self.on_heard("", True)
        elif now < self.awake_until:
            clean = re.sub(r"[^a-z ]", "", text.lower()).strip()
            if clean in JUNK or len(clean) < 3:
                return
            better = self._refined(audio)
            if better:
                text = better
            self.awake_until = 0.0
            _log("follow-up: " + text)
            self.on_heard(text, False)




