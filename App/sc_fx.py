import numpy as np

PRESETS = [
    ("off", "Off (clean voice)"),
    ("cockpit", "Cockpit AI (subtle)"),
    ("computer", "Ship computer"),
    ("helmet", "Helmet comms"),
    ("radio", "Long-range radio"),
    ("deep", "Deep and dark"),
    ("echo", "Echo chamber"),
]

PITCH_RANGE = (-8, 8)


def _next_pow2(n):
    return 1 << (int(n) - 1).bit_length()


def eq(x, sr, points):
    """Zero-phase EQ: points = [(hz, db), ...] on a log-frequency curve."""
    n = _next_pow2(len(x) + sr // 4)
    spec = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    hz = np.array([p[0] for p in points], dtype=float)
    db = np.array([p[1] for p in points], dtype=float)
    gain = 10 ** (np.interp(np.log10(np.maximum(f, 1.0)), np.log10(hz), db) / 20.0)
    return np.fft.irfft(spec * gain, n)[:len(x)].astype(np.float32)


def convolve(x, ir):
    n = _next_pow2(len(x) + len(ir))
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)[:len(x) + len(ir) - 1]
    return y.astype(np.float32)


def room_ir(sr, decay, density=1.0, seed=7, early=()):
    rng = np.random.default_rng(seed)
    n = int(sr * decay * 1.2)
    t = np.arange(n) / sr
    tail = rng.standard_normal(n) * np.exp(-6.9 * t / decay) * density
    tail[: int(sr * 0.004)] = 0
    for ms, g in early:
        i = int(sr * ms / 1000)
        if i < n:
            tail[i] += g
    tail[0] = 1.0
    return (tail / np.sqrt(np.sum(tail ** 2))).astype(np.float32)


def saturate(x, drive):
    return (np.tanh(x * drive) / np.tanh(drive)).astype(np.float32)


def ring(x, sr, hz, depth):
    t = np.arange(len(x)) / sr
    return (x * (1 - depth + depth * np.sin(2 * np.pi * hz * t))).astype(np.float32)


def downsample_hold(x, sr, target):
    step = max(1, int(round(sr / target)))
    y = np.repeat(x[::step], step)[:len(x)]
    return y.astype(np.float32)


def squelch(sr, ms=70, level=0.25, seed=3):
    rng = np.random.default_rng(seed)
    n = int(sr * ms / 1000)
    env = np.minimum(1, np.arange(n) / (sr * 0.003)) * np.exp(-np.arange(n) / (sr * ms / 3000))
    burst = rng.standard_normal(n) * env * level
    burst = eq(burst.astype(np.float32), sr, [(100, -30), (900, -4), (2200, 0), (4000, -4), (8000, -30)])
    click = np.zeros(int(sr * 0.006), dtype=np.float32)
    click[0], click[1] = 0.6, -0.4
    return np.concatenate([click, burst]).astype(np.float32)


def stretch(x, sr, factor):
    """Make audio longer (factor > 1) or shorter without changing its pitch.

    Cuts it into short overlapping slices and lays them down at a different spacing. Each slice is
    nudged a few milliseconds to wherever it lines up best with the previous one (WSOLA), which keeps
    the voice smooth instead of buzzy.
    """
    x = np.asarray(x, dtype=np.float32)
    if abs(factor - 1.0) < 1e-3 or len(x) < sr // 20:
        return x
    win = int(sr * 0.025) & ~1
    hop = win // 2
    tol = int(sr * 0.008)
    w = np.hanning(win).astype(np.float32)
    n_out = int(len(x) * factor)
    xp = np.concatenate([np.zeros(tol, np.float32), x, np.zeros(win * 2 + tol * 2, np.float32)])
    out = np.zeros(n_out + win * 2, np.float32)
    norm = np.zeros_like(out)
    hop_in = hop / factor
    pos, k, nxt = 0, 0, None
    while pos < n_out:
        centre = int(round(k * hop_in)) + tol
        if centre + win + tol >= len(xp):
            break
        if nxt is None:
            start = centre
        else:
            lo = max(0, centre - tol)
            region = xp[lo:centre + tol + win]
            start = lo + int(np.argmax(np.correlate(region, nxt, mode="valid")))
        seg = xp[start:start + win]
        out[pos:pos + win] += seg * w
        norm[pos:pos + win] += w
        nxt = xp[start + hop:start + hop + win]
        pos += hop
        k += 1
    norm[norm < 1e-3] = 1.0
    return (out / norm)[:n_out].astype(np.float32)


def resample(x, ratio):
    """Play audio ratio times faster (shorter and higher) or slower, by interpolation."""
    idx = np.arange(0, len(x) - 1, ratio)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


def pitch(x, sr, semitones):
    """Raise or lower the pitch, keeping the same speed. 12 semitones = one octave."""
    x = np.asarray(x, dtype=np.float32)
    if abs(semitones) < 0.05 or len(x) == 0:
        return x
    r = 2 ** (semitones / 12.0)
    y = stretch(x, sr, r)
    if r > 1:
        cut = sr / 2 / r
        y = eq(y, sr, [(20, 0), (cut * 0.85, 0), (cut, -40), (sr / 2, -60)])
    y = resample(y, r)
    if len(y) >= len(x):
        return y[:len(x)]
    return np.concatenate([y, np.zeros(len(x) - len(y), np.float32)])


def fade_tail(x, sr, keep, fade=0.25):
    """Cut a long echo tail down to `keep` seconds after the voice, fading out smoothly."""
    n = min(len(x), keep)
    y = x[:n].copy()
    f = min(n, int(sr * fade))
    if f > 0:
        y[-f:] *= np.linspace(1, 0, f, dtype=np.float32) ** 2
    return y


def normalize(x, peak=0.89):
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return (x * (peak / m)).astype(np.float32) if m > 1e-6 else x


def pad(x, sr, before=0.0, after=0.0):
    return np.concatenate([np.zeros(int(sr * before), np.float32), x, np.zeros(int(sr * after), np.float32)])


def _fx(x, sr, preset):
    if preset == "cockpit":
        y = eq(x, sr, [(60, -18), (120, -3), (300, 0), (2500, 2.5), (6000, 1.5), (11000, 0)])
        wet = convolve(y, room_ir(sr, 0.32, 0.6, early=((7, 0.35), (13, 0.2))))[:len(y) + int(sr * 0.25)]
        y = pad(y, sr, after=len(wet) / sr - len(y) / sr)
        return y * 0.88 + wet * 0.22
    if preset == "computer":
        y = eq(x, sr, [(80, -24), (160, -4), (400, -1), (1200, 0), (3200, 4), (7500, 2.5), (12000, -2)])
        dbl = np.concatenate([np.zeros(int(sr * 0.011), np.float32), y])[:len(y)]
        y = y * 0.9 + dbl * 0.22
        y = ring(y, sr, 55, 0.07)
        ir = room_ir(sr, 0.22, 0.5, seed=11, early=((3.1, 0.5), (5.3, 0.38), (8.9, 0.27), (11.7, 0.18)))
        wet = convolve(y, ir)
        y = pad(y, sr, after=(len(wet) - len(y)) / sr)
        return saturate(y * 0.85 + wet * 0.3, 1.3)
    if preset == "helmet":
        y = eq(x, sr, [(120, -30), (260, -6), (500, 0), (1800, 2), (3600, 1), (5200, -12), (8000, -40)])
        y = saturate(normalize(y), 2.2)
        wet = convolve(y, room_ir(sr, 0.05, 0.3, seed=5, early=((1.4, 0.45), (2.6, 0.25))))
        y = pad(y, sr, after=(len(wet) - len(y)) / sr) * 0.8 + wet * 0.35
        rng = np.random.default_rng(1)
        hiss = eq(rng.standard_normal(len(y)).astype(np.float32) * 0.006, sr, [(300, -20), (2000, 0), (6000, -12)])
        sq = squelch(sr, 45, 0.18)
        return np.concatenate([sq * 0.6, y + hiss, sq * 0.8])
    if preset == "radio":
        y = eq(x, sr, [(200, -36), (380, -6), (700, 0), (1600, 3), (2700, 0), (3300, -10), (4200, -40)])
        y = downsample_hold(saturate(normalize(y), 3.2), sr, 11025)
        y = eq(y, sr, [(250, -30), (450, 0), (3000, 0), (3800, -30)])
        rng = np.random.default_rng(2)
        hiss = eq(rng.standard_normal(len(y)).astype(np.float32) * 0.02, sr, [(400, -20), (1500, 0), (3500, -15)])
        sq = squelch(sr, 80, 0.3)
        return np.concatenate([sq, y + hiss, squelch(sr, 110, 0.35, seed=9)])
    if preset == "deep":
        y = pitch(x, sr, -4)
        sub = pitch(x, sr, -12)
        y = normalize(y) + normalize(sub) * 0.16
        y = eq(y, sr, [(35, -14), (80, 3), (160, 4), (350, 0), (1200, -2), (3000, 0.5), (6000, -4), (10000, -14)])
        y = saturate(normalize(y), 1.7)
        ir = room_ir(sr, 0.7, 0.8, seed=13, early=((9, 0.3), (17, 0.22), (29, 0.15)))
        wet = eq(convolve(y, ir), sr, [(60, -10), (150, 0), (1500, -6), (4000, -20)])
        y = pad(y, sr, after=(len(wet) - len(y)) / sr)
        return fade_tail(y * 0.9 + wet * 0.2, sr, len(x) + int(sr * 0.6))
    if preset == "echo":
        y = eq(x, sr, [(70, -14), (180, 0), (3500, 0.5), (9000, -5)])
        taps = ((180, 0.55), (360, 0.36), (540, 0.24), (720, 0.15), (900, 0.09))
        ir = room_ir(sr, 1.9, 1.0, seed=21, early=((23, 0.4), (41, 0.32), (67, 0.25), (97, 0.18)) + taps)
        wet = eq(convolve(y, ir), sr, [(100, -8), (300, 0), (2500, -2), (5000, -10), (9000, -24)])
        y = pad(y, sr, after=(len(wet) - len(y)) / sr)
        return fade_tail(y * 0.72 + wet * 0.55, sr, len(x) + int(sr * 1.4), fade=0.5)
    return x


def apply(x, sr, preset="off", amount=1.0, semitones=0):
    """Process mono float32 audio. amount 0..1 blends the dry voice with the effect; semitones shifts the pitch."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if semitones and len(x):
        lo, hi = PITCH_RANGE
        x = pitch(normalize(x), sr, max(lo, min(hi, float(semitones))))
    if preset in (None, "", "off") or amount <= 0 or len(x) == 0:
        return normalize(x)
    x = normalize(x)
    y = _fx(x, sr, preset)
    if amount < 1.0:
        dry = np.zeros_like(y)
        off = int(sr * 0.051) if preset in ("helmet",) else int(sr * 0.086) if preset == "radio" else 0
        dry[off:off + len(x)] = x[: len(y) - off]
        y = dry * (1 - amount) + y * amount
    return normalize(y)
