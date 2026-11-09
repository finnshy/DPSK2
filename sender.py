"""DPSK-Sender mit GUI: Präambel + definierte Symbolfolge als I/Q über die Soundkarte.

Start:  py -3.9 sender.py
CLI:    py -3.9 sender.py --wav tx.wav [--config dpsk_config.json]
        py -3.9 sender.py --play --out-dev 24 [--loop]
"""
import argparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from dpsk import Config, audio_io, modem, sequences
from dpsk.gui_common import DeviceCombo, PlotTabs, SequenceFrame, SettingsFrame, config_buttons, run_bg


def build_signal(cfg: Config, loop_pause: bool = False):
    data = sequences.build(cfg)
    tx, info = modem.modulate(cfg, data, silence_s=cfg.pause_s / 2 if loop_pause else 0.2)
    return data, tx, info


class SenderApp:
    def __init__(self, root):
        self.root = root
        root.title("DPSK-Sender")
        left = ttk.Frame(root)
        left.pack(side="left", fill="y", padx=6, pady=6)

        self.device = DeviceCombo(left, "output", "Ausgang (→ I/Q-Modulator, links = I, rechts = Q)")
        self.device.pack(fill="x", pady=3)
        self.settings = SettingsFrame(left, "sender")
        self.settings.pack(fill="x", pady=3)
        self.seq = SequenceFrame(left)
        self.seq.pack(fill="x", pady=3)
        config_buttons(left, self.get_cfg, self.set_cfg).pack(fill="x", pady=3)

        btns = ttk.LabelFrame(left, text="Senden")
        btns.pack(fill="x", pady=3)
        ttk.Button(btns, text="Einmal senden", command=lambda: self.send(False)).pack(fill="x", padx=4, pady=1)
        ttk.Button(btns, text="Dauersenden (Burst + Pause, endlos)",
                   command=lambda: self.send(True)).pack(fill="x", padx=4, pady=1)
        ttk.Button(btns, text="Stopp", command=self.stop).pack(fill="x", padx=4, pady=1)
        ttk.Button(btns, text="Als WAV speichern", command=self.save_wav).pack(fill="x", padx=4, pady=1)

        self.status = tk.StringVar(value="Bereit." if audio_io.available() else "sounddevice fehlt: nur WAV-Export.")
        ttk.Label(left, textvariable=self.status, wraplength=340, justify="left").pack(fill="x", pady=4)

        self.plots = PlotTabs(root, ["Sendesignal"])
        self.plots.pack(side="right", fill="both", expand=True)

    def get_cfg(self) -> Config:
        cfg = self.seq.apply(self.settings.apply(Config()))
        err = cfg.check()
        if err:
            raise ValueError(err)
        return cfg

    def set_cfg(self, cfg: Config):
        self.settings.load(cfg)
        self.seq.load(cfg)

    def _err(self, e):
        self.status.set("Fehler: %s" % e)
        messagebox.showerror("Fehler", str(e))

    def _prepare(self, loop=False):
        cfg = self.get_cfg()
        data, tx, info = build_signal(cfg, loop)
        self.seq.show(data, cfg.M)
        self._plot(cfg, data, tx, info)
        self.status.set("%d Präambel- + %d Datensymbole, %.2f s, %.1f Bd, %.0f bit/s, Band %.0f Hz um %.0f Hz"
                        % (info["n_preamble"], info["n_data"], info["duration_s"], info["rs"],
                           info["bitrate"], info["bandwidth"], cfg.f_if))
        return cfg, tx

    def send(self, loop):
        try:
            cfg, tx = self._prepare(loop)
        except Exception as e:  # noqa: BLE001
            return self._err(e)
        dev = self.device.device()
        if loop:
            try:
                audio_io.play(tx, cfg.fs, dev, blocking=False, loop=True)
            except Exception as e:  # noqa: BLE001
                return self._err(e)
            self.status.set(self.status.get() + "\nDauersenden läuft … (Stopp beendet)")
            return
        self.status.set(self.status.get() + "\nSende …")
        run_bg(self.root, lambda: audio_io.play(tx, cfg.fs, dev),
               lambda r: self.status.set(self.status.get().replace("Sende …", "Gesendet.")), self._err)

    def stop(self):
        audio_io.stop()
        self.status.set(self.status.get().replace("Dauersenden läuft … (Stopp beendet)", "Gestoppt."))

    def save_wav(self):
        try:
            cfg, tx = self._prepare()
        except Exception as e:  # noqa: BLE001
            return self._err(e)
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="dpsk_tx.wav")
        if p:
            audio_io.write_wav(p, tx, cfg.fs)
            self.status.set(self.status.get() + "\nGespeichert: " + p)

    def _plot(self, cfg, data, tx, info):
        a = self.plots.axes("Sendesignal")
        s = modem.tx_symbols(cfg, data)
        L = cfg.preamble_len
        k = np.arange(len(s))
        ph = np.degrees(np.angle(s))
        a[0].step(k, ph, where="post", lw=0.8)
        a[0].axvspan(0, L, color="orange", alpha=0.15, label="Präambel")
        a[0].set_title("Absolute Phase der Sendesymbole [°]")
        a[0].set_xlabel("Symbol")
        a[0].set_yticks([-180, -90, 0, 90, 180])
        a[0].legend(fontsize=7, loc="upper right")
        a[0].set_xlim(0, min(len(s), L + 200))
        inc = np.degrees(np.angle(s[1:] * np.conj(s[:-1])))
        inc = np.mod(inc + 1e-9, 360)
        a[1].plot(k[1:], inc, ".", ms=3)
        a[1].axvspan(0, L, color="orange", alpha=0.15)
        a[1].set_title("Phasenänderung je Symbol [°] (das, was DPSK überträgt)")
        a[1].set_xlabel("Symbol")
        a[1].set_yticks(range(0, 360, 360 // cfg.M))
        a[1].set_xlim(0, min(len(s), L + 200))
        x = tx[:, 0] + 1j * tx[:, 1]
        x = x[np.abs(x) > 0]
        n = min(len(x), 1 << 16)
        X = np.fft.fftshift(np.abs(np.fft.fft(x[:n] * np.hanning(n)))) + 1e-12
        f = np.fft.fftshift(np.fft.fftfreq(n, 1 / cfg.fs))
        a[2].plot(f / 1000, 20 * np.log10(X / X.max()), lw=0.5)
        a[2].axvline(cfg.f_if / 1000, color="r", ls="--", lw=0.8)
        a[2].set_ylim(-80, 5)
        a[2].set_title("Spektrum I/Q [dB], rot = ZF")
        a[2].set_xlabel("f [kHz]")
        a[3].plot(s.real, s.imag, "o")
        a[3].set_aspect("equal")
        a[3].set_xlim(-1.5, 1.5)
        a[3].set_ylim(-1.5, 1.5)
        a[3].grid(True)
        a[3].set_title("Sendesymbole (vor Impulsformung)")
        self.plots.draw()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="JSON-Konfiguration")
    ap.add_argument("--wav", help="Sendesignal als WAV speichern")
    ap.add_argument("--play", action="store_true", help="über die Soundkarte senden")
    ap.add_argument("--loop", action="store_true", help="mit --play: endlos wiederholen (Strg+C beendet)")
    ap.add_argument("--out-dev", type=int, help="Ausgabegerät (Nummer, siehe --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        print(audio_io.device_table())
        return
    if not (args.wav or args.play):
        root = tk.Tk()
        SenderApp(root)
        root.mainloop()
        return
    cfg = Config.from_json(open(args.config, encoding="utf-8").read()) if args.config else Config()
    data, tx, info = build_signal(cfg, args.loop)
    print("%d Präambel- + %d Datensymbole, %.2f s" % (info["n_preamble"], info["n_data"], info["duration_s"]))
    if args.wav:
        audio_io.write_wav(args.wav, tx, cfg.fs)
        print("geschrieben:", args.wav)
    if args.play:
        if args.loop:
            audio_io.play(tx, cfg.fs, args.out_dev, blocking=False, loop=True)
            input("Dauersenden läuft – Enter beendet.")
            audio_io.stop()
        else:
            audio_io.play(tx, cfg.fs, args.out_dev)


if __name__ == "__main__":
    main()
