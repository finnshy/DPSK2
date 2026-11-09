"""Gemeinsame GUI-Bausteine für Sender und Empfänger (tkinter + matplotlib)."""
import math
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import audio_io, sequences
from .config import Config


class SettingsFrame(ttk.LabelFrame):
    """Signalparameter. Für Sender und Empfänger gleich einstellen."""

    FIELDS = [
        # (Name, Beschriftung, Art, Auswahl)
        ("modulation", "Modulation", "combo", ["DBPSK", "DQPSK"]),
        ("symbol_rate", "Symbolrate [Bd]", "entry", None),
        ("rolloff", "Roll-off", "entry", None),
        ("f_if", "ZF-Frequenz [Hz]", "entry", None),
        ("preamble_len", "Präambellänge", "combo", ["31", "63", "127", "255"]),
    ]
    SENDER_ONLY = [("amplitude", "Pegel (0..1)", "entry", None),
                   ("pause_s", "Pause Dauersenden [s]", "entry", None)]
    RECEIVER_ONLY = [("max_cfo_hz", "Max. Freq.-Versatz [Hz]", "entry", None)]

    def __init__(self, master, role: str):
        super().__init__(master, text="Signal (Sender = Empfänger)")
        fields = self.FIELDS + (self.SENDER_ONLY if role == "sender" else self.RECEIVER_ONLY)
        c = Config()
        self.vars = {}
        for i, (name, label, kind, values) in enumerate(fields):
            v = tk.StringVar(value=str(getattr(c, name)))
            self.vars[name] = v
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=1)
            if kind == "combo":
                w = ttk.Combobox(self, textvariable=v, values=values, width=10, state="readonly")
            else:
                w = ttk.Entry(self, textvariable=v, width=12)
            w.grid(row=i, column=1, sticky="w", padx=4, pady=1)
        self.info = ttk.Label(self, text="", foreground="gray", wraplength=300, justify="left")
        self.info.grid(row=len(fields), column=0, columnspan=2, sticky="w", padx=4)
        for v in self.vars.values():
            v.trace_add("write", lambda *a: self.update_info())
        self.update_info()

    def apply(self, cfg: Config) -> Config:
        for name, v in self.vars.items():
            typ = type(getattr(Config(), name))
            try:
                setattr(cfg, name, typ(v.get().replace(",", ".")) if typ is not str else v.get())
            except ValueError:
                raise ValueError("Ungültiger Wert bei '%s': %s" % (name, v.get()))
        return cfg

    def load(self, cfg: Config):
        for name, v in self.vars.items():
            v.set(str(getattr(cfg, name)))

    def update_info(self):
        try:
            cfg = self.apply(Config())
            err = cfg.check()
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if err:
            self.info.config(text=err, foreground="red")
            return
        txt = ("%d Abtastwerte/Symbol, Symbolrate %.1f Bd, %.0f bit/s\n"
               "Band %.0f … %.0f Hz (Breite %.0f Hz)"
               % (cfg.sps, cfg.rs, cfg.rs * math.log2(cfg.M), cfg.f_if - cfg.bandwidth / 2,
                  cfg.f_if + cfg.bandwidth / 2, cfg.bandwidth))
        txt += "\nOhne Korrektur entscheidbar bis ±%.0f Hz Versatz" % (cfg.rs / (2 * cfg.M))
        self.info.config(text=txt, foreground="gray")


class SequenceFrame(ttk.LabelFrame):
    """Definition der gesendeten Symbolfolge. Muss beim Empfänger gleich sein."""

    def __init__(self, master):
        super().__init__(master, text="Symbolfolge (Sender = Empfänger)")
        c = Config()
        self.preset = tk.StringVar(value=c.sequence_preset)
        self.seq_len = tk.StringVar(value=str(c.seq_len))
        self.reps = tk.StringVar(value=str(c.repetitions))
        ttk.Label(self, text="Vorlage").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(self, textvariable=self.preset, values=sequences.PRESETS, width=28,
                     state="readonly").grid(row=0, column=1, columnspan=3, sticky="w", padx=4, pady=1)
        ttk.Label(self, text="Länge (Vorlagen)").grid(row=1, column=0, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.seq_len, width=8).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(self, text="Wiederholungen").grid(row=1, column=2, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.reps, width=5).grid(row=1, column=3, sticky="w", padx=4)
        ttk.Label(self, text="Eigene Symbole / Bits / Text:").grid(row=2, column=0, columnspan=4, sticky="w", padx=4)
        self.text = tk.Text(self, width=40, height=3, wrap="word")
        self.text.insert("1.0", c.sequence_text)
        self.text.grid(row=3, column=0, columnspan=4, sticky="we", padx=4, pady=1)
        self.info = ttk.Label(self, text="", foreground="gray", wraplength=320, justify="left")
        self.info.grid(row=4, column=0, columnspan=4, sticky="w", padx=4)

    def apply(self, cfg: Config) -> Config:
        cfg.sequence_preset = self.preset.get()
        cfg.sequence_text = self.text.get("1.0", "end").strip()
        try:
            cfg.seq_len = int(self.seq_len.get())
            cfg.repetitions = int(self.reps.get())
        except ValueError:
            raise ValueError("Länge und Wiederholungen müssen ganze Zahlen sein")
        return cfg

    def load(self, cfg: Config):
        self.preset.set(cfg.sequence_preset)
        self.seq_len.set(str(cfg.seq_len))
        self.reps.set(str(cfg.repetitions))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", cfg.sequence_text)

    def show(self, seq, M):
        self.info.config(text=sequences.describe(seq, M))


class DeviceCombo(ttk.LabelFrame):
    STD = "Standardgerät"

    def __init__(self, master, kind: str, label: str):
        super().__init__(master, text="Audiogerät")
        self.kind = kind
        self.var = tk.StringVar(value=self.STD)
        ttk.Label(self, text=label).grid(row=0, column=0, sticky="w", padx=4)
        self.box = ttk.Combobox(self, textvariable=self.var, width=46, state="readonly")
        self.box.grid(row=1, column=0, sticky="w", padx=4, pady=1)
        ttk.Button(self, text="Aktualisieren", command=self.refresh).grid(row=1, column=1, padx=4)
        self.refresh(rescan=False)
        # WDM-KS bevorzugen: dort Stereo-Eingang und keine Windows-Audioverarbeitung
        for _, n in self.devices:
            if "USB Audio CODEC" in n and "WDM-KS" in n:
                self.var.set(n)
                break

    def refresh(self, rescan=True):
        if rescan:
            audio_io.rescan()
        self.devices = [(None, self.STD)] + audio_io.list_devices(self.kind)
        self.box["values"] = [n for _, n in self.devices]
        if self.var.get() not in [n for _, n in self.devices]:
            self.var.set(self.STD)

    def device(self):
        for idx, n in self.devices:
            if n == self.var.get():
                return idx
        return None


class PlotTabs(ttk.Notebook):
    """Reiter mit je 2x2 Grafiken und Matplotlib-Werkzeugleiste (Zoom, Speichern)."""

    def __init__(self, master, names, size=(9, 6.2)):
        super().__init__(master)
        self.tabs = {}
        for name in names:
            frame = ttk.Frame(self)
            fig = Figure(figsize=size, dpi=88, tight_layout=True)
            axes = [fig.add_subplot(2, 2, i + 1) for i in range(4)]
            canvas = FigureCanvasTkAgg(fig, master=frame)
            NavigationToolbar2Tk(canvas, frame).update()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.add(frame, text=name)
            self.tabs[name] = (fig, axes, canvas)

    def axes(self, name):
        fig, axes, _ = self.tabs[name]
        for ax in fig.axes[4:]:       # Zusatzachsen (twinx) entfernen
            fig.delaxes(ax)
        for ax in axes:
            ax.clear()
        return axes

    def draw(self):
        for _, _, canvas in self.tabs.values():
            canvas.draw_idle()


def config_buttons(parent, get_cfg, set_cfg):
    """Schaltflächen Konfiguration speichern/laden."""
    row = ttk.Frame(parent)

    def save():
        try:
            cfg = get_cfg()
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Fehler", str(e))
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="dpsk_config.json")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(cfg.to_json())

    def load():
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p:
            with open(p, encoding="utf-8") as f:
                set_cfg(Config.from_json(f.read()))

    ttk.Button(row, text="Konfiguration speichern", command=save).pack(side="left", padx=2)
    ttk.Button(row, text="Konfiguration laden", command=load).pack(side="left", padx=2)
    return row


def run_bg(root, func, on_done, on_error):
    def worker():
        try:
            res = func()
        except Exception as e:  # noqa: BLE001
            root.after(0, on_error, e)
        else:
            root.after(0, on_done, res)
    threading.Thread(target=worker, daemon=True).start()
