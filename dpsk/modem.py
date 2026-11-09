"""DPSK-Einträger-Modem mit Phasenanalyse.

Burst:  [Präambel: m-Sequenz, BPSK][Symbolfolge: differentiell codiert]

Sender:   Symbole -> RRC-Impulsformung -> Mischung auf ZF f_if -> I/Q (Stereo)
Empfänger:
  1. Grobe Frequenz: Leistungsspektrum, Signalband suchen (Bereich f_if ± max_cfo_hz)
  2. Mischen auf 0 Hz, Matched Filter (RRC)
  3. Burst finden: differentielle Korrelation mit der Präambel
     (z[k]·z*[k-1] ist unabhängig von Phase und – bis auf eine feste Drehung –
     vom Frequenzversatz) -> Zeitpunkt + Feinschätzung Frequenz
  4. Symbole abtasten (mit Nachführung des Abtastzeitpunkts)
  5. Analyse: Da Präambel und Symbolfolge bekannt sind, ist für jedes Symbol die
     Phasendifferenz zwischen Empfangs- und Sendesymbol messbar. Daraus:
     mittlerer Frequenzversatz, Drift, Phasenrest/Phasenrauschen, Momentanfrequenz,
     und was ein DPSK-Empfänger mit und ohne Frequenzkorrektur entscheiden würde.
"""
import numpy as np
from scipy.signal import fftconvolve, welch

from . import sequences
from .config import Config


# ---------------------------------------------------------------------------
# Gemeinsam
# ---------------------------------------------------------------------------
def rrc_taps(beta: float, sps: int, span: int) -> np.ndarray:
    """Wurzel-Kosinus-Filter, Energie 1 (Sende- und Empfangsfilter)."""
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    h = np.empty_like(t)
    for i, x in enumerate(t):
        if abs(x) < 1e-12:
            h[i] = 1 - beta + 4 * beta / np.pi
        elif abs(abs(x) - 1 / (4 * beta)) < 1e-9:
            h[i] = beta / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                        + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * x * (1 - beta)) + 4 * beta * x * np.cos(np.pi * x * (1 + beta))) \
                / (np.pi * x * (1 - (4 * beta * x) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def tx_symbols(cfg: Config, data: np.ndarray) -> np.ndarray:
    """Komplexe Sendesymbole: Präambel + differentiell codierte Folge."""
    p = sequences.preamble(cfg.preamble_len).astype(complex)
    inc = np.exp(2j * np.pi * np.asarray(data) / cfg.M)
    return np.concatenate([p, p[-1] * np.cumprod(inc)])


def _wrap_deg(x):
    return (np.asarray(x) + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------
def modulate(cfg: Config, data: np.ndarray, silence_s: float = 0.2):
    """-> (Stereo-Signal float32 [I, Q], Info-Dict)"""
    err = cfg.check()
    if err:
        raise ValueError(err)
    syms = tx_symbols(cfg, data)
    sps = cfg.sps
    h = rrc_taps(cfg.rolloff, sps, cfg.rrc_span)
    up = np.zeros(len(syms) * sps, complex)
    up[::sps] = syms
    x = np.convolve(up, h)
    n = np.arange(len(x))
    x = x * np.exp(2j * np.pi * cfg.f_if * n / cfg.fs)
    x = x / np.max(np.abs(x)) * cfg.amplitude
    z = np.zeros(int(silence_s * cfg.fs), complex)
    x = np.concatenate([z, x, z])
    out = np.stack([x.real, x.imag], axis=1).astype(np.float32)
    info = {"n_symbols": len(syms), "n_preamble": cfg.preamble_len, "n_data": len(data),
            "duration_s": len(syms) / cfg.rs, "rs": cfg.rs, "sps": sps,
            "bandwidth": cfg.bandwidth, "bitrate": cfg.rs * np.log2(cfg.M)}
    return out, info


# ---------------------------------------------------------------------------
# Empfänger
# ---------------------------------------------------------------------------
def _psd(r, fs, nper=8192):
    nper = int(min(nper, 2 ** int(np.floor(np.log2(max(len(r) // 4, 256))))))
    f, p = welch(r, fs=fs, nperseg=nper, return_onesided=False, detrend=False)
    return np.fft.fftshift(f), np.fft.fftshift(p)


def _rc_shape(f, rs, beta):
    """Leistungsdichtespektrum eines RRC-Signals (= Raised Cosine)."""
    a = np.abs(f)
    f1, f2 = (1 - beta) * rs / 2, (1 + beta) * rs / 2
    out = np.where(a <= f1, 1.0, 0.0)
    mid = (a > f1) & (a <= f2)
    out[mid] = 0.5 * (1 + np.cos(np.pi / (beta * rs) * (a[mid] - f1)))
    return out


def _coarse_center(f, p, cfg: Config):
    """Mittenfrequenz des Signals im I/Q-Spektrum (grob, aber auf wenige Hz genau)."""
    df = f[1] - f[0]
    p = p.copy()
    floor = np.median(p)
    p[np.abs(f) < 3 * df] = floor                 # Gleichanteil (LO-Durchgriff) ausblenden
    x = np.maximum(p - floor, 0)
    nb = int(np.ceil(cfg.bandwidth / 2 / df))
    tpl = _rc_shape(np.arange(-nb, nb + 1) * df, cfg.rs, cfg.rolloff)
    c = np.convolve(x, tpl, mode="same")
    allowed = (np.abs(f - cfg.f_if) <= cfg.max_cfo_hz) & (np.abs(f) < cfg.fs / 2 - nb * df)
    if not allowed.any():
        allowed[:] = True
    c[~allowed] = 0
    i = int(np.argmax(c))
    # Schwerpunkt im Fenster ±Bandbreite (genau für Zufallsdaten und für einzelne Linien)
    w = np.abs(f - f[i]) <= cfg.bandwidth
    fc = float(np.sum(f[w] * x[w]) / max(np.sum(x[w]), 1e-30))
    snr_spec = float(10 * np.log10(np.max(p[w]) / floor)) if floor > 0 else 0.0
    return fc, snr_spec


def _mixdown_mf(r, fc, fs, h, n_offset=0):
    n = np.arange(len(r)) + n_offset
    return fftconvolve(r * np.exp(-2j * np.pi * fc * n / fs), h, mode="same")


def _diffcorr(z, sps, p):
    """Differentielle Präambel-Korrelation. Metrik 0..1, Peak bei Index n0 + sps."""
    d = np.zeros_like(z)
    d[sps:] = z[sps:] * np.conj(z[:-sps])
    dp = p[1:] * p[:-1]
    h = np.zeros((len(dp) - 1) * sps + 1)
    h[::sps] = dp
    if len(d) < len(h):
        return np.zeros(0), np.zeros(0, complex)
    C = fftconvolve(d, h[::-1], mode="valid")
    E = fftconvolve(np.abs(d), np.abs(h)[::-1], mode="valid")
    # Nicht nur auf die Energie im Fenster normieren: Am Burst-Ende überlappt das Fenster
    # nur mit wenigen Symbolen, das ergäbe Scheintreffer. Mindestens die halbe Energie
    # einer vollständigen Präambel ansetzen.
    e_ref = len(dp) * np.percentile(np.abs(d), 95)
    M = np.abs(C) / np.maximum(E, 0.5 * e_ref + 1e-30)
    return np.minimum(M, 1.0), C


def _find_peaks(M, threshold, min_dist):
    idx = np.flatnonzero(M > threshold)
    peaks = []
    for i in idx[np.argsort(-M[idx])]:
        if all(abs(i - q) >= min_dist for q in peaks):
            peaks.append(int(i))
    return sorted(peaks)


def analyze(y: np.ndarray, cfg: Config, data: np.ndarray, threshold: float = 0.5, max_bursts: int = 200):
    """Aufnahme (N x 2: I, Q) auswerten.

    -> dict mit 'f', 'psd' (Spektrum der Aufnahme), 'fc_global', 'bursts' (Liste),
       'skipped' (Anzahl unvollständiger Bursts)
    """
    err = cfg.check()
    if err:
        raise ValueError(err)
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 2 or y.shape[1] < 2:
        raise ValueError("Es wird eine Stereo-Aufnahme (I links, Q rechts) benötigt")
    r = y[:, 0] + 1j * y[:, 1]
    r = r - np.mean(r)                             # Gleichanteil entfernen
    fs, sps = cfg.fs, cfg.sps
    p = sequences.preamble(cfg.preamble_len)
    s_tx = tx_symbols(cfg, data)
    h = rrc_taps(cfg.rolloff, sps, cfg.rrc_span)

    f, P = _psd(r, fs)
    fc0, _ = _coarse_center(f, P, cfg)
    z = _mixdown_mf(r, fc0, fs, h)
    M, _ = _diffcorr(z, sps, p)
    res = {"f": f, "psd": P, "fc_global": fc0, "metric": M, "bursts": [], "skipped": 0,
           "peak_metric": float(M.max()) if len(M) else 0.0}
    if not len(M):
        return res
    frame = len(s_tx) * sps
    for m in _find_peaks(M, threshold, int(0.8 * frame))[:max_bursts]:
        b = _analyze_burst(r, m - sps, cfg, data, s_tx, p, h)
        if b is None:
            res["skipped"] += 1
        else:
            res["bursts"].append(b)
    return res


def _analyze_burst(r, n0_glob, cfg, data, s_tx, p, h):
    fs, sps, rs, M_ = cfg.fs, cfg.sps, cfg.rs, cfg.M
    N, L = len(s_tx), len(p)
    if n0_glob < 0 or n0_glob + (N - 1) * sps + 2 * sps >= len(r):
        return None                                    # Burst nicht vollständig aufgenommen
    pad = len(h) + 2 * sps
    a, b = max(0, n0_glob - pad), min(len(r), n0_glob + N * sps + pad)
    seg = r[a:b]

    # 1) grobe Frequenz aus dem Spektrum dieses Bursts
    f, P = _psd(seg, fs)
    fc, snr_spec = _coarse_center(f, P, cfg)
    # 2) Mischen + Matched Filter, 3) Präambel -> Zeit und Feinfrequenz
    z = _mixdown_mf(seg, fc, fs, h, n_offset=a)
    Mt, C = _diffcorr(z, sps, p)
    exp_m = n0_glob - a + sps
    lo, hi = max(0, exp_m - 3 * sps), min(len(Mt), exp_m + 3 * sps)
    if hi <= lo:
        return None
    m = lo + int(np.argmax(Mt[lo:hi]))
    f_fine = float(np.angle(C[m]) / (2 * np.pi) * rs)
    n0 = m - sps

    # 4) Symbole abtasten, Abtastzeitpunkt blockweise nachführen
    idx = np.empty(N, dtype=np.int64)
    pos, blk = n0, 16
    for k0 in range(0, N, blk):
        k1 = min(k0 + blk, N)
        if cfg.track_timing and k0 > 0:
            best, best_e = 0, -1.0
            for dl in (-1, 0, 1):
                ii = pos + dl + np.arange(k1 - k0) * sps
                ii = ii[(ii >= 0) & (ii < len(z))]
                e = float(np.sum(np.abs(z[ii]) ** 2))
                if e > best_e:
                    best, best_e = dl, e
            pos += best
        idx[k0:k1] = pos + np.arange(k1 - k0) * sps
        pos += (k1 - k0) * sps
    if idx[-1] >= len(z):
        return None
    zk = z[idx]
    t = (a + idx) / fs                                  # absolute Zeit [s]
    tt = t - t[0]

    # 5) Phase Empfang relativ zum Sendesymbol
    e = zk * np.conj(s_tx)
    phi = np.unwrap(np.angle(e * np.exp(-2j * np.pi * f_fine * tt))) + 2 * np.pi * f_fine * tt
    lin = np.polyfit(tt, phi, 1)
    quad = np.polyfit(tt, phi, 2) if N > 3 else np.array([0.0, *lin])
    f_res = lin[0] / (2 * np.pi)
    f_off = fc - cfg.f_if + f_res                       # gesamter Frequenzversatz
    drift = quad[0] / np.pi                             # Hz/s
    phi_res = phi - np.polyval(lin, tt)
    pn_rms = float(np.degrees(np.std(phi - np.polyval(quad, tt))))
    # Gesamte Phasendifferenz Sender-Empfänger (inkl. grober Mischung), ab Burst-Beginn
    phi_total = phi + 2 * np.pi * (fc - cfg.f_if) * tt
    phi_total -= phi_total[0]
    # Momentanfrequenz (geglätteter Phasenrest abgeleitet)
    W = max(5, N // 60)
    sm = np.convolve(phi_res, np.ones(W) / W, mode="same")
    f_inst = f_off + np.gradient(sm, tt) / (2 * np.pi)
    f_inst[:W] = np.nan                                 # Ränder: Glättung unvollständig
    f_inst[-W:] = np.nan

    # Konstellation nach voller Korrektur, SNR
    gain = float(np.mean(np.abs(zk)))
    const = zk * np.exp(-1j * np.polyval(quad, tt)) / max(gain, 1e-30)
    evm = float(np.mean(np.abs(const - s_tx) ** 2))
    snr_db = float(-10 * np.log10(max(evm, 1e-12)))

    # DPSK-Entscheidung: ohne Korrektur (Mischung nur mit f_if) und mit Frequenzkorrektur
    step = 2 * np.pi / M_
    dz = zk[1:] * np.conj(zk[:-1])
    dphi_raw = np.angle(dz) + 2 * np.pi * (fc - cfg.f_if) / rs
    dphi_corr = dphi_raw - 2 * np.pi * f_off / rs
    dphi_tx = np.angle(s_tx[1:] * np.conj(s_tx[:-1]))
    dec = lambda x: np.mod(np.round(x / step), M_).astype(np.int64)
    sl = slice(L - 1, N - 1)                            # Übergänge der Datensymbole
    dec_raw, dec_corr = dec(dphi_raw[sl]), dec(dphi_corr[sl])
    data = np.asarray(data, dtype=np.int64)
    err_raw, err_corr = dec_raw != data, dec_corr != data
    bits_tx = sequences.symbols_to_bits(data, M_)
    ber = float(np.mean(sequences.symbols_to_bits(dec_corr, M_) != bits_tx)) if len(data) else 0.0
    ber_raw = float(np.mean(sequences.symbols_to_bits(dec_raw, M_) != bits_tx)) if len(data) else 0.0

    return {
        "t": t, "tt": tt, "k": np.arange(N), "n_preamble": L, "z": zk, "s_tx": s_tx,
        "phi_total_cycles": phi_total / (2 * np.pi), "phi_res_deg": np.degrees(phi_res),
        "phi_fit_quad_deg": np.degrees(np.polyval(quad, tt) - np.polyval(lin, tt)),
        "f_inst": f_inst, "const": const,
        "dphi_raw_deg": _wrap_deg(np.degrees(dphi_raw)), "dphi_corr_deg": _wrap_deg(np.degrees(dphi_corr)),
        "dphi_tx_deg": _wrap_deg(np.degrees(dphi_tx)),
        "diff_raw": np.abs(dz) * np.exp(1j * dphi_raw) / max(gain ** 2, 1e-30),
        "diff_corr": np.abs(dz) * np.exp(1j * dphi_corr) / max(gain ** 2, 1e-30),
        "err_raw": err_raw, "err_corr": err_corr, "dec_corr": dec_corr,
        "amp": np.abs(zk) / max(gain, 1e-30),
        "stats": {
            "t_start": float(t[0]), "duration": float(tt[-1]), "metric": float(Mt[m]),
            "fc": float(fc), "f_coarse": float(fc - cfg.f_if), "f_fine": f_fine, "f_off": float(f_off),
            "drift_hz_s": float(drift), "phase_noise_deg": pn_rms,
            "rot_per_symbol_deg": float(_wrap_deg(360 * f_off / rs)),
            "snr_db": snr_db, "snr_spec_db": snr_spec,
            "ser_raw": float(np.mean(err_raw)) if len(data) else 0.0,
            "ser_corr": float(np.mean(err_corr)) if len(data) else 0.0,
            "ber_raw": ber_raw, "ber_corr": ber,
            "n_err_raw": int(np.sum(err_raw)), "n_err_corr": int(np.sum(err_corr)),
            "n_data": int(len(data)),
        },
    }


def raw_view(y: np.ndarray, cfg: Config, nperseg: int = 1024):
    """Rohsignal-Analyse, unabhängig von der Burst-Erkennung.

    -> dict: Spektrogramm (t, f, S in dB) und Frequenz der stärksten Spektrallinie
       relativ zur ZF über die Zeit (zeigt Versatz, Drift, Sprünge, Wobbeln der Oszillatoren).
    """
    from scipy.signal import spectrogram
    y = np.asarray(y, dtype=np.float64)
    r = y[:, 0] + 1j * y[:, 1]
    r = r - np.mean(r)
    nperseg = int(min(nperseg, max(64, len(r) // 8)))
    f, t, S = spectrogram(r, cfg.fs, nperseg=nperseg, noverlap=nperseg * 3 // 4,
                          return_onesided=False, mode="psd")
    f = np.fft.fftshift(f)
    S = np.fft.fftshift(S, axes=0)
    S[np.abs(f) < 2 * cfg.fs / nperseg, :] = np.median(S)        # Gleichanteil ausblenden
    i = np.argmax(S, axis=0)
    df = f[1] - f[0]
    # Parabel-Interpolation für feinere Frequenz
    ii = np.clip(i, 1, len(f) - 2)
    a, b, c = (np.log(S[ii - 1, np.arange(S.shape[1])] + 1e-30), np.log(S[ii, np.arange(S.shape[1])] + 1e-30),
               np.log(S[ii + 1, np.arange(S.shape[1])] + 1e-30))
    den = a - 2 * b + c
    delta = np.where(np.abs(den) > 1e-12, 0.5 * (a - c) / den, 0.0)
    f_peak = f[ii] + np.clip(delta, -0.5, 0.5) * df
    level = 10 * np.log10(S.max(axis=0) / np.median(S) + 1e-30)
    return {"t": t, "f": f, "S_db": 10 * np.log10(S + 1e-30), "f_peak_rel": f_peak - cfg.f_if,
            "peak_level_db": level, "r": r}


def summary(b: dict, cfg: Config) -> str:
    s = b["stats"]
    lines = [
        "Burst bei %.3f s, Dauer %.2f s, Präambel-Metrik %.2f" % (s["t_start"], s["duration"], s["metric"]),
        "Frequenzversatz gesamt: %+.2f Hz  (grob %+.1f Hz, fein %+.2f Hz)" % (s["f_off"], s["f_coarse"], s["f_off"] - s["f_coarse"]),
        "  -> Phasendrehung je Symbol: %+.1f°  (Entscheidungsgrenze DPSK: ±%.0f°)" % (s["rot_per_symbol_deg"], 180 / cfg.M),
        "Frequenzdrift: %+.3f Hz/s" % s["drift_hz_s"],
        "Phasenrauschen (Rest nach Drift-Abzug): %.2f° rms" % s["phase_noise_deg"],
        "SNR (Symbole): %.1f dB" % s["snr_db"],
        "Symbolfehler ohne Frequenzkorrektur: %d / %d  (SER %.3f, BER %.3f)" % (s["n_err_raw"], s["n_data"], s["ser_raw"], s["ber_raw"]),
        "Symbolfehler mit Frequenzkorrektur:  %d / %d  (SER %.3f, BER %.3f)" % (s["n_err_corr"], s["n_data"], s["ser_corr"], s["ber_corr"]),
    ]
    return "\n".join(lines)
