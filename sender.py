"""BPSK-Sender: Symbole ±1 auf I (links), Q = 0 (rechts), direkt im Basisband.

Start:  py -3.9 sender.py
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import audio_io
import bpsk


class SenderApp:
    def __init__(self, root):
        self.root = root
        root.title("BPSK-Sender")
        left = ttk.Frame(root)
        left.pack(side="left", fill="y", padx=8, pady=8)

        ttk.Label(left, text="Ausgang (→ I/Q-Modulator)").pack(anchor="w")
        self.devices = [(None, "Standardgerät")] + audio_io.list_devices("output")
        names = [n for _, n in self.devices]
        self.dev = tk.StringVar(value=next((n for n in names if "USB Audio CODEC" in n and "WDM-KS" in n), names[0]))
        ttk.Combobox(left, textvariable=self.dev, values=names, width=48, state="readonly").pack(anchor="w", pady=2)

        c = bpsk.Config()
        self.vars = {}
        form = ttk.Frame(left)
        form.pack(fill="x", pady=6)
        for i, (key, label) in enumerate([("symbol_rate", "Symbolrate [Bd]"), ("amplitude", "Pegel (0..1)"),
                                          ("n_symbols", "Symbole pro Burst"), ("pause_s", "Pause Dauersenden [s]")]):
            self.vars[key] = tk.StringVar(value=str(getattr(c, key)))
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(form, textvariable=self.vars[key], width=10).grid(row=i, column=1, sticky="w", padx=4, pady=1)
        ttk.Label(form, text="Bitfolge").grid(row=4, column=0, sticky="w")
        self.pattern = tk.StringVar(value=c.pattern)
        ttk.Combobox(form, textvariable=self.pattern, values=bpsk.PATTERNS, width=20,
                     state="readonly").grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(form, text="Eigene Bits").grid(row=5, column=0, sticky="w")
        self.bits = tk.StringVar(value=c.bits)
        ttk.Entry(form, textvariable=self.bits, width=24).grid(row=5, column=1, sticky="w", padx=4)

        ttk.Button(left, text="Einmal senden", command=lambda: self.send(False)).pack(fill="x", pady=1)
        ttk.Button(left, text="Dauersenden", command=lambda: self.send(True)).pack(fill="x", pady=1)
        ttk.Button(left, text="Stopp", command=audio_io.stop).pack(fill="x", pady=1)
        ttk.Button(left, text="Als WAV speichern", command=self.save).pack(fill="x", pady=1)
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(left, textvariable=self.status, wraplength=320).pack(anchor="w", pady=6)

        self.fig = Figure(figsize=(7, 5), dpi=90, tight_layout=True)
        self.ax = [self.fig.add_subplot(2, 1, i + 1) for i in range(2)]
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas.get_tk_widget().pack(side="right", fill="both", expand=True)

    def config(self) -> bpsk.Config:
        try:
            return bpsk.Config(symbol_rate=float(self.vars["symbol_rate"].get()),
                               amplitude=float(self.vars["amplitude"].get()),
                               n_symbols=int(self.vars["n_symbols"].get()),
                               pause_s=float(self.vars["pause_s"].get()),
                               pattern=self.pattern.get(), bits=self.bits.get())
        except ValueError:
            raise ValueError("Bitte Zahlen in die Felder eintragen")

    def signal(self, loop):
        cfg = self.config()
        tx = bpsk.modulate(cfg, bpsk.make_bits(cfg), silence_s=cfg.pause_s / 2 if loop else 0.2)
        self.plot(cfg, tx)
        self.status.set("%d Symbole, %.2f s, %d Abtastwerte/Symbol" % (cfg.n_symbols, cfg.n_symbols / cfg.symbol_rate, cfg.sps))
        return cfg, tx

    def send(self, loop):
        try:
            cfg, tx = self.signal(loop)
            dev = dict((n, i) for i, n in self.devices)[self.dev.get()]
            audio_io.play(tx, cfg.fs, dev, blocking=False, loop=loop)
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Fehler", str(e))
        self.status.set(self.status.get() + ("\nDauersenden läuft (Stopp beendet)" if loop else "\nGesendet."))

    def save(self):
        try:
            cfg, tx = self.signal(False)
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Fehler", str(e))
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="bpsk_tx.wav")
        if p:
            audio_io.write_wav(p, tx, cfg.fs)

    def plot(self, cfg, tx):
        x = tx[np.abs(tx[:, 0]) > 0]
        n = min(len(x), 20 * cfg.sps)
        for a in self.ax:
            a.clear()
        t = np.arange(n) / cfg.fs * 1000
        self.ax[0].plot(t, x[:n, 0], label="I")
        self.ax[0].plot(t, x[:n, 1], label="Q")
        self.ax[0].set_title("Sendesignal (erste 20 Symbole)")
        self.ax[0].set_xlabel("t [ms]")
        self.ax[0].legend()
        X = np.fft.fftshift(np.abs(np.fft.fft(x[:, 0] * np.hanning(len(x))))) + 1e-12
        f = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / cfg.fs))
        self.ax[1].plot(f / 1000, 20 * np.log10(X / X.max()), lw=0.5)
        self.ax[1].set_ylim(-60, 3)
        self.ax[1].set_title("Spektrum [dB]")
        self.ax[1].set_xlabel("f [kHz]")
        self.canvas.draw_idle()


if __name__ == "__main__":
    root = tk.Tk()
    SenderApp(root)
    root.mainloop()
