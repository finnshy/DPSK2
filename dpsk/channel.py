"""Kanalsimulation für Tests ohne Hardware: Frequenzversatz, Frequenzdrift,
Phasenrauschen (Random Walk), Taktabweichung, Gleichanteil (LO-Durchgriff), Rauschen."""
from math import gcd

import numpy as np
from scipy.signal import resample_poly

from .config import Config


def simulate(tx: np.ndarray, cfg: Config, snr_db: float = 30.0, cfo_hz: float = 0.0,
             drift_hz_s: float = 0.0, phase_noise_deg: float = 0.0, sco_ppm: float = 0.0,
             delay_s: float = 0.2, dc: complex = 0.0, gain: float = 1.0, phase0_deg: float = 0.0,
             seed: int = 0) -> np.ndarray:
    """tx: Stereo [I, Q]. snr_db = Es/N0 (SNR je Symbol nach dem Matched Filter).
    phase_noise_deg: Standardabweichung des Phasen-Random-Walks je Symbol."""
    rng = np.random.default_rng(seed)
    x = tx[:, 0].astype(np.float64) + 1j * tx[:, 1]
    n = np.arange(len(x))
    t = n / cfg.fs
    ph = 2 * np.pi * (cfo_hz * t + 0.5 * drift_hz_s * t ** 2) + np.radians(phase0_deg)
    if phase_noise_deg:
        sigma = np.radians(phase_noise_deg) / np.sqrt(cfg.sps)
        ph = ph + np.cumsum(rng.standard_normal(len(x)) * sigma)
    y = x * np.exp(1j * ph)
    if sco_ppm:
        up = 1_000_000
        down = int(round(up * (1 + sco_ppm * 1e-6)))
        g = gcd(up, down)
        y = resample_poly(y, up // g, down // g)
    y = np.concatenate([np.zeros(int(delay_s * cfg.fs), complex), y * gain,
                        np.zeros(int(0.1 * cfg.fs), complex)])
    p = np.mean(np.abs(x[np.abs(x) > 0]) ** 2) * gain ** 2
    var = p * cfg.sps / 10 ** (snr_db / 10)          # komplexe Rauschvarianz je Abtastwert
    y = y + dc + np.sqrt(var / 2) * (rng.standard_normal(len(y)) + 1j * rng.standard_normal(len(y)))
    return np.stack([y.real, y.imag], axis=1).astype(np.float32)
