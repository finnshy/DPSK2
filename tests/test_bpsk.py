"""Tests ohne Hardware.  Ausführen:  py -3.9 -m pytest -v tests"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bpsk  # noqa: E402


def run(df=0.0, drift=0.0, pattern="Zufall", snr_db=25.0):
    cfg = bpsk.Config(pattern=pattern)
    tx = bpsk.modulate(cfg, bpsk.make_bits(cfg))
    return bpsk.analyze(bpsk.simulate(tx, cfg, df=df, drift=drift, phase0_deg=60, snr_db=snr_db), cfg)


def test_sender_bpsk():
    cfg = bpsk.Config(n_symbols=4, pattern="Eigene Bits", bits="1 0 0 1")
    tx = bpsk.modulate(cfg, bpsk.make_bits(cfg), silence_s=0)
    assert np.all(tx[:, 1] == 0)                                    # Q = 0
    assert list(tx[::cfg.sps, 0] / cfg.amplitude) == [1, -1, -1, 1]   # I = ±1


@pytest.mark.parametrize("df", [-11000.0, -3200.0, -435.0, 0.0, 12.5, 980.0, 7000.0])
def test_frequency_offset(df):
    res = run(df)
    assert res["burst_found"]
    assert abs(res["df"] - df) < 0.5


@pytest.mark.parametrize("pattern", bpsk.PATTERNS)
def test_any_bit_pattern(pattern):
    assert abs(run(1500.0, pattern=pattern)["df"] - 1500.0) < 0.5


def test_corrected_constellation_has_two_points():
    res = run(2345.0)
    c = res["sym_corr"] ** 2                       # ±1 -> 1: beide Punkte fallen zusammen
    assert np.abs(np.mean(c / np.abs(c))) > 0.95   # mit Korrektur: feste Phase
    c = res["sym_raw"][np.abs(res["sym_raw"]) > 1e-3] ** 2
    assert np.abs(np.mean(c / np.abs(c))) < 0.2    # ohne Korrektur: Phase läuft um


def test_drift_and_frequency_over_time():
    res = run(500.0, drift=100.0)
    assert abs(res["drift"] - 100.0) < 3
    f = res["f_inst"][~np.isnan(res["f_inst"])]
    assert f[-1] - f[0] > 150                        # 2 s * 100 Hz/s = 200 Hz Anstieg


def test_noise_only_does_not_crash():
    cfg = bpsk.Config()
    y = (np.random.default_rng(0).standard_normal((48000, 2)) * 0.01).astype(np.float32)
    assert "df" in bpsk.analyze(y, cfg)
