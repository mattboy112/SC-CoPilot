import math

import numpy as np
import pytest

import sc_avatar as AV
import sc_fx as FX


def run(model, mode, level=0.0, secs=2.0, fps=30, t0=0.0):
    shapes = None
    for i in range(int(secs * fps)):
        shapes = model.step(t0 + i / fps, mode, level)
    return shapes


def test_mix_blends_toward_background():
    assert AV.mix("#ffffff", "#000000", 1) == "#ffffff"
    assert AV.mix("#ffffff", "#000000", 0) == "#000000"
    assert AV.mix("#ffffff", "#000000", 0.5) == "#808080"
    assert AV.mix("#ffffff", "#000000", 7) == "#ffffff"


@pytest.mark.parametrize("size", [72, 96, 132, 211])
@pytest.mark.parametrize("mode,level", [("idle", 0), ("listen", 0), ("think", 0), ("speak", 1.0), ("speak", -1.0), ("bogus", 0)])
def test_everything_stays_inside_the_canvas(size, mode, level):
    m = AV.AvatarModel(size, "#0e151c")
    for _ in range(3):
        s = run(m, mode, level, secs=1.5)
        c = size / 2
        assert len(s["points"]) == AV.AvatarModel.POINTS and len(s["arcs"]) == 20 and len(s["core"]) == 3
        for x, y, r, color, front in s["points"]:
            assert -0.5 <= x - r and x + r <= size + 0.5 and -0.5 <= y - r and y + r <= size + 0.5
        for r, start, extent, width, color in s["arcs"]:
            assert r + width / 2 <= c
        for r, color in s["core"]:
            assert 0 < r <= c
        if s["chase"]:
            assert s["chase"][0] + s["chase"][3][0] / 2 <= c


def test_core_follows_the_voice():
    m = AV.AvatarModel(96, "#0e151c")
    quiet = run(m, "speak", 0.0)["core"][2][0]
    loud = run(m, "speak", 1.0, t0=2)["core"][2][0]
    back = run(m, "idle", 0.0, t0=4)["core"][2][0]
    assert loud > quiet * 1.3
    assert back < loud


def test_listening_pulls_the_cloud_in_and_thinking_shows_the_chase():
    m = AV.AvatarModel(96, "#0e151c")
    spread = lambda s: max(math.hypot(x - 48, y - 48) for x, y, *_ in s["points"])
    idle = run(m, "idle")
    assert idle["chase"] is None
    listen = run(m, "listen", t0=2)
    assert spread(listen) < spread(idle) * 0.92
    think = run(m, "think", t0=4)
    assert think["chase"] is not None


def test_fake_level_stays_in_range():
    vals = [AV.fake_level(t / 50) for t in range(2000)]
    assert min(vals) >= 0 and max(vals) <= 1 and max(vals) > 0.6


def test_envelope_tracks_loudness():
    sr = 24000
    t = np.arange(sr) / sr
    x = np.sin(2 * np.pi * 200 * t).astype(np.float32) * np.where(t < 0.5, 0.05, 0.8).astype(np.float32)
    env = FX.envelope(x, sr)
    assert len(env) == 50
    assert max(env[:20]) < 0.3 and min(env[30:]) > 0.9
    assert FX.envelope(np.zeros(10, np.float32), sr) == []


def test_setting_reads_new_and_old_keys():
    assert AV.setting({}) == "medium"
    assert AV.setting({"avatar": "off"}) == "off"
    assert AV.setting({"avatar": "small"}) == "small"
    assert AV.setting({"avatar_on": False, "avatar_size": "large"}) == "large"
    assert AV.setting({"avatar": "bogus", "avatar_size": "nope"}) == "medium"
