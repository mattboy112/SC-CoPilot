import numpy as np
import pytest

import sc_listen as L

rng = np.random.default_rng(7)


def chunk(sec, noise=0.002, voice=0.0):
    n = int(sec * L.RATE)
    t = np.arange(n) / L.RATE
    x = rng.normal(0, noise, n).astype(np.float32)
    if voice:
        syllables = np.clip(np.sin(2 * np.pi * 2.5 * t) + 0.3, 0, 1)
        x += (voice * np.sin(2 * np.pi * 170 * t) * syllables).astype(np.float32)
    return [x[i:i + L.FRAME] for i in range(0, n - L.FRAME + 1, L.FRAME)]


def run(seg, frames):
    return [a for a in (seg.feed(f) for f in frames) if a is not None]


def test_one_sentence_becomes_one_recording_with_a_bit_before_it():
    got = run(L.Segmenter(), chunk(2) + chunk(1.2, voice=0.12) + chunk(1.5))
    assert len(got) == 1
    assert 1.4 <= len(got[0]) / L.RATE <= 2.4


def test_clicks_and_quiet_rooms_are_ignored():
    assert run(L.Segmenter(), chunk(3) + chunk(0.06, voice=0.3) + chunk(2)) == []


def test_loud_background_raises_the_bar():
    seg = L.Segmenter()
    run(seg, chunk(4, noise=0.03))
    assert seg.noise > 0.02
    assert run(seg, chunk(1.0, noise=0.03, voice=0.02) + chunk(1.5, noise=0.03)) == [], "speech barely over game noise is skipped"
    assert len(run(seg, chunk(1.0, noise=0.03, voice=0.25) + chunk(1.5, noise=0.03))) == 1


def test_low_sensitivity_needs_a_louder_voice_than_high():
    quiet_voice = chunk(1) + chunk(1.0, voice=0.006) + chunk(1.5)
    assert run(L.Segmenter("low"), quiet_voice) == []
    assert len(run(L.Segmenter("high"), quiet_voice)) == 1


def test_a_steady_hum_is_treated_as_background():
    seg = L.Segmenter()
    n = int(8 * L.RATE)
    hum = (0.08 * np.sin(2 * np.pi * 120 * np.arange(n) / L.RATE)).astype(np.float32)
    got = run(seg, [hum[i:i + L.FRAME] for i in range(0, n - L.FRAME + 1, L.FRAME)])
    assert len(got) <= 1, "at most one cut while it learns the hum, then nothing"
    assert seg.threshold() > 0.08


def test_long_talking_is_cut_at_the_limit():
    got = run(L.Segmenter(max_s=3.0), chunk(1) + chunk(7, voice=0.1) + chunk(1.5))
    assert len(got) >= 2 and all(len(a) / L.RATE <= 3.1 for a in got)


@pytest.mark.parametrize("text,name,want", [
    ("Co-Pilot, gear down", "Co-Pilot", "gear down"),
    ("copilot gear down", "Co-Pilot", "gear down"),
    ("co pilot shields up", "Co-Pilot", "shields up"),
    ("Hey Co-Pilot, what's my objective?", "Co-Pilot", "what's my objective?"),
    ("Computer, lights on.", "Co-Pilot", "lights on."),
    ("Jarvis scan", "Jarvis", "scan"),
    ("Co-Pilot.", "Co-Pilot", ""),
    ("gear down", "Co-Pilot", None),
    ("I told my copilot friend", "Co-Pilot", None),
    ("", "Co-Pilot", None),
])
def test_wake_word(text, name, want):
    assert L.strip_wake(text, name) == want


def test_saying_just_the_name_opens_a_short_window():
    g = L.WakeGate()
    assert g.check("gear down", "Co-Pilot", now=100) is None
    assert g.check("Co-Pilot", "Co-Pilot", now=100) == ""
    assert g.check("gear down", "Co-Pilot", now=103) == "gear down"
    assert g.check("lights on", "Co-Pilot", now=104) is None, "the window closes after one sentence"
    assert g.check("Co-Pilot", "Co-Pilot", now=110) == ""
    assert g.check("lights on", "Co-Pilot", now=110 + L.WAKE_WINDOW + 1) is None
    assert g.check("lights on", "Co-Pilot", required=False, now=200) == "lights on"


class FakeSettings(dict):
    pass


def test_it_never_hears_itself_or_talks_over_push_to_talk():
    busy = [False]
    heard = []
    va = L.VoiceActivation(lambda: {"talk_mode": "voice"}, lambda: busy[0], heard.append, lambda on: heard.append(("hearing", on)))
    t = 0.0
    out = []
    for i, f in enumerate(chunk(1) + chunk(1.0, voice=0.15) + chunk(1.5)):
        busy[0] = 33 <= i < 70
        t += 0.03
        a = va.step(f, now=t)
        if a is not None:
            out.append(a)
    assert out == [], "speech while the co-pilot is talking is dropped"
    t += 1.0
    busy[0] = False
    for f in chunk(1) + chunk(1.0, voice=0.15) + chunk(1.5):
        t += 0.03
        a = va.step(f, now=t)
        if a is not None:
            out.append(a)
    assert len(out) == 1
    assert ("hearing", True) in heard and heard[-1] == ("hearing", False)


def test_off_means_no_microphone():
    va = L.VoiceActivation(lambda: {"talk_mode": "ptt"}, lambda: False, lambda a: None)
    assert not va.enabled()


def test_speech_detector_drops_bangs_and_hums_when_available():
    pytest.importorskip("faster_whisper")
    n = int(1.5 * L.RATE)
    t = np.arange(n) / L.RATE
    assert L.has_speech((0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)) is False
    assert L.has_speech((rng.normal(0, 0.2, n) * np.exp(-t * 3)).astype(np.float32)) is False
    assert L.has_speech(np.zeros(n, np.float32)) is False
