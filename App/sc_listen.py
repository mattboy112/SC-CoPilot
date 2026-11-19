"""Voice activation: listens all the time, cuts out what you say, and hands it over like a push-to-talk recording."""
import queue
import re
import threading
import time
import traceback
from collections import deque
from difflib import SequenceMatcher

import numpy as np

try:
    import sounddevice as sd
except Exception:
    sd = None

RATE = 16000
FRAME = 480
FRAME_MS = 30
SENSITIVITY = {"low": (3.5, 0.012), "medium": (2.5, 0.0075), "high": (1.8, 0.004)}
SENSITIVITY_CHOICES = [("low", "Low: noisy room or speakers"), ("medium", "Medium"), ("high", "High: quiet room and a headset")]
TALK_MODES = [("ptt", "Hold push-to-talk"), ("voice", "Voice activation (hands-free)")]
WAKE_WINDOW = 6.0
QUIET_AFTER_SPEAKING = 0.6
ALIASES = ("copilot", "computer")
LEAD_INS = {"hey", "ok", "okay", "yo", "hi"}


def level(frame):
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float32)))) if len(frame) else 0.0


class Segmenter:
    """Turns 30 ms frames into utterances. One starts when the level jumps well above the background noise and ends after a pause."""

    def __init__(self, sensitivity="medium", start_frames=3, end_ms=750, preroll_ms=300, max_s=12.0, min_voiced_s=0.3,
                 history_s=3.0):
        self.ratio, self.min_level = SENSITIVITY.get(sensitivity, SENSITIVITY["medium"])
        self.start_frames = start_frames
        self.end_frames = max(1, int(end_ms / FRAME_MS))
        self.max_frames = int(max_s * 1000 / FRAME_MS)
        self.min_voiced = max(1, int(min_voiced_s * 1000 / FRAME_MS))
        self.noise = self.min_level / 2.5
        self.levels = deque(maxlen=max(10, int(history_s * 1000 / FRAME_MS)))
        self.pre = deque(maxlen=max(1, int(preroll_ms / FRAME_MS)))
        self.reset()

    def reset(self):
        self.active = False
        self.loud = 0
        self.quiet = 0
        self.voiced = 0
        self.buf = []
        self.pre.clear()

    def threshold(self):
        return max(self.min_level, self.noise * self.ratio)

    def feed(self, frame):
        """Returns a finished utterance as one float32 array, or None.

        The background level is the quiet end (20th percentile) of the last few seconds, so steady engine or game noise
        raises the bar on its own, while the short gaps between words keep it low when someone is talking."""
        lvl = level(frame)
        self.levels.append(lvl)
        if len(self.levels) >= 10:
            self.noise = float(np.percentile(self.levels, 20))
        th = self.threshold()
        if not self.active:
            self.loud = self.loud + 1 if lvl > th else 0
            self.pre.append(frame)
            if self.loud >= self.start_frames:
                self.active = True
                self.buf = list(self.pre)
                self.voiced = self.loud
                self.quiet = 0
                self.pre.clear()
            return None
        self.buf.append(frame)
        if lvl > th * 0.6:
            self.voiced += 1
            self.quiet = 0
        else:
            self.quiet += 1
        if self.quiet >= self.end_frames or len(self.buf) >= self.max_frames:
            audio, voiced = np.concatenate(self.buf).astype(np.float32), self.voiced
            self.reset()
            if voiced >= self.min_voiced:
                return audio
        return None


def has_speech(audio):
    """A second, smarter check with the speech detector that ships with the speech model, so bangs and engine noise are dropped."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:
        return True
    try:
        spans = get_speech_timestamps(audio.astype(np.float32), VadOptions(min_speech_duration_ms=200, min_silence_duration_ms=300))
    except Exception:
        return True
    return sum(s["end"] - s["start"] for s in spans) >= 0.2 * RATE


def _compact(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _close(a, b):
    return a == b or (len(b) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def strip_wake(text, name):
    """If the words start with the co-pilot's name (optionally after "hey"), return what came after it. Otherwise None.

    "Co-Pilot, gear down" -> "gear down"; "hey computer what's my objective?" -> "what's my objective?"; "Co-Pilot." -> ""."""
    words = list(re.finditer(r"[A-Za-z0-9']+", text or ""))
    if not words:
        return None
    names = {_compact(name or "")} | set(ALIASES)
    names.discard("")
    i = 1 if words[0].group().lower() in LEAD_INS and len(words) > 1 else 0
    for n in (3, 2, 1):
        chunk = words[i:i + n]
        if len(chunk) < n:
            continue
        said = _compact("".join(w.group() for w in chunk))
        if any(_close(said, nm) for nm in names):
            return text[chunk[-1].end():].lstrip(" ,.!:;-").strip()
    return None


class WakeGate:
    """Decides whether a hands-free sentence was meant for the co-pilot."""

    def __init__(self):
        self.until = 0.0

    def check(self, text, name, required=True, now=None):
        """The words to act on, "" if only the name was said (the next few seconds then count), or None to ignore it."""
        if not required:
            return text
        now = time.time() if now is None else now
        rest = strip_wake(text, name)
        if rest is None and now < self.until:
            rest = text
        if rest is None:
            return None
        self.until = now + WAKE_WINDOW if rest == "" else 0.0
        return rest


class VoiceActivation(threading.Thread):
    """Runs the microphone all the time while voice activation is on.

    get_settings() -> the settings dict; busy() -> True while push-to-talk is held, the co-pilot is talking or still working;
    on_utterance(audio) gets each finished bit of speech; on_hearing(bool) says when someone seems to be talking."""

    def __init__(self, get_settings, busy, on_utterance, on_hearing=None):
        super().__init__(daemon=True, name="voice-activation")
        self.get_settings = get_settings
        self.busy = busy
        self.on_utterance = on_utterance
        self.on_hearing = on_hearing or (lambda on: None)
        self.frames = queue.Queue(maxsize=400)
        self.stream = None
        self.key = None
        self.status = "off"
        self.hearing = False
        self.quiet_until = 0.0
        self.stopped = False
        self.seg = Segmenter()

    def enabled(self):
        return self.get_settings().get("talk_mode") == "voice"

    def _cb(self, data, frames, t, status):
        try:
            self.frames.put_nowait(data[:, 0].copy() if data.ndim > 1 else data.copy())
        except queue.Full:
            pass

    def _open(self, device):
        self._close()
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME, callback=self._cb, device=device)
        self.stream.start()

    def _close(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _set_hearing(self, on):
        if on != self.hearing:
            self.hearing = on
            self.on_hearing(on)

    def stop(self):
        self.stopped = True

    def step(self, frame, now=None):
        """Handle one frame. Split out so tests can drive it without a microphone."""
        now = time.time() if now is None else now
        if self.busy():
            self.quiet_until = now + QUIET_AFTER_SPEAKING
            self.seg.reset()
            self._set_hearing(False)
            return None
        if now < self.quiet_until:
            self.seg.feed(frame * 0)
            return None
        audio = self.seg.feed(frame)
        self._set_hearing(self.seg.active)
        return audio

    def run(self):
        while not self.stopped:
            try:
                s = self.get_settings()
                if not self.enabled() or sd is None:
                    if self.stream is not None:
                        self._close()
                    self._set_hearing(False)
                    self.status = "off" if sd is not None else "voice packages missing (run Install.bat)"
                    time.sleep(0.3)
                    continue
                key = (s.get("mic"), s.get("va_sensitivity", "medium"))
                if self.stream is None or key != self.key:
                    self.seg = Segmenter(sensitivity=key[1])
                    self._open(key[0])
                    self.key = key
                    self.status = "listening"
                try:
                    frame = self.frames.get(timeout=0.3)
                except queue.Empty:
                    continue
                audio = self.step(frame)
                if audio is not None and has_speech(audio):
                    self.on_utterance(audio)
            except Exception as ex:
                self.status = f"microphone problem: {ex}"
                traceback.print_exc()
                self._close()
                self.key = None
                time.sleep(5)
        self._close()
