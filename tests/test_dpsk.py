"""Modultests (ohne Hardware).  Ausführen:  py -3.9 -m pytest -v tests"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpsk import Config, channel, modem, sequences  # noqa: E402


# --------------------------------------------------------------------------- Bausteine
def test_mseq_autocorrelation():
    p = sequences.preamble(63)
    ac = [np.dot(p, np.roll(p, s)) for s in range(1, 63)]
    assert np.allclose(ac, -1)                       # ideale periodische Autokorrelation


def test_rrc_nyquist():
    """Sende-RRC * Empfangs-RRC = Raised Cosine: keine Intersymbol-Interferenz."""
    h = modem.rrc_taps(0.35, 48, 10)
    g = np.convolve(h, h)
    c = len(g) // 2
    assert abs(g[c] - 1) < 1e-3
    assert np.max(np.abs(g[c + 48::48][:4])) < 1e-2


@pytest.mark.parametrize("M", [2, 4])
def test_bits_symbols_roundtrip(M):
    bits = np.random.default_rng(0).integers(0, 2, 400).astype(np.uint8)
    assert np.array_equal(sequences.symbols_to_bits(sequences.bits_to_symbols(bits, M), M), bits)


@pytest.mark.parametrize("preset,mod,expect", [
    ("Nullen (konstante Phase)", "DQPSK", 0),
    ("Phasensprung 180° je Symbol", "DQPSK", 2),
    ("Phasensprung 180° je Symbol", "DBPSK", 1),
    ("Phasenrampe +90° je Symbol", "DQPSK", 1),
])
def test_presets(preset, mod, expect):
    seq = sequences.build(Config(modulation=mod, sequence_preset=preset, seq_len=50))
    assert len(seq) == 50 and np.all(seq == expect)


def test_custom_sequences():
    cfg = Config(sequence_preset="Eigene Symbole", sequence_text="0, 1 2;3", repetitions=3)
    assert list(sequences.build(cfg)) == [0, 1, 2, 3] * 3
    cfg = Config(sequence_preset="Eigene Bits", sequence_text="00 01 11 10")
    assert list(sequences.build(cfg)) == [0, 1, 2, 3]
    cfg = Config(sequence_preset="Text (ASCII)", sequence_text="A")       # 01000001
    assert list(sequences.build(cfg)) == [1, 0, 0, 1]
    with pytest.raises(ValueError):
        sequences.build(Config(sequence_preset="Eigene Symbole", sequence_text="0 5"))
    with pytest.raises(ValueError):
        sequences.build(Config(modulation="DBPSK", sequence_preset="Phasenrampe +90° je Symbol"))


def test_tx_symbols_are_differential():
    cfg = Config(modulation="DQPSK")
    data = np.array([0, 1, 2, 3, 1])
    s = modem.tx_symbols(cfg, data)
    inc = np.angle(s[cfg.preamble_len:] * np.conj(s[cfg.preamble_len - 1:-1]), deg=True)
    assert np.allclose(np.mod(inc, 360), [0, 90, 180, 270, 90], atol=1e-9)


# --------------------------------------------------------------------------- Ganze Kette
def _run(cfg, data, **ch):
    tx, _ = modem.modulate(cfg, data)
    rx = channel.simulate(tx, cfg, **ch)
    return modem.analyze(rx, cfg, data)


def test_ideal():
    cfg = Config()
    data = sequences.build(cfg)
    res = _run(cfg, data, snr_db=40)
    assert len(res["bursts"]) == 1
    s = res["bursts"][0]["stats"]
    assert s["n_err_corr"] == 0 and s["n_err_raw"] == 0
    assert abs(s["f_off"]) < 0.5 and s["snr_db"] > 30


@pytest.mark.parametrize("mod", ["DBPSK", "DQPSK"])
@pytest.mark.parametrize("cfo", [-20000.0, -7300.0, -3000.0, -480.0, 0.0, 137.0, 2500.0, 15000.0, 19500.0])
def test_large_frequency_offset(mod, cfo):
    """Frequenzversatz bis ±20 kHz wird gefunden und auf < 1 Hz gemessen.
    -3000 Hz legt das Signal genau auf 0 Hz (Gleichanteil wird entfernt)."""
    cfg = Config(modulation=mod)
    data = sequences.build(cfg)
    res = _run(cfg, data, snr_db=20, cfo_hz=cfo, phase0_deg=77, seed=3)
    assert len(res["bursts"]) == 1
    s = res["bursts"][0]["stats"]
    assert abs(s["f_off"] - cfo) < 1.0, s
    assert s["n_err_corr"] == 0


def test_raw_vs_corrected_decisions():
    """Ohne Frequenzkorrektur dreht ein Versatz jede Differenzphase um 360°·f/Rs.
    Bei 300 Hz und 1000 Bd sind das 108° -> DQPSK falsch, mit Korrektur richtig."""
    cfg = Config(modulation="DQPSK")
    data = sequences.build(cfg)
    s = _run(cfg, data, snr_db=25, cfo_hz=300)["bursts"][0]["stats"]
    assert abs(s["rot_per_symbol_deg"] - 108) < 1
    assert s["ser_raw"] > 0.9 and s["n_err_corr"] == 0
    s = _run(cfg, data, snr_db=25, cfo_hz=30)["bursts"][0]["stats"]   # 10.8° -> geht auch ohne
    assert s["n_err_raw"] == 0


def test_drift_and_phase_noise():
    cfg = Config(sequence_preset="Nullen (konstante Phase)", seq_len=4000)
    data = sequences.build(cfg)
    s = _run(cfg, data, snr_db=35, cfo_hz=820, drift_hz_s=40)["bursts"][0]["stats"]
    assert abs(s["drift_hz_s"] - 40) < 2
    # mittlere Frequenz über den Burst = 820 + 40 * (0,2 s Stille vor dem Burst + Dauer/2)
    assert abs(s["f_off"] - (820 + 40 * (0.2 + s["duration"] / 2))) < 1
    s0 = _run(cfg, data, snr_db=35, cfo_hz=820)["bursts"][0]["stats"]
    s1 = _run(cfg, data, snr_db=35, cfo_hz=820, phase_noise_deg=2.0, seed=5)["bursts"][0]["stats"]
    assert s1["phase_noise_deg"] > 3 * s0["phase_noise_deg"]


def test_multiple_bursts_and_sco():
    cfg = Config(seq_len=300)
    data = sequences.build(cfg)
    tx, _ = modem.modulate(cfg, data)
    rx = channel.simulate(np.concatenate([tx] * 4), cfg, snr_db=25, cfo_hz=-1234, sco_ppm=80, seed=2)
    res = modem.analyze(rx, cfg, data)
    assert len(res["bursts"]) == 4
    for b in res["bursts"]:
        assert b["stats"]["n_err_corr"] == 0
        assert abs(b["stats"]["f_off"] + 1234) < 1.5


def test_partial_burst_is_skipped():
    cfg = Config(seq_len=300)
    data = sequences.build(cfg)
    tx, _ = modem.modulate(cfg, data, silence_s=0.05)
    rx = channel.simulate(tx[: int(len(tx) * 0.6)], cfg, snr_db=30, delay_s=0.05)
    res = modem.analyze(rx, cfg, data)
    assert len(res["bursts"]) == 0 and res["skipped"] == 1


def test_noise_only():
    cfg = Config()
    rng = np.random.default_rng(0)
    y = (rng.standard_normal((48000 * 2, 2)) * 0.01).astype(np.float32)
    res = modem.analyze(y, cfg, sequences.build(cfg))
    assert len(res["bursts"]) == 0


def test_raw_view_tracks_offset():
    """Rohsignal-Ansicht: stärkste Linie folgt dem Frequenzversatz eines Trägers."""
    cfg = Config(sequence_preset="Nullen (konstante Phase)", seq_len=3000)
    tx, _ = modem.modulate(cfg, sequences.build(cfg))
    rx = channel.simulate(tx, cfg, snr_db=30, cfo_hz=-1650)
    rv = modem.raw_view(rx, cfg)
    ok = rv["peak_level_db"] > 15
    assert abs(np.median(rv["f_peak_rel"][ok]) + 1650) < 15
