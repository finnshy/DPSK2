"""Parameter der DPSK-Einträgerübertragung.

Sender und Empfänger brauchen dieselben Werte (außer Pegel und Pause, die nur der
Sender nutzt, und max_cfo_hz, den nur der Empfänger nutzt). Über
to_json/from_json lassen sie sich als Datei austauschen.
"""
from dataclasses import asdict, dataclass
import json


@dataclass
class Config:
    # --- Soundkarte / Signal ----------------------------------------------
    fs: int = 48000                 # Abtastrate der Soundkarte [Hz]
    symbol_rate: float = 1000.0     # Symbolrate [Bd]; fs/symbol_rate wird auf ganze Zahl gerundet
    rolloff: float = 0.35           # Roll-off des Wurzel-Kosinus-Filters (RRC)
    rrc_span: int = 10              # Filterlänge in Symbolen
    modulation: str = "DQPSK"       # DBPSK oder DQPSK
    f_if: float = 3000.0            # digitale Zwischenfrequenz im I/Q-Basisband [Hz]
    amplitude: float = 0.2          # Spitzenpegel am Soundkarten-Ausgang (0..1)
    pause_s: float = 0.5            # Pause zwischen Bursts beim Dauersenden [s]

    # --- Rahmen -----------------------------------------------------------
    preamble_len: int = 63          # Länge der Präambel (m-Sequenz): 31, 63, 127, 255

    # --- Symbolfolge ------------------------------------------------------
    sequence_preset: str = "PN-Folge (zufällig)"
    sequence_text: str = "0 1 2 3"  # für "Eigene Symbole", "Eigene Bits", "Text (ASCII)"
    seq_len: int = 1000             # Länge der Vorlagen in Symbolen
    repetitions: int = 1            # Wiederholungen der Folge

    # --- Empfänger --------------------------------------------------------
    max_cfo_hz: float = 20000.0     # Suchbereich Frequenzversatz um f_if [Hz]
    track_timing: bool = True       # Abtastzeitpunkt nachführen (Taktabweichung)

    @property
    def sps(self) -> int:
        """Abtastwerte pro Symbol."""
        return max(2, int(round(self.fs / self.symbol_rate)))

    @property
    def rs(self) -> float:
        """Tatsächliche Symbolrate (nach Rundung von sps)."""
        return self.fs / self.sps

    @property
    def M(self) -> int:
        return {"DBPSK": 2, "DQPSK": 4}[self.modulation]

    @property
    def bandwidth(self) -> float:
        """Belegte Bandbreite [Hz]."""
        return self.rs * (1 + self.rolloff)

    def check(self) -> str:
        """-> Fehlertext oder ''."""
        if self.modulation not in ("DBPSK", "DQPSK"):
            return "Modulation muss DBPSK oder DQPSK sein"
        if not 0 < self.rolloff <= 1:
            return "Roll-off muss zwischen 0 und 1 liegen"
        if self.preamble_len not in (31, 63, 127, 255):
            return "Präambellänge muss 31, 63, 127 oder 255 sein"
        half = self.bandwidth / 2
        if abs(self.f_if) + half > self.fs / 2 - 200:
            return "Signal (ZF %.0f Hz ± %.0f Hz) passt nicht in ±%.0f Hz" % (self.f_if, half, self.fs / 2)
        if self.sps < 4:
            return "Symbolrate zu hoch (mindestens 4 Abtastwerte pro Symbol)"
        return ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Config":
        d = json.loads(text)
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})
