"""BPSK im Basisband mit Barker-Präambel: Senden, Frequenzoffset messen, Zeitsynchronisation.

Sender:    [Barker-13][Datenbits] -> Symbole ±1 -> Rechteckimpulse -> I = Symbol, Q = 0

Empfänger:
  1. Frequenzoffset: Ein Offset Δf dreht das Signal, r(t) = ±A · e^{j(2π·Δf·t + φ0)}.
     Quadrieren entfernt die BPSK-Modulation, (±1)² = 1:  r² = A² · e^{j(2π·2Δf·t + 2φ0)}
     -> Linie bei 2·Δf im Spektrum, Phasenverlauf aus der Phase von r² (eindeutig bis |Δf| < 12 kHz).
  2. Drehung herausrechnen: z = r · e^{-jφ(t)}  -> wieder ein reelles ±1-Signal
     (bis auf ein Vorzeichen, weil φ aus r² nur bis auf 180° bestimmt ist).
  3. Zeitsynchronisation: z mit dem Barker-Code korrelieren. Die Spitze liefert den Beginn
     des ersten Symbols; ihr Vorzeichen löst die 180°-Mehrdeutigkeit.
  4. Symbol Timing Recovery: ab dort jedes Symbol über seine Dauer integrieren
     (Integrate & Dump). Eine Early-Late-Regelung vergleicht die Integration ein Stück früher
     und später und schiebt das Integrationsfenster nach (gleicht Taktabweichungen aus).
"""
from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve

BARKER13 = np.array([1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1], dtype=float)


@dataclass
class Config:
    fs: int = 48000             # Abtastrate der Soundkarte [Hz]
    symbol_rate: float = 1000   # Symbole pro Sekunde
    amplitude: float = 0.2      # Ausgangspegel (0..1)
    n_symbols: int = 2000       # Datensymbole pro Burst (ohne Barker)
    pattern: str = "Zufall"     # "Zufall", "Nur Einsen (Träger)", "Eigene Bits"
    bits: str = "1 0 1 1 0 0 1 0"
    pause_s: float = 0.5        # Pause zwischen Bursts beim Dauersenden
    timing_gain: float = 0.05   # Regelverstärkung der Early-Late-Regelung (0 = aus)

    @property
    def sps(self) -> int:
        """Abtastwerte pro Symbol."""
        return max(4, int(round(self.fs / self.symbol_rate)))


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


def tx_symbols(bits) -> np.ndarray:
    """Barker-13 + Daten als ±1 (Bit 1 -> +1, Bit 0 -> -1)."""
    return np.concatenate([BARKER13, 2.0 * np.asarray(bits) - 1.0])


def modulate(cfg: Config, bits: np.ndarray, silence_s: float = 0.2) -> np.ndarray:
    """-> Stereo-Signal [I, Q] als float32."""
    i = np.repeat(tx_symbols(bits), cfg.sps) * cfg.amplitude
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
    env = _smooth(np.abs(r), 0.002 * fs)
    on = env > 0.3 * np.percentile(env, 99.5)
    if not on.any() or on.all():
        return None
    edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    k = int(np.argmax(ends - starts))                   # längster Abschnitt
    return (int(starts[k]), int(ends[k])) if ends[k] - starts[k] > 0.05 * fs else None


def _freq_offset(s, fs):
    """Frequenz der stärksten Linie in s (mit Parabel-Interpolation)."""
    nfft = 1 << int(np.ceil(np.log2(len(s)))) + 2
    S = np.abs(np.fft.fft(s * np.hanning(len(s)), nfft))
    f = np.fft.fftfreq(nfft, 1 / fs)
    k = int(np.argmax(S))
    l, m, r = (np.log(S[(k + i) % nfft] + 1e-30) for i in (-1, 0, 1))
    d = 0.5 * (l - r) / (l - 2 * m + r) if (l - 2 * m + r) != 0 else 0.0
    return f[k] + d * fs / nfft, f, S


def analyze(y: np.ndarray, cfg: Config) -> dict:
    """Aufnahme (N x 2, I und Q) auswerten."""
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 2 or y.shape[1] < 2:
        raise ValueError("Es wird eine Stereo-Aufnahme (I links, Q rechts) benötigt")
    fs, sps = cfg.fs, cfg.sps
    r_all = y[:, 0] + 1j * y[:, 1]
    r_all = r_all - np.mean(r_all)                      # Gleichanteil entfernen
    burst = find_burst(r_all, fs)
    if burst:                                           # etwas Rand lassen (für den Barker-Anfang)
        pad = int(0.02 * fs)
        a, b = max(0, burst[0] - pad), min(len(r_all), burst[1] + pad)
        on0, on1 = burst[0] - a + int(0.003 * fs), burst[1] - a - int(0.003 * fs)
    else:                                               # ohne Burst: ganze Aufnahme
        a, b = 0, len(r_all)
        on0, on1 = 0, b
    r = r_all[a:b]
    t = np.arange(len(r)) / fs

    # 1) Frequenzoffset aus dem Spektrum von r² (Linie bei 2·Δf), nur über den Burst
    f2_peak, f2, S = _freq_offset(r[on0:on1] ** 2, fs)
    df = f2_peak / 2

    # 2) Phasenverlauf: r² um 2·Δf zurückdrehen, glätten, abwickeln -> φ(t)
    s_res = _smooth(r ** 2 * np.exp(-2j * np.pi * 2 * df * t), 0.002 * fs)
    phase = (np.unwrap(np.angle(s_res)) + 2 * np.pi * 2 * df * t) / 2
    # außerhalb des Bursts (nur Rauschen) linear mit Δf fortsetzen
    phase[:on0] = phase[on0] + 2 * np.pi * df * (t[:on0] - t[on0])
    phase[on1:] = phase[on1 - 1] + 2 * np.pi * df * (t[on1:] - t[on1 - 1])
    f_inst = _smooth(np.gradient(phase) * fs / (2 * np.pi), 0.01 * fs)
    f_inst[:on0 + int(0.01 * fs)] = np.nan
    f_inst[on1 - int(0.01 * fs):] = np.nan
    tb = t[on0:on1]
    drift = float(np.polyfit(tb, phase[on0:on1], 2)[0] / np.pi) if len(tb) > 3 else 0.0
    z = r * np.exp(-1j * phase)                         # Drehung entfernt: reelles ±A-Signal

    # 3) Zeitsynchronisation mit dem Barker-Code
    tpl = np.repeat(BARKER13, sps)
    corr = fftconvolve(z, tpl[::-1], mode="valid")      # corr[n] = Σ z[n+i]·tpl[i]
    search = corr[:max(1, on0 + 30 * sps)] if burst else corr   # Barker liegt am Burst-Anfang
    n0 = int(np.argmax(np.abs(search)))
    peak = corr[n0]
    sign = 1.0 if peak.real >= 0 else -1.0              # löst die 180°-Mehrdeutigkeit
    z = z * sign
    norm = np.sqrt(np.sum(np.abs(z[n0:n0 + len(tpl)]) ** 2) * np.sum(tpl ** 2)) + 1e-30
    barker_quality = float(np.abs(peak) / norm)        # 1 = perfekte Übereinstimmung

    # 4) Symbol Timing Recovery: Integrate & Dump mit Early-Late-Regelung
    d = max(1, sps // 4)                                # Versatz für "früh"/"spät"
    pos = float(n0)
    starts, syms, terr = [], [], []
    while True:
        i = int(round(pos))
        if i - d < 0 or i + sps + d > len(z):
            break
        sym = z[i:i + sps].mean()
        early = abs(z[i - d:i - d + sps].mean())
        late = abs(z[i + d:i + d + sps].mean())
        e = (late - early) / (abs(sym) + 1e-30)         # > 0: Fenster sollte später liegen
        starts.append(i)
        syms.append(sym)
        terr.append(e)
        pos += sps + cfg.timing_gain * e * d
    starts, syms, terr = np.array(starts, int), np.array(syms), np.array(terr)
    if len(syms) > 13:                                  # Symbole nach dem Burst-Ende (nur Rauschen) abschneiden
        good = np.flatnonzero(np.abs(syms) > 0.5 * np.median(np.abs(syms[:13])))
        last = good[-1] + 1 if len(good) else len(syms)
        starts, syms, terr = starts[:last], syms[:last], terr[:last]
    n_sym = len(syms)
    timing_offset = starts - (n0 + np.arange(n_sym) * sps)   # Nachführung gegenüber starrem Raster
    bits_rx = (syms[13:].real > 0).astype(int)
    barker_ok = n_sym >= 13 and np.array_equal(np.sign(syms[:13].real), BARKER13)

    # ohne Korrektur: Abtastwert in der Symbolmitte des Rohsignals (Phase läuft mit Δf um)
    centers = starts + sps // 2
    sym_raw = r[centers] if n_sym else np.zeros(0, complex)

    R = np.abs(np.fft.fft(r[on0:on1] * np.hanning(on1 - on0), len(f2)))
    return {
        "burst_found": burst is not None, "t0": a / fs, "duration": (on1 - on0) / fs,
        "df": float(df), "drift": drift, "rot_per_symbol_deg": float((360 * df / cfg.symbol_rate + 180) % 360 - 180),
        "f": np.fft.fftshift(f2), "R_db": np.fft.fftshift(20 * np.log10(R / R.max() + 1e-12)),
        "S_db": np.fft.fftshift(20 * np.log10(S / S.max() + 1e-12)),
        "t": t, "phase": phase, "f_inst": f_inst, "on": (on0, on1),
        "r": r, "z": z, "sps": sps, "fs": fs,
        "corr": np.abs(corr) / (np.abs(peak) + 1e-30), "n0": n0, "barker_quality": barker_quality,
        "barker_ok": bool(barker_ok),
        "starts": starts, "centers": centers, "sym_corr": syms, "sym_raw": sym_raw,
        "timing_err": terr, "timing_offset": timing_offset, "bits": bits_rx,
        "level": float(np.sqrt(np.mean(np.abs(r[on0:on1]) ** 2))),
    }


def summary(res: dict) -> str:
    lines = []
    if not res["burst_found"]:
        lines.append("Kein Burst erkannt – ganze Aufnahme ausgewertet.")
    to = res["timing_offset"]
    lines += [
        "Ausgewertet: %.3f s ab %.3f s, Pegel %.4f" % (res["duration"], res["t0"], res["level"]),
        "Frequenzoffset: %+.2f Hz,  Drift: %+.2f Hz/s" % (res["df"], res["drift"]),
        "Phasendrehung je Symbol: %+.1f°" % res["rot_per_symbol_deg"],
        "Barker: Beginn bei %.4f s, Korrelation %.2f, %s" % (
            res["t0"] + res["n0"] / res["fs"], res["barker_quality"],
            "erkannt" if res["barker_ok"] else "NICHT sicher erkannt"),
        "Timing-Nachführung: %+d … %+d Abtastwerte" % (to.min(), to.max()) if len(to) else "Keine Symbole",
        "%d Datensymbole, erste Bits: %s" % (len(res["bits"]), "".join(map(str, res["bits"][:40]))),
    ]
    return "\n".join(lines)


def bit_errors(res: dict, cfg: Config):
    """Bitfehler gegenüber der Bitfolge, die der Sender mit cfg erzeugt. -> (Fehler, verglichen)"""
    ref = make_bits(cfg)
    n = min(len(ref), len(res["bits"]))
    return int(np.sum(ref[:n] != res["bits"][:n])), n


# ---------------------------------------------------------------------------
# Simulation (für Tests ohne Hardware)
# ---------------------------------------------------------------------------
def simulate(tx: np.ndarray, cfg: Config, df: float = 0.0, drift: float = 0.0, phase0_deg: float = 0.0,
             snr_db: float = 30.0, delay: int = 0, sco_ppm: float = 0.0, seed: int = 0) -> np.ndarray:
    """Frequenzoffset df [Hz], Drift [Hz/s], Rauschen, Verzögerung [Abtastwerte],
    Taktabweichung zwischen den Soundkarten [ppm]."""
    rng = np.random.default_rng(seed)
    x = tx[:, 0] + 1j * tx[:, 1]
    if sco_ppm:
        from scipy.signal import resample
        x = resample(x, int(round(len(x) * (1 - sco_ppm * 1e-6))))
    x = np.concatenate([np.zeros(delay, complex), x])
    t = np.arange(len(x)) / cfg.fs
    y = x * np.exp(1j * (2 * np.pi * (df * t + 0.5 * drift * t ** 2) + np.radians(phase0_deg)))
    p = np.mean(np.abs(x[np.abs(x) > 1e-6]) ** 2)
    sigma = np.sqrt(p / 10 ** (snr_db / 10) / 2)
    y = y + sigma * (rng.standard_normal(len(y)) + 1j * rng.standard_normal(len(y)))
    return np.stack([y.real, y.imag], axis=1).astype(np.float32)
