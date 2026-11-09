"""Tests ohne Hardware.  Ausführen:  py -3.9 -m pytest -v tests"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bpsk  # noqa: E402


def run(df=0.0, drift=0.0, pattern="Zufall", snr_db=25.0, delay=0, sco_ppm=0.0, phase0=60, **kw):
    cfg = bpsk.Config(pattern=pattern, **kw)
    tx = bpsk.modulate(cfg, bpsk.make_bits(cfg))
    rx = bpsk.simulate(tx, cfg, df=df, drift=drift, phase0_deg=phase0, snr_db=snr_db, delay=delay, sco_ppm=sco_ppm)
    return bpsk.analyze(rx, cfg), cfg


def test_sender_barker_and_bpsk():
    cfg = bpsk.Config(n_symbols=4, pattern="Eigene Bits", bits="1 0 0 1")
    tx = bpsk.modulate(cfg, bpsk.make_bits(cfg), silence_s=0)
    assert np.all(tx[:, 1] == 0)                                          # Q = 0
    sym = tx[::cfg.sps, 0] / cfg.amplitude
    assert list(sym[:13]) == list(bpsk.BARKER13)                          # Präambel
    assert list(sym[13:]) == [1, -1, -1, 1]                               # Daten


def test_barker_autocorrelation():
    ac = np.correlate(bpsk.BARKER13, bpsk.BARKER13, mode="full")
    assert ac.max() == 13 and np.max(np.abs(np.delete(ac, 12))) == 1     # Nebenmaxima höchstens 1


@pytest.mark.parametrize("df", [-11000.0, -3200.0, -435.0, 0.0, 12.5, 980.0, 7000.0])
@pytest.mark.parametrize("phase0", [0, 100, 200])
def test_offset_sync_and_bits(df, phase0):
    """Offset genau, Barker auf den Abtastwert genau, Vorzeichen richtig, alle Bits richtig."""
    delay = 1234
    res, cfg = run(df, phase0=phase0, delay=delay)
    assert abs(res["df"] - df) < 0.5
    true_start = delay + int(0.2 * cfg.fs)                                # Verzögerung + Stille
    assert abs(res["t0"] * cfg.fs + res["n0"] - true_start) <= 1
    assert res["barker_ok"]
    assert bpsk.bit_errors(res, cfg) == (0, cfg.n_symbols)


@pytest.mark.parametrize("pattern", bpsk.PATTERNS)
def test_any_bit_pattern(pattern):
    res, cfg = run(1500.0, pattern=pattern)
    assert abs(res["df"] - 1500.0) < 0.5 and bpsk.bit_errors(res, cfg)[0] == 0


def test_timing_recovery_tracks_clock_offset():
    """300 ppm Taktabweichung: nach 2 s ist das starre Raster ~29 Abtastwerte (0,6 Symbole)
    daneben. Mit Nachführung bleiben alle Bits richtig, ohne nicht."""
    res, cfg = run(700.0, sco_ppm=300, n_symbols=2000)
    assert bpsk.bit_errors(res, cfg)[0] == 0
    assert res["timing_offset"][-1] < -20                                 # Fenster wurde nachgeführt
    res0, cfg0 = run(700.0, sco_ppm=300, n_symbols=2000, timing_gain=0.0)
    assert bpsk.bit_errors(res0, cfg0)[0] > 50


def test_drift_and_frequency_over_time():
    res, _ = run(500.0, drift=100.0)
    assert abs(res["drift"] - 100.0) < 3
    f = res["f_inst"][~np.isnan(res["f_inst"])]
    assert f[-1] - f[0] > 150                                             # ~2 s * 100 Hz/s


def test_noise_only_does_not_crash():
    cfg = bpsk.Config()
    y = (np.random.default_rng(0).standard_normal((48000, 2)) * 0.01).astype(np.float32)
    assert "df" in bpsk.analyze(y, cfg)
