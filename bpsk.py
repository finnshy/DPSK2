"""BPSK im Basisband: Senden und Frequenzoffset messen.

Sender:    Bits -> Symbole ±1 -> Rechteckimpulse -> I = Symbol, Q = 0 (Stereo-Ausgang)

Empfänger: r = I + jQ. Ein Frequenzoffset Δf zwischen Sender- und Empfänger-Oszillator
           dreht das Signal:  r(t) = a(t) · e^{j(2π·Δf·t + φ0)}  mit a(t) = ±A.
           Quadrieren entfernt die BPSK-Modulation (±1)² = 1:
               r²(t) = A² · e^{j(2π·2Δf·t + 2φ0)}
           -> im Spektrum von r² eine Linie bei 2·Δf, die Phase von r² wächst mit 4π·Δf·t.
           Dafür braucht der Empfänger weder Synchronisation noch die gesendeten Daten.
           Eindeutig bis |Δf| < fs/4 = 12 kHz.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Config:
    fs: int = 48000             # Abtastrate der Soundkarte [Hz]
    symbol_rate: float = 1000   # Symbole pro Sekunde
    amplitude: float = 0.2      # Ausgangspegel (0..1)
    n_symbols: int = 2000       # Symbole pro Burst
    pattern: str = "Zufall"     # "Zufall", "Nur Einsen (Träger)", "Eigene Bits"
    bits: str = "1 0 1 1 0 0 1 0"
    pause_s: float = 0.5        # Pause zwischen Bursts beim Dauersenden

    @property
    def sps(self) -> int:
        """Abtastwerte pro Symbol."""
        return max(1, int(round(self.fs / self.symbol_rate)))


PATTERNS = ["Zufall", "Nur Einsen (Träger)", "Eigene Bits"]


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------
def make_bits(cfg: Config) -> np.ndarray:
    if cfg.pattern == "Zufall":
        return np.random.default_rng(1).integers(0, 2, cfg.n_symbols)
    if cfg.pattern == "Nur Einsen (Träger)":
        return np.ones(cfg.n_symbols, int)
    b = [int(c) for c in cfg.bits if c in "01"]
    if not b:
        raise ValueError("Eigene Bits: nur 0 und 1 eingeben")
    return np.resize(b, cfg.n_symbols)          # so oft wiederholen, bis n_symbols erreicht


def modulate(cfg: Config, bits: np.ndarray, silence_s: float = 0.2) -> np.ndarray:
    """-> Stereo-Signal [I, Q] als float32. Bit 1 -> +1, Bit 0 -> -1."""
    sym = 2.0 * np.asarray(bits) - 1.0
    i = np.repeat(sym, cfg.sps) * cfg.amplitude
    z = np.zeros(int(silence_s * cfg.fs))
    i = np.concatenate([z, i, z])
    return np.stack([i, np.zeros_like(i)], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# Empfänger
# ---------------------------------------------------------------------------
def _smooth(x, n):
    n = max(1, int(n))
    return np.convolve(x, np.ones(n) / n, mode="same")


def find_burst(r: np.ndarray, fs: int):
    """Bereich mit Signal (Hüllkurve > 30 % des Maximums). -> (start, ende) oder None."""
    env = _smooth(np.abs(r), 0.005 * fs)
    on = env > 0.3 * np.percentile(env, 99.5)
    if not on.any() or on.all():
        return None
    edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    k = int(np.argmax(ends - starts))                   # längster Abschnitt
    margin = int(0.01 * fs)                             # Ein-/Ausschwingen abschneiden
    a, b = starts[k] + margin, ends[k] - margin
    return (a, b) if b - a > 0.05 * fs else None


def analyze(y: np.ndarray, cfg: Config) -> dict:
    """Aufnahme (N x 2, I und Q) auswerten."""
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 2 or y.shape[1] < 2:
        raise ValueError("Es wird eine Stereo-Aufnahme (I links, Q rechts) benötigt")
    fs = cfg.fs
    r_all = y[:, 0] + 1j * y[:, 1]
    r_all = r_all - np.mean(r_all)                      # Gleichanteil entfernen
    burst = find_burst(r_all, fs)
    a, b = burst if burst else (0, len(r_all))          # ohne Burst: ganze Aufnahme
    r = r_all[a:b]
    t = np.arange(len(r)) / fs

    # 1) Frequenzoffset aus dem Spektrum von r²  (Linie bei 2·Δf)
    s = r ** 2
    nfft = 1 << int(np.ceil(np.log2(len(s)))) + 2      # Nullen anhängen -> feines Raster
    S = np.abs(np.fft.fft(s * np.hanning(len(s)), nfft))
    f2 = np.fft.fftfreq(nfft, 1 / fs)
    k = int(np.argmax(S))
    if 0 < k < nfft - 1:                                # Parabel-Interpolation
        l, m, rr = np.log(S[k - 1] + 1e-30), np.log(S[k] + 1e-30), np.log(S[(k + 1) % nfft] + 1e-30)
        d = 0.5 * (l - rr) / (l - 2 * m + rr) if (l - 2 * m + rr) != 0 else 0.0
    else:
        d = 0.0
    df = (f2[k] + d * fs / nfft) / 2

    # 2) Phase über der Zeit: r² um 2·Δf zurückdrehen, glätten, abwickeln, wieder addieren
    win = 0.002 * fs                                    # 2 ms Glättung
    s_res = _smooth(s * np.exp(-2j * np.pi * 2 * df * t), win)
    phase = (np.unwrap(np.angle(s_res)) + 2 * np.pi * 2 * df * t) / 2    # Phase von r ohne Modulation
    phase -= phase[0]
    # Momentanfrequenz (Steigung der Phase, über 10 ms geglättet)
    f_inst = _smooth(np.gradient(phase) * fs / (2 * np.pi), 0.01 * fs)
    edge = int(0.01 * fs)
    f_inst[:edge] = np.nan
    f_inst[-edge:] = np.nan
    drift = float(np.polyfit(t, phase, 2)[0] / np.pi) if len(t) > 3 else 0.0

    # 3) Symbole (Integrieren über ein Symbol), ohne und mit Korrektur des Offsets
    sps = cfg.sps
    n_sym = len(r) // sps - 1
    best, best_e = 0, -1.0
    for off in range(0, sps, max(1, sps // 16)):        # Symboltakt: maximale Energie
        blocks = (r * np.exp(-2j * np.pi * df * t))[off:off + n_sym * sps].reshape(n_sym, sps)
        e = float(np.sum(np.abs(blocks.sum(axis=1)) ** 2))
        if e > best_e:
            best, best_e = off, e
    sl = slice(best, best + n_sym * sps)
    # ohne Korrektur: Abtastwert in der Symbolmitte (die Phase läuft mit Δf um)
    sym_raw = r[best + sps // 2: best + n_sym * sps: sps][:n_sym]
    # mit Korrektur: gemessenen Phasenverlauf abziehen (erfasst auch Drift), über das Symbol mitteln
    sym_corr = (r * np.exp(-1j * phase))[sl].reshape(n_sym, sps).mean(axis=1)
    t_sym = (best + np.arange(n_sym) * sps + sps / 2) / fs

    # Spektrum von r (zur Anzeige)
    R = np.abs(np.fft.fft(r * np.hanning(len(r)), nfft))
    return {
        "burst_found": burst is not None, "t0": a / fs, "duration": len(r) / fs,
        "df": float(df), "drift": drift, "rot_per_symbol_deg": float((360 * df / cfg.symbol_rate + 180) % 360 - 180),
        "f": np.fft.fftshift(f2), "R_db": np.fft.fftshift(20 * np.log10(R / R.max() + 1e-12)),
        "S_db": np.fft.fftshift(20 * np.log10(S / S.max() + 1e-12)),
        "t": t, "phase": phase, "f_inst": f_inst,
        "t_sym": t_sym, "sym_raw": sym_raw, "sym_corr": sym_corr,
        "r": r, "level": float(np.sqrt(np.mean(np.abs(r) ** 2))),
    }


def summary(res: dict) -> str:
    lines = []
    if not res["burst_found"]:
        lines.append("Kein Burst erkannt – ganze Aufnahme ausgewertet.")
    lines += [
        "Ausgewertet: %.3f s ab %.3f s, Pegel %.4f" % (res["duration"], res["t0"], res["level"]),
        "Frequenzoffset: %+.2f Hz" % res["df"],
        "Drift: %+.2f Hz/s" % res["drift"],
        "Phasendrehung je Symbol: %+.1f°" % res["rot_per_symbol_deg"],
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Simulation (für Tests ohne Hardware)
# ---------------------------------------------------------------------------
def simulate(tx: np.ndarray, cfg: Config, df: float = 0.0, drift: float = 0.0,
             phase0_deg: float = 0.0, snr_db: float = 30.0, seed: int = 0) -> np.ndarray:
    """Frequenzoffset df [Hz], Drift [Hz/s], Rauschen (SNR bezogen auf das Signal)."""
    rng = np.random.default_rng(seed)
    x = tx[:, 0] + 1j * tx[:, 1]
    t = np.arange(len(x)) / cfg.fs
    y = x * np.exp(1j * (2 * np.pi * (df * t + 0.5 * drift * t ** 2) + np.radians(phase0_deg)))
    p = np.mean(np.abs(x[x != 0]) ** 2)
    sigma = np.sqrt(p / 10 ** (snr_db / 10) / 2)
    y = y + sigma * (rng.standard_normal(len(y)) + 1j * rng.standard_normal(len(y)))
    return np.stack([y.real, y.imag], axis=1).astype(np.float32)
