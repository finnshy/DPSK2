"""Hardwaretest: Bursts senden und gleichzeitig aufnehmen, dann auswerten.

    py -3.9 tests/hw_test.py --list
    py -3.9 tests/hw_test.py --out 24 --in 25                       # 3 Bursts, Standardeinstellungen
    py -3.9 tests/hw_test.py --out 24 --in 25 --bursts 10 --preset "Nullen (konstante Phase)"
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpsk import Config, audio_io, modem, sequences  # noqa: E402


def run(cfg, out_dev, in_dev, n_bursts, save=None):
    data = sequences.build(cfg)
    tx, info = modem.modulate(cfg, data, silence_s=cfg.pause_s / 2)
    sig = np.concatenate([tx] * n_bursts)
    rec = audio_io.Recorder(cfg.fs, 2, in_dev, max_seconds=len(sig) / cfg.fs + 1.5)
    rec.start()
    time.sleep(0.3)
    audio_io.play(sig, cfg.fs, out_dev)
    time.sleep(0.4)
    rx = rec.stop()
    if save:
        audio_io.write_wav(save, rx, cfg.fs)
    return modem.analyze(rx, cfg, data), rx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=int)
    ap.add_argument("--in", dest="inp", type=int)
    ap.add_argument("--bursts", type=int, default=3)
    ap.add_argument("--mod", default="DQPSK")
    ap.add_argument("--rate", type=float, default=1000)
    ap.add_argument("--amp", type=float, default=0.2)
    ap.add_argument("--fif", type=float, default=3000)
    ap.add_argument("--preset", default=sequences.PRESETS[0])
    ap.add_argument("--len", type=int, default=1000)
    ap.add_argument("--save", help="Rohaufnahme als WAV speichern")
    a = ap.parse_args()
    if a.list:
        print(audio_io.device_table())
        return
    cfg = Config(modulation=a.mod, symbol_rate=a.rate, amplitude=a.amp, f_if=a.fif,
                 sequence_preset=a.preset, seq_len=a.len)
    res, rx = run(cfg, a.out, a.inp, a.bursts, a.save)
    print("Eingangspegel: Spitze %.3f, rms %.4f" % (np.abs(rx).max(), np.sqrt(np.mean(rx ** 2))))
    print("%d Burst(s) gefunden, %d unvollständig, max. Präambel-Metrik %.2f"
          % (len(res["bursts"]), res["skipped"], res["peak_metric"]))
    for i, b in enumerate(res["bursts"]):
        print("\n--- Burst %d ---\n%s" % (i + 1, modem.summary(b, cfg)))


if __name__ == "__main__":
    main()
