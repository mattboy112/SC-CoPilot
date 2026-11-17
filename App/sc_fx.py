import numpy as np

PRESETS = [
    ("off", "Off (clean voice)"),
    ("cockpit", "Cockpit AI (subtle)"),
    ("computer", "Ship computer"),
    ("helmet", "Helmet comms"),
    ("radio", "Long-range radio"),
]


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
    return x


def apply(x, sr, preset="off", amount=1.0):
    """Process mono float32 audio. amount 0..1 blends the dry voice with the effect."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
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
