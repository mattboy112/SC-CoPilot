import numpy as np

import sc_hud as H

RNG = np.random.default_rng(0)


def space(h=120, w=120):
    img = (RNG.random((h, w, 3)) * 25).astype(np.uint8)
    img[RNG.random((h, w)) > 0.995] = 200
    return img


def ring(frac):
    img = space()
    yy, xx = np.mgrid[:120, :120]
    r = np.hypot(yy - 60, xx - 60)
    ang = (np.degrees(np.arctan2(yy - 60, xx - 60)) + 360) % 360
    m = (r > 40) & (r < 50) & (ang < 360 * frac)
    img[m] = (60, 170, 255)
    return img


def hullbar(frac):
    img = space(30, 200)
    img[10:20, 5:5 + int(190 * frac)] = (60, 220, 90) if frac > 0.6 else (230, 200, 40) if frac > 0.3 else (240, 60, 50)
    return img


def test_reader_tracks_shield_and_hull():
    prof = {"shield": {"cal": H.calibrate_region(ring(1.0), "color")}, "hull": {"cal": H.calibrate_region(hullbar(1.0), "any")}}
    for sf, hf in ((1.0, 1.0), (0.5, 0.8), (0.25, 0.45), (0.0, 0.2)):
        r = H.Reader.interpret(prof, ring(sf), hullbar(hf))
        assert r["visible"]
        assert abs(r["shields"] - sf) < 0.06 and abs(r["hull"] - hf) < 0.06


def test_no_target_is_reported():
    prof = {"shield": {"cal": H.calibrate_region(ring(1.0), "color")}, "hull": {"cal": H.calibrate_region(hullbar(1.0), "any")}}
    assert H.Reader.interpret(prof, space(), space(30, 200))["visible"] is False


def test_spoken_pct():
    assert H.spoken_pct(0.0) == "down" and H.spoken_pct(1.0) == "full" and H.spoken_pct(0.25) == "about 30 percent"
