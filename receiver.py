"""BPSK-Empfänger: Frequenzoffset, Barker-Zeitsynchronisation und Symbol Timing Recovery.

Start:  py -3.9 receiver.py
CLI:    py -3.9 receiver.py aufnahme.wav
"""
import sys
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import audio_io
import bpsk


def make_tab(notebook, title, layout):
    """Reiter mit Matplotlib-Figur. layout: Liste von (Zeile, Spalte, Zeilen, Spalten) in einem Raster."""
    frame = ttk.Frame(notebook)
    notebook.add(frame, text=title)
    fig = Figure(figsize=(9.5, 6.8), dpi=86, tight_layout=True)
    gs = fig.add_gridspec(*layout[0])
    axes = [fig.add_subplot(gs[r:r + h, c:c + w]) for r, c, h, w in layout[1:]]
    canvas = FigureCanvasTkAgg(fig, master=frame)
    NavigationToolbar2Tk(canvas, frame).update()
    canvas.get_tk_widget().pack(fill="both", expand=True)
    return fig, axes, canvas


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        root.title("BPSK-Empfänger")
        self.rec, self.rx, self.res = None, None, None
        left = ttk.Frame(root)
        left.pack(side="left", fill="y", padx=8, pady=8)

        ttk.Label(left, text="Eingang (← I/Q-Demodulator)").pack(anchor="w")
        self.devices = [(None, "Standardgerät")] + audio_io.list_devices("input")
        names = [n for _, n in self.devices]
        self.dev = tk.StringVar(value=next((n for n in names if "USB Audio CODEC" in n and "WDM-KS" in n), names[0]))
        ttk.Combobox(left, textvariable=self.dev, values=names, width=48, state="readonly").pack(anchor="w", pady=2)

        form = ttk.Frame(left)
        form.pack(fill="x", pady=6)
        self.rate = tk.StringVar(value=str(bpsk.Config().symbol_rate))
        self.max_s = tk.StringVar(value="10")
        self.gain = tk.StringVar(value=str(bpsk.Config().timing_gain))
        for i, (label, var) in enumerate([("Symbolrate [Bd] (wie Sender)", self.rate),
                                          ("Max. Aufnahmedauer [s]", self.max_s),
                                          ("Timing-Regelverstärkung (0 = aus)", self.gain)]):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(form, textvariable=var, width=10).grid(row=i, column=1, padx=4, pady=1)

        self.btn = ttk.Button(left, text="Aufnahme starten", command=self.toggle)
        self.btn.pack(fill="x", pady=1)
        ttk.Button(left, text="WAV laden", command=self.load).pack(fill="x", pady=1)
        ttk.Button(left, text="Aufnahme als WAV speichern", command=self.save).pack(fill="x", pady=1)
        ttk.Button(left, text="Erneut auswerten", command=self.evaluate).pack(fill="x", pady=1)

        cmp_ = ttk.LabelFrame(left, text="Vergleich mit Sender (für Bitfehler)")
        cmp_.pack(fill="x", pady=6)
        c = bpsk.Config()
        self.pattern = tk.StringVar(value=c.pattern)
        self.nsym = tk.StringVar(value=str(c.n_symbols))
        self.bits = tk.StringVar(value=c.bits)
        ttk.Label(cmp_, text="Bitfolge").grid(row=0, column=0, sticky="w")
        ttk.Combobox(cmp_, textvariable=self.pattern, values=bpsk.PATTERNS, width=20,
                     state="readonly").grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(cmp_, text="Symbole pro Burst").grid(row=1, column=0, sticky="w")
        ttk.Entry(cmp_, textvariable=self.nsym, width=8).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(cmp_, text="Eigene Bits").grid(row=2, column=0, sticky="w")
        ttk.Entry(cmp_, textvariable=self.bits, width=22).grid(row=2, column=1, sticky="w", padx=4)

        view = ttk.LabelFrame(left, text="Zeitsignal-Ausschnitt")
        view.pack(fill="x", pady=2)
        self.first = tk.StringVar(value="0")
        self.count = tk.StringVar(value="30")
        ttk.Label(view, text="ab Symbol").grid(row=0, column=0)
        ttk.Entry(view, textvariable=self.first, width=6).grid(row=0, column=1)
        ttk.Label(view, text="Anzahl").grid(row=0, column=2)
        ttk.Entry(view, textvariable=self.count, width=5).grid(row=0, column=3)
        ttk.Button(view, text="Zeigen", command=self.plot_sync).grid(row=0, column=4, padx=4)

        self.status = tk.Text(left, width=48, height=10, font=("Consolas", 9))
        self.status.pack(fill="x", pady=6)
        self.say("Bereit.")

        nb = ttk.Notebook(root)
        nb.pack(side="right", fill="both", expand=True)
        self.tab1 = make_tab(nb, "Frequenzoffset", [(2, 2), (0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 1, 1)])
        self.tab2 = make_tab(nb, "Zeitsynchronisation", [(2, 2), (0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 2)])

    # ------------------------------------------------------------------ Ablauf
    def say(self, text):
        self.status.delete("1.0", "end")
        self.status.insert("1.0", text)

    def cfg(self):
        return bpsk.Config(symbol_rate=float(self.rate.get()), timing_gain=float(self.gain.get()),
                           pattern=self.pattern.get(), n_symbols=int(self.nsym.get()), bits=self.bits.get())

    def toggle(self):
        if self.rec is None:
            try:
                dev = dict((n, i) for i, n in self.devices)[self.dev.get()]
                self.rec = audio_io.Recorder(48000, 2, dev, float(self.max_s.get()))
                self.rec.start()
            except Exception as e:  # noqa: BLE001
                self.rec = None
                return self.say("Fehler: %s" % e)
            self.btn.config(text="Aufnahme stoppen und auswerten")
            self.poll()
        else:
            self.finish()

    def poll(self):
        if self.rec is None:
            return
        if self.rec._done.is_set():
            return self.finish()
        self.say("Aufnahme läuft … %.1f s" % self.rec.seconds)
        self.root.after(100, self.poll)

    def finish(self):
        rec, self.rec = self.rec, None
        self.btn.config(text="Aufnahme starten")
        self.rx = rec.stop()
        self.evaluate()

    def load(self):
        p = filedialog.askopenfilename(filetypes=[("WAV", "*.wav")])
        if p:
            self.rx, _ = audio_io.read_wav(p)
            self.evaluate()

    def save(self):
        if self.rx is not None:
            p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="bpsk_rx.wav")
            if p:
                audio_io.write_wav(p, self.rx, 48000)

    def evaluate(self):
        if self.rx is None:
            return self.say("Noch keine Aufnahme.")
        try:
            cfg = self.cfg()
            self.res = bpsk.analyze(self.rx, cfg)
            err, n = bpsk.bit_errors(self.res, cfg)
        except Exception as e:  # noqa: BLE001
            return self.say("Fehler: %s" % e)
        self.say(bpsk.summary(self.res) + "\nBitfehler (Vergleich mit Sender-Einstellung): %d von %d" % (err, n))
        self.plot_offset()
        self.plot_sync()

    # ------------------------------------------------------------------ Grafiken
    def plot_offset(self):
        res = self.res
        _, a, canvas = self.tab1
        for x in a:
            x.clear()
        df = res["df"]
        on0, on1 = res["on"]
        t = res["t"]
        a[0].plot(res["f"] / 1000, res["R_db"], lw=0.5, color="0.6", label="Empfangssignal r")
        a[0].plot(res["f"] / 1000, res["S_db"], lw=0.6, color="tab:red", label="r² (Linie bei 2·Δf)")
        a[0].axvline(df / 1000, color="k", ls=":", lw=1, label="Δf")
        a[0].set_ylim(-70, 3)
        a[0].set_xlabel("f [kHz]")
        a[0].set_title("Spektrum – Offset Δf = %+.1f Hz" % df)
        a[0].legend(fontsize=7)

        a[1].plot(t, res["f_inst"], lw=0.8)
        a[1].axhline(df, color="r", ls="--", lw=0.8)
        a[1].set_xlabel("t [s]")
        a[1].set_title("Frequenzoffset über der Zeit [Hz]")
        a[1].ticklabel_format(useOffset=False)
        a[1].grid(True)

        a[2].plot(t[on0:on1], (res["phase"][on0:on1] - res["phase"][on0]) / (2 * np.pi), lw=0.8)
        a[2].set_xlabel("t [s]")
        a[2].set_title("Phase Empfang − Sender [Umdrehungen]\n(Steigung = Frequenzoffset)")
        a[2].grid(True)

        s1, s2 = res["sym_raw"], res["sym_corr"]
        m = max(np.max(np.abs(s2)), 1e-12) if len(s2) else 1.0
        a[3].plot(s1.real / m, s1.imag / m, ".", ms=2, alpha=0.5, label="ohne Korrektur (läuft um)")
        a[3].plot(s2.real / m, s2.imag / m, ".", ms=3, alpha=0.5, label="mit Korrektur + Timing")
        a[3].set_aspect("equal")
        a[3].set_xlim(-1.3, 1.3)
        a[3].set_ylim(-1.3, 1.3)
        a[3].grid(True)
        a[3].set_title("Symbole (I/Q)")
        a[3].legend(fontsize=7, loc="lower right")
        canvas.draw_idle()

    def plot_sync(self):
        res = self.res
        if res is None:
            return
        _, a, canvas = self.tab2
        for x in a:
            x.clear()
        fs, sps, n0 = res["fs"], res["sps"], res["n0"]
        tms = lambda n: n / fs * 1000                     # Abtastwert -> ms (relativ zum Ausschnitt)

        # Barker-Korrelation um die Spitze
        lo, hi = max(0, n0 - 25 * sps), min(len(res["corr"]), n0 + 25 * sps)
        k = np.arange(lo, hi)
        a[0].plot((k - n0) / sps, res["corr"][lo:hi], lw=0.8)
        a[0].axvline(0, color="r", ls=":", lw=1)
        a[0].set_xlabel("Verschiebung [Symbole]")
        a[0].set_title("Barker-13-Korrelation (normiert)\nSpitze = Beginn der Präambel, Güte %.2f" % res["barker_quality"])
        a[0].grid(True)

        # Timing-Nachführung
        to = res["timing_offset"]
        a[1].plot(np.arange(len(to)), to, lw=0.8)
        a[1].set_xlabel("Symbol")
        a[1].set_ylabel("Abtastwerte")
        a[1].set_title("Timing-Nachführung: Verschiebung gegenüber starrem Raster")
        a[1].grid(True)

        # Zeitsignal mit Abtastzeitpunkten
        try:
            k0 = max(0, int(self.first.get()))
            nk = max(1, int(self.count.get()))
        except ValueError:
            k0, nk = 0, 30
        starts, centers, syms = res["starts"], res["centers"], res["sym_corr"]
        if k0 >= len(starts):
            k0 = max(0, len(starts) - nk)
        k1 = min(len(starts), k0 + nk)
        if k1 > k0:
            i0 = max(0, starts[k0] - sps)
            i1 = min(len(res["z"]), starts[k1 - 1] + 2 * sps)
            n = np.arange(i0, i1)
            ref = n[0]
            amp = np.median(np.abs(syms[:13])) if len(syms) >= 13 else 1.0
            a[2].plot(tms(n - ref), res["r"][i0:i1].real / amp, color="0.75", lw=0.7, label="I roh (ohne Korrektur)")
            a[2].plot(tms(n - ref), res["z"][i0:i1].real / amp, color="tab:blue", lw=1, label="nach Frequenzkorrektur")
            for j in range(k0, k1):
                a[2].axvline(tms(starts[j] - ref), color="0.85", lw=0.6)
                if j < 13:
                    a[2].axvspan(tms(starts[j] - ref), tms(starts[j] + sps - ref), color="orange", alpha=0.12)
            a[2].plot(tms(centers[k0:k1] - ref), syms[k0:k1].real / amp, "o", color="tab:red", ms=5,
                      label="Abtastzeitpunkt (Integration über das Symbol)")
            if k1 - k0 <= 60:
                for j in range(k0, k1):
                    lab = ("B" if j < 13 else "") + ("1" if syms[j].real > 0 else "0")
                    a[2].text(tms(centers[j] - ref), 1.35, lab, ha="center", fontsize=7)
            a[2].set_ylim(-1.6, 1.6)
            a[2].set_xlabel("t [ms] ab Symbol %d" % k0)
            a[2].set_title("Zeitsignal und Abtastzeitpunkte (orange = Barker-Präambel, Zahlen = entschiedene Bits)")
            a[2].legend(fontsize=7, loc="lower right")
            a[2].grid(True, axis="y")
        canvas.draw_idle()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        y, _ = audio_io.read_wav(sys.argv[1])
        print(bpsk.summary(bpsk.analyze(y, bpsk.Config())))
    else:
        root = tk.Tk()
        ReceiverApp(root)
        root.mainloop()
