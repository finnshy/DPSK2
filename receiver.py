"""BPSK-Empfänger: macht den Frequenzoffset zwischen Sender und Empfänger sichtbar.

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


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        root.title("BPSK-Empfänger – Frequenzoffset")
        self.rec, self.rx = None, None
        left = ttk.Frame(root)
        left.pack(side="left", fill="y", padx=8, pady=8)

        ttk.Label(left, text="Eingang (← I/Q-Demodulator)").pack(anchor="w")
        self.devices = [(None, "Standardgerät")] + audio_io.list_devices("input")
        names = [n for _, n in self.devices]
        self.dev = tk.StringVar(value=next((n for n in names if "USB Audio CODEC" in n and "WDM-KS" in n), names[0]))
        ttk.Combobox(left, textvariable=self.dev, values=names, width=48, state="readonly").pack(anchor="w", pady=2)

        form = ttk.Frame(left)
        form.pack(fill="x", pady=6)
        ttk.Label(form, text="Symbolrate [Bd] (wie Sender)").grid(row=0, column=0, sticky="w")
        self.rate = tk.StringVar(value=str(bpsk.Config().symbol_rate))
        ttk.Entry(form, textvariable=self.rate, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="Max. Aufnahmedauer [s]").grid(row=1, column=0, sticky="w")
        self.max_s = tk.StringVar(value="10")
        ttk.Entry(form, textvariable=self.max_s, width=10).grid(row=1, column=1, padx=4)

        self.btn = ttk.Button(left, text="Aufnahme starten", command=self.toggle)
        self.btn.pack(fill="x", pady=1)
        ttk.Button(left, text="WAV laden", command=self.load).pack(fill="x", pady=1)
        ttk.Button(left, text="Aufnahme als WAV speichern", command=self.save).pack(fill="x", pady=1)
        self.status = tk.Text(left, width=46, height=9, font=("Consolas", 9))
        self.status.pack(fill="x", pady=6)
        self.say("Bereit.")

        right = ttk.Frame(root)
        right.pack(side="right", fill="both", expand=True)
        self.fig = Figure(figsize=(9, 6.5), dpi=88, tight_layout=True)
        self.ax = [self.fig.add_subplot(2, 2, i + 1) for i in range(4)]
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        NavigationToolbar2Tk(self.canvas, right).update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def say(self, text):
        self.status.delete("1.0", "end")
        self.status.insert("1.0", text)

    def cfg(self):
        return bpsk.Config(symbol_rate=float(self.rate.get()))

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
        try:
            res = bpsk.analyze(self.rx, self.cfg())
        except Exception as e:  # noqa: BLE001
            return self.say("Fehler: %s" % e)
        self.say(bpsk.summary(res))
        self.plot(res)

    def plot(self, res):
        a = self.ax
        for x in a:
            x.clear()
        df = res["df"]
        a[0].plot(res["f"] / 1000, res["R_db"], lw=0.5, color="0.6", label="Empfangssignal r")
        a[0].plot(res["f"] / 1000, res["S_db"], lw=0.6, color="tab:red", label="r² (Linie bei 2·Δf)")
        a[0].axvline(df / 1000, color="k", ls=":", lw=1, label="Δf")
        a[0].set_ylim(-70, 3)
        a[0].set_xlabel("f [kHz]")
        a[0].set_title("Spektrum – Offset Δf = %+.1f Hz" % df)
        a[0].legend(fontsize=7)

        a[1].plot(res["t"], res["f_inst"], lw=0.8)
        a[1].axhline(df, color="r", ls="--", lw=0.8)
        a[1].set_xlabel("t [s]")
        a[1].set_title("Frequenzoffset über der Zeit [Hz]")
        a[1].ticklabel_format(useOffset=False)
        a[1].grid(True)

        a[2].plot(res["t"], res["phase"] / (2 * np.pi), lw=0.8)
        a[2].set_xlabel("t [s]")
        a[2].set_title("Phase Empfang − Sender [Umdrehungen]\n(Steigung = Frequenzoffset)")
        a[2].grid(True)

        s1, s2 = res["sym_raw"], res["sym_corr"]
        m = max(np.max(np.abs(s2)), 1e-12)
        a[3].plot(s1.real / m, s1.imag / m, ".", ms=2, alpha=0.5, label="ohne Korrektur (läuft um)")
        a[3].plot(s2.real / m, s2.imag / m, ".", ms=3, alpha=0.5, label="mit Korrektur")
        a[3].set_aspect("equal")
        a[3].set_xlim(-1.3, 1.3)
        a[3].set_ylim(-1.3, 1.3)
        a[3].grid(True)
        a[3].set_title("Symbole (I/Q)")
        a[3].legend(fontsize=7, loc="lower right")
        self.canvas.draw_idle()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        y, _ = audio_io.read_wav(sys.argv[1])
        print(bpsk.summary(bpsk.analyze(y, bpsk.Config())))
    else:
        root = tk.Tk()
        ReceiverApp(root)
        root.mainloop()
