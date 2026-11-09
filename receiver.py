"""DPSK-Empfänger mit Phasenanalyse.

Start:  py -3.9 receiver.py
CLI:    py -3.9 receiver.py --wav aufnahme.wav [--config dpsk_config.json] [--csv symbole.csv]
        py -3.9 receiver.py --record 10 --in-dev 25
"""
import argparse
import csv
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from dpsk import Config, audio_io, channel, modem, sequences
from dpsk.gui_common import DeviceCombo, PlotTabs, SequenceFrame, SettingsFrame, config_buttons, run_bg


def export_csv(path, res, cfg):
    """Je Symbol eine Zeile, für alle Bursts."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["burst", "symbol", "t_s", "praeambel", "rx_re", "rx_im", "tx_re", "tx_im",
                    "phase_gesamt_umdrehungen", "phasenrest_grad", "momentanfrequenz_hz",
                    "dphi_roh_grad", "dphi_korr_grad", "dphi_tx_grad"])
        for bi, b in enumerate(res["bursts"]):
            L = b["n_preamble"]
            for k in range(len(b["t"])):
                d = (b["dphi_raw_deg"][k - 1], b["dphi_corr_deg"][k - 1], b["dphi_tx_deg"][k - 1]) if k else ("", "", "")
                w.writerow([bi, k, "%.6f" % b["t"][k], int(k < L), "%.6g" % b["z"][k].real, "%.6g" % b["z"][k].imag,
                            "%.0f" % b["s_tx"][k].real, "%.0f" % b["s_tx"][k].imag,
                            "%.6f" % b["phi_total_cycles"][k], "%.3f" % b["phi_res_deg"][k],
                            "" if np.isnan(b["f_inst"][k]) else "%.3f" % b["f_inst"][k], *d])


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        root.title("DPSK-Empfänger – Phasenanalyse")
        self.rx, self.res, self.cfg, self.recorder = None, None, None, None

        left = ttk.Frame(root)
        left.pack(side="left", fill="y", padx=6, pady=6)
        mid = ttk.Frame(root)
        mid.pack(side="left", fill="y", padx=6, pady=6)

        self.device = DeviceCombo(left, "input", "Eingang (← I/Q-Demodulator, links = I, rechts = Q)")
        self.device.pack(fill="x", pady=3)

        inp = ttk.LabelFrame(left, text="Aufnahme")
        inp.pack(fill="x", pady=3)
        row = ttk.Frame(inp)
        row.pack(fill="x", padx=4)
        ttk.Label(row, text="Max. Dauer [s]:").pack(side="left")
        self.max_s = tk.StringVar(value="20")
        ttk.Entry(row, textvariable=self.max_s, width=6).pack(side="left")
        self.rec_btn = ttk.Button(inp, text="Aufnahme starten", command=self.toggle_record)
        self.rec_btn.pack(fill="x", padx=4, pady=1)
        self.level = ttk.Progressbar(inp, maximum=1.0)
        self.level.pack(fill="x", padx=4, pady=1)
        ttk.Button(inp, text="WAV laden und auswerten", command=self.load_wav).pack(fill="x", padx=4, pady=1)
        ttk.Button(inp, text="Erneut auswerten (geänderte Einstellungen)", command=self.analyze).pack(fill="x", padx=4, pady=1)

        sim = ttk.LabelFrame(left, text="Kanalsimulation (nur WAV-Eingang)")
        sim.pack(fill="x", pady=3)
        self.sim_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(sim, text="aktiv", variable=self.sim_on).grid(row=0, column=0, sticky="w")
        self.sim = {"SNR Es/N0 [dB]": tk.StringVar(value="25"), "Frequenzversatz [Hz]": tk.StringVar(value="2500"),
                    "Drift [Hz/s]": tk.StringVar(value="20"), "Phasenrauschen [°/Symbol]": tk.StringVar(value="1"),
                    "Taktabweichung [ppm]": tk.StringVar(value="20")}
        for i, (k, v) in enumerate(self.sim.items()):
            ttk.Label(sim, text=k).grid(row=i + 1, column=0, sticky="w", padx=4)
            ttk.Entry(sim, textvariable=v, width=8).grid(row=i + 1, column=1, sticky="w")

        out = ttk.LabelFrame(left, text="Ergebnis")
        out.pack(fill="x", pady=3)
        row = ttk.Frame(out)
        row.pack(fill="x", padx=4)
        ttk.Label(row, text="Burst:").pack(side="left")
        self.burst = tk.StringVar(value="1")
        self.burst_box = ttk.Spinbox(row, from_=1, to=1, textvariable=self.burst, width=5, command=self.show)
        self.burst_box.pack(side="left")
        self.n_bursts = ttk.Label(row, text="von 0")
        self.n_bursts.pack(side="left", padx=4)
        row2 = ttk.Frame(out)
        row2.pack(fill="x", padx=4, pady=1)
        ttk.Label(row2, text="Rohsignal ab [s]").pack(side="left")
        self.win_start = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.win_start, width=7).pack(side="left")
        ttk.Label(row2, text="Länge [ms]").pack(side="left")
        self.win_len = tk.StringVar(value="20")
        ttk.Entry(row2, textvariable=self.win_len, width=5).pack(side="left")
        ttk.Button(row2, text="Zeigen", command=self._plot_raw).pack(side="left", padx=2)
        ttk.Button(out, text="Symboldaten als CSV exportieren", command=self.save_csv).pack(fill="x", padx=4, pady=1)
        ttk.Button(out, text="Rohaufnahme als WAV speichern", command=self.save_raw).pack(fill="x", padx=4, pady=1)

        self.settings = SettingsFrame(mid, "receiver")
        self.settings.pack(fill="x", pady=3)
        self.seq = SequenceFrame(mid)
        self.seq.pack(fill="x", pady=3)
        config_buttons(mid, self.get_cfg, self.set_cfg).pack(fill="x", pady=3)
        self.status = tk.Text(mid, width=52, height=14, wrap="word", font=("Consolas", 9))
        self.status.pack(fill="both", expand=True, pady=3)
        self._set_status("Bereit. Gleiche Signal- und Symbolfolgen-Einstellungen wie am Sender wählen.")

        self.plots = PlotTabs(root, ["Phase", "Signal", "Rohsignal"])
        self.raw = None
        self.plots.pack(side="right", fill="both", expand=True)

    # ------------------------------------------------------------------ Konfiguration
    def get_cfg(self) -> Config:
        cfg = self.seq.apply(self.settings.apply(Config()))
        err = cfg.check()
        if err:
            raise ValueError(err)
        return cfg

    def set_cfg(self, cfg: Config):
        self.settings.load(cfg)
        self.seq.load(cfg)

    def _set_status(self, text):
        self.status.delete("1.0", "end")
        self.status.insert("1.0", text)

    def _err(self, e):
        self._set_status("Fehler: %s" % e)

    # ------------------------------------------------------------------ Eingang
    def toggle_record(self):
        if self.recorder is None:
            try:
                cfg = self.get_cfg()
                self.recorder = audio_io.Recorder(cfg.fs, 2, self.device.device(), float(self.max_s.get()))
                self.recorder.start()
            except Exception as e:  # noqa: BLE001
                self.recorder = None
                return self._err(e)
            self.rec_btn.config(text="Aufnahme stoppen und auswerten")
            self._poll()
        else:
            self._finish()

    def _poll(self):
        if self.recorder is None:
            return
        self.level["value"] = min(self.recorder.level, 1.0)
        if self.recorder._done.is_set():
            return self._finish()
        self._set_status("Aufnahme läuft … %.1f s (Pegel %.3f)" % (self.recorder.seconds, self.recorder.level))
        self.root.after(100, self._poll)

    def _finish(self):
        rec, self.recorder = self.recorder, None
        self.rec_btn.config(text="Aufnahme starten")
        self.rx = rec.stop()
        self.analyze()

    def load_wav(self):
        p = filedialog.askopenfilename(filetypes=[("WAV", "*.wav"), ("Alle", "*.*")])
        if not p:
            return
        try:
            cfg = self.get_cfg()
            x, fs = audio_io.read_wav(p)
            if fs != cfg.fs:
                raise ValueError("WAV hat %d Hz, erwartet %d Hz" % (fs, cfg.fs))
            if x.shape[1] < 2:
                raise ValueError("WAV ist mono – es wird I/Q (Stereo) benötigt")
            if self.sim_on.get():
                s = {k: float(v.get().replace(",", ".")) for k, v in self.sim.items()}
                x = channel.simulate(x, cfg, snr_db=s["SNR Es/N0 [dB]"], cfo_hz=s["Frequenzversatz [Hz]"],
                                     drift_hz_s=s["Drift [Hz/s]"], phase_noise_deg=s["Phasenrauschen [°/Symbol]"],
                                     sco_ppm=s["Taktabweichung [ppm]"], phase0_deg=float(np.random.uniform(0, 360)),
                                     seed=int(time.time()))
        except Exception as e:  # noqa: BLE001
            return self._err(e)
        self.rx = x
        self.analyze()

    # ------------------------------------------------------------------ Auswertung
    def analyze(self):
        if self.rx is None:
            return self._set_status("Noch keine Aufnahme.")
        try:
            cfg = self.get_cfg()
            data = sequences.build(cfg)
        except Exception as e:  # noqa: BLE001
            return self._err(e)
        self.seq.show(data, cfg.M)
        rx = self.rx
        self._set_status("Werte %.1f s Aufnahme aus …" % (len(rx) / cfg.fs))

        def job():
            return modem.analyze(rx, cfg, data), modem.raw_view(rx, cfg)

        def done(out):
            res, self.raw = out
            self.res, self.cfg = res, cfg
            self.win_start.set("")
            n = len(res["bursts"])
            self.burst_box.config(to=max(n, 1))
            self.burst.set("1")
            self.n_bursts.config(text="von %d" % n)
            self.show()

        run_bg(self.root, job, done, self._err)

    def show(self):
        res, cfg = self.res, self.cfg
        if res is None:
            return
        peak = float(np.max(np.abs(self.rx))) if self.rx is not None and self.rx.size else 0
        warn = "WARNUNG: Eingang übersteuert (Spitze %.2f)!\n" % peak if peak > 0.98 else ""
        if not res["bursts"]:
            self._set_status(warn + "Kein vollständiger Burst gefunden (max. Präambel-Metrik %.2f, unvollständig: %d).\n"
                             "Reiter 'Rohsignal' prüfen (Spektrogramm, I/Q, Phase); Einstellungen wie am Sender?"
                             % (res["peak_metric"], res["skipped"]))
            self._plot_spectrum_only()
            self._plot_raw()
            self.plots.select(2)
            return
        try:
            i = min(max(int(self.burst.get()) - 1, 0), len(res["bursts"]) - 1)
        except ValueError:
            i = 0
        b = res["bursts"][i]
        head = warn + "Burst %d von %d%s\n" % (i + 1, len(res["bursts"]),
                                               (" (%d unvollständige übersprungen)" % res["skipped"]) if res["skipped"] else "")
        self._set_status(head + modem.summary(b, cfg))
        self._plot(b)
        self._plot_raw()

    def _plot_spectrum_only(self):
        for name in ("Phase", "Signal"):
            self.plots.axes(name)
        a = self.plots.axes("Signal")
        self._spectrum(a[0], None)
        self.plots.draw()

    def _spectrum(self, ax, b):
        res, cfg = self.res, self.cfg
        ax.plot(res["f"] / 1000, 10 * np.log10(res["psd"] / np.max(res["psd"]) + 1e-15), lw=0.6)
        ax.axvline(cfg.f_if / 1000, color="gray", ls="--", lw=0.8, label="ZF (Soll)")
        if b is not None:
            ax.axvline(b["stats"]["fc"] / 1000, color="r", ls=":", lw=1, label="gemessen")
        ax.set_ylim(-80, 3)
        ax.set_xlabel("f [kHz]")
        ax.set_title("Spektrum der Aufnahme (I/Q) [dB]")
        ax.legend(fontsize=7)

    def _plot(self, b):
        cfg, s = self.cfg, b["stats"]
        L, t, k = b["n_preamble"], b["tt"], b["k"]

        # ---------------- Reiter "Phase"
        a = self.plots.axes("Phase")
        a[0].plot(t, b["phi_total_cycles"], lw=0.8)
        a[0].axvspan(0, t[L - 1], color="orange", alpha=0.15, label="Präambel")
        a[0].set_title("Phasendifferenz Empfang − Sender [Umdrehungen]\nSteigung = Frequenzversatz %.1f Hz" % s["f_off"])
        a[0].set_xlabel("t [s]")
        a[0].legend(fontsize=7)

        a[1].plot(t, b["phi_res_deg"], ".", ms=2, alpha=0.6, label="gemessen")
        a[1].plot(t, b["phi_fit_quad_deg"], "r", lw=1, label="Drift %.2f Hz/s" % s["drift_hz_s"])
        a[1].axvspan(0, t[L - 1], color="orange", alpha=0.15)
        a[1].set_title("Phasenrest nach Abzug des mittleren Versatzes [°]\nRauschen %.1f° rms" % s["phase_noise_deg"])
        a[1].set_xlabel("t [s]")
        a[1].legend(fontsize=7)

        a[2].plot(t, b["f_inst"], lw=0.8)
        a[2].axhline(s["f_off"], color="r", ls="--", lw=0.8)
        a[2].set_title("Momentane Frequenzabweichung [Hz] (geglättet)")
        a[2].set_xlabel("t [s]")
        a[2].ticklabel_format(useOffset=False)

        kk = k[1:]
        a[3].plot(kk, b["dphi_raw_deg"], ".", ms=2, color="tab:blue", label="empfangen ohne Korrektur")
        a[3].plot(kk, b["dphi_tx_deg"], "_", ms=4, color="k", alpha=0.5, label="gesendet")
        ek = kk[L - 1:][b["err_raw"]]
        if len(ek):
            a[3].plot(ek, b["dphi_raw_deg"][L - 1:][b["err_raw"]], "x", ms=4, color="r", label="Fehlentscheidung")
        a[3].axvspan(0, L, color="orange", alpha=0.15)
        a[3].set_ylim(-185, 185)
        a[3].set_yticks(range(-180, 181, 90 if cfg.M == 4 else 180))
        a[3].set_title("Phasenänderung je Symbol [°]\nDrehung durch Versatz: %+.1f°/Symbol" % s["rot_per_symbol_deg"])
        a[3].set_xlabel("Symbol")
        a[3].legend(fontsize=7, loc="lower right")

        # ---------------- Reiter "Signal"
        a = self.plots.axes("Signal")
        self._spectrum(a[0], b)

        c = b["const"]
        sc = a[1].scatter(c.real, c.imag, c=t, s=3, cmap="viridis")
        a[1].plot(b["s_tx"].real, b["s_tx"].imag, "r+", ms=10)
        a[1].set_aspect("equal")
        lim = 1.6
        a[1].set_xlim(-lim, lim)
        a[1].set_ylim(-lim, lim)
        a[1].grid(True)
        a[1].set_title("Symbole nach Frequenz-/Phasenkorrektur\nFarbe = Zeit, SNR %.1f dB" % s["snr_db"])
        self.plots.tabs["Signal"][0].colorbar(sc, ax=a[1], label="t [s]")

        d1, d2 = b["diff_raw"], b["diff_corr"]
        a[2].plot(d1.real, d1.imag, ".", ms=2, alpha=0.5, label="ohne Korrektur")
        a[2].plot(d2.real, d2.imag, ".", ms=2, alpha=0.5, label="mit Korrektur")
        for i in range(cfg.M):      # Entscheidungsgrenzen
            ang = np.pi / cfg.M + 2 * np.pi * i / cfg.M
            a[2].plot([0, 1.8 * np.cos(ang)], [0, 1.8 * np.sin(ang)], "k:", lw=0.7)
        a[2].set_aspect("equal")
        a[2].set_xlim(-1.8, 1.8)
        a[2].set_ylim(-1.8, 1.8)
        a[2].set_title("DPSK-Entscheidungsebene z[k]·z*[k−1]\nFehler: ohne %d, mit Korrektur %d"
                       % (s["n_err_raw"], s["n_err_corr"]))
        a[2].legend(fontsize=7, loc="lower right")

        bursts = self.res["bursts"]
        if len(bursts) > 1:
            tb = [x["stats"]["t_start"] for x in bursts]
            fb = [x["stats"]["f_off"] for x in bursts]
            a[3].plot(tb, fb, "o-", ms=3)
            a[3].plot(b["stats"]["t_start"], s["f_off"], "ro")
            a[3].set_title("Frequenzversatz je Burst [Hz]")
            a[3].set_xlabel("Zeitpunkt in der Aufnahme [s]")
            a[3].ticklabel_format(useOffset=False)
        else:
            a[3].plot(t, b["amp"], lw=0.6)
            a[3].set_title("Betrag der Empfangssymbole (normiert)")
            a[3].set_xlabel("t [s]")
        self.plots.draw()

    def _plot_raw(self):
        """Reiter 'Rohsignal': Spektrogramm, Versatz-Verlauf, I/Q- und Phasenverlauf im Ausschnitt."""
        rv, cfg = self.raw, self.cfg
        if rv is None:
            return
        a = self.plots.axes("Rohsignal")
        fig = self.plots.tabs["Rohsignal"][0]
        S = rv["S_db"]
        a[0].pcolormesh(rv["t"], rv["f"] / 1000, S, shading="auto", cmap="viridis",
                        vmin=np.percentile(S, 40), vmax=S.max())
        a[0].axhline(cfg.f_if / 1000, color="w", ls="--", lw=0.6)
        a[0].set_title("Spektrogramm I/Q (weiß = ZF)")
        a[0].set_xlabel("t [s]")
        a[0].set_ylabel("f [kHz]")
        ok = rv["peak_level_db"] > 15
        a[1].plot(rv["t"][ok], rv["f_peak_rel"][ok], ".", ms=2)
        a[1].set_title("Stärkste Spektrallinie − ZF [Hz]\n(= Frequenzversatz, wenn ein Träger gesendet wird)")
        a[1].set_xlabel("t [s]")
        a[1].grid(True)
        r, fs = rv["r"], cfg.fs
        try:
            t0 = float(self.win_start.get().replace(",", "."))
        except ValueError:
            m = np.abs(r)
            on = np.flatnonzero(m > 0.3 * m.max())
            t0 = (on[0] / fs + 0.1) if len(on) else 0.0
            self.win_start.set("%.3f" % t0)
        try:
            dur = float(self.win_len.get().replace(",", ".")) / 1000
        except ValueError:
            dur = 0.02
        i0 = int(max(0, min(t0 * fs, len(r) - 2)))
        i1 = int(min(len(r), i0 + max(dur * fs, 4)))
        tt = (np.arange(i0, i1) / fs - t0) * 1000
        x = r[i0:i1]
        a[2].plot(tt, x.real, lw=0.7, label="I")
        a[2].plot(tt, x.imag, lw=0.7, label="Q")
        a[2].plot(tt, np.abs(x), "k", lw=0.5, alpha=0.5, label="Betrag")
        a[2].set_title("I/Q ab %.3f s" % t0)
        a[2].set_xlabel("t [ms]")
        a[2].legend(fontsize=7)
        a[2].grid(True)
        ph = np.unwrap(np.angle(x * np.exp(-2j * np.pi * cfg.f_if * np.arange(i0, i1) / fs)))
        a[3].plot(tt, np.degrees(ph - ph[0]), lw=0.8)
        a[3].set_title("Phase relativ zur ZF [°], abgewickelt\n(Steigung = Frequenzversatz)")
        a[3].set_xlabel("t [ms]")
        a[3].grid(True)
        fig.canvas.draw_idle()

    # ------------------------------------------------------------------ Export
    def save_csv(self):
        if not self.res or not self.res["bursts"]:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="dpsk_symbole.csv")
        if p:
            export_csv(p, self.res, self.cfg)

    def save_raw(self):
        if self.rx is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="dpsk_rx_roh.wav")
        if p:
            audio_io.write_wav(p, self.rx, Config().fs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", help="Aufnahme (Stereo I/Q) auswerten")
    ap.add_argument("--record", type=float, help="Sekunden aufnehmen und auswerten")
    ap.add_argument("--in-dev", type=int, help="Eingabegerät (Nummer, siehe --list-devices)")
    ap.add_argument("--config", help="JSON-Konfiguration")
    ap.add_argument("--csv", help="Symboldaten als CSV speichern")
    ap.add_argument("--save-raw", help="Rohaufnahme als WAV speichern")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        print(audio_io.device_table())
        return
    if not (args.wav or args.record):
        root = tk.Tk()
        ReceiverApp(root)
        root.mainloop()
        return
    cfg = Config.from_json(open(args.config, encoding="utf-8").read()) if args.config else Config()
    data = sequences.build(cfg)
    if args.wav:
        rx, _ = audio_io.read_wav(args.wav)
    else:
        print("Aufnahme %.1f s …" % args.record)
        rx = audio_io.record(args.record, cfg.fs, 2, args.in_dev)
    if args.save_raw:
        audio_io.write_wav(args.save_raw, rx, cfg.fs)
    res = modem.analyze(rx, cfg, data)
    print("%d Burst(s) gefunden, %d unvollständig" % (len(res["bursts"]), res["skipped"]))
    for i, b in enumerate(res["bursts"]):
        print("\n--- Burst %d ---\n%s" % (i + 1, modem.summary(b, cfg)))
    if args.csv and res["bursts"]:
        export_csv(args.csv, res, cfg)
        print("CSV:", args.csv)


if __name__ == "__main__":
    main()
