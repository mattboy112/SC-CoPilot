import numpy as np
import pytest

import sc_fx as FX

SR = 24000


def tone(sec=2.0, hz=140.0):
    t = np.arange(int(SR * sec)) / SR
    ph = 2 * np.pi * np.cumsum(hz * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / SR
    return FX.normalize(sum(np.sin(k * ph) / k for k in range(1, 20)).astype(np.float32))


def f0(x):
    seg = x[len(x) // 3: len(x) // 3 + SR // 5].astype(float)
    seg -= seg.mean()
    c = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lo, hi = SR // 400, SR // 50
    return SR / (lo + np.argmax(c[lo:hi]))


@pytest.mark.parametrize("semi", [-12, -8, -4, -1, 2, 5, 8])
def test_pitch_hits_target_and_keeps_length(semi):
    x = tone()
    y = FX.pitch(x, SR, semi)
    assert len(y) == len(x)
    assert np.isfinite(y).all()
    assert f0(y) == pytest.approx(f0(x) * 2 ** (semi / 12), rel=0.02)


def test_stretch_changes_length_not_pitch():
    x = tone()
    for factor in (0.7, 1.4):
        y = FX.stretch(x, SR, factor)
        assert len(y) == int(len(x) * factor)
        assert f0(y) == pytest.approx(f0(x), rel=0.02)


@pytest.mark.parametrize("preset", [p for p, _ in FX.PRESETS])
@pytest.mark.parametrize("semi", [0, -3])
def test_every_preset_is_clean(preset, semi):
    x = tone(1.0)
    y = FX.apply(x, SR, preset, 1.0, semi)
    assert np.isfinite(y).all() and 0.5 < np.abs(y).max() <= 0.9
    assert len(y) >= len(x)


def test_new_presets_listed_and_echo_tail_is_capped():
    names = [p for p, _ in FX.PRESETS]
    assert "deep" in names and "echo" in names
    x = tone(1.0)
    assert len(FX.apply(x, SR, "echo")) <= len(x) + int(SR * 1.4)


def test_pitch_alone_with_effect_off_and_clamped():
    x = tone()
    assert f0(FX.apply(x, SR, "off", 1.0, -5)) == pytest.approx(f0(x) * 2 ** (-5 / 12), rel=0.02)
    assert f0(FX.apply(x, SR, "off", 1.0, -40)) == pytest.approx(f0(x) * 2 ** (FX.PITCH_RANGE[0] / 12), rel=0.02)
