# BPSK-Test: Frequenzoffset sichtbar machen

Einfacher Testaufbau, um den Frequenzoffset zwischen den Oszillatoren (PLLs) von I/Q-Modulator und
I/Q-Demodulator zu messen und darzustellen.

```
Sender:    Bits -> ±1 -> Rechteckimpulse -> I (links), Q = 0 (rechts) -> Soundkarte -> I/Q-Modulator
Empfänger: I/Q-Demodulator -> Soundkarte (I links, Q rechts) -> Frequenzoffset messen und anzeigen
```

## Start

```
py -3.9 -m pip install --user -r requirements.txt
py -3.9 sender.py
py -3.9 receiver.py
py -3.9 -m pytest -v tests        # Tests ohne Hardware
```

1. Empfänger: **„Aufnahme starten“**.
2. Sender: **„Einmal senden“** oder **„Dauersenden“**.
3. Empfänger: **„Aufnahme stoppen und auswerten“**.

Beide Programme wählen automatisch das WDM-KS-Gerät der USB-Soundkarte (nur dort kommt der Eingang in
Stereo und ohne Windows-Audioverarbeitung an).

## Wie der Offset gemessen wird

Weicht der Empfänger-Oszillator um Δf vom Sender ab, dreht sich das empfangene Signal:

    r(t) = ±A · e^{j(2π·Δf·t + φ0)}

Beim Quadrieren fällt die BPSK-Modulation weg, weil (±1)² = 1 ist:

    r²(t) = A² · e^{j(2π·2Δf·t + 2φ0)}

Das Spektrum von r² hat also eine Linie bei 2·Δf, und die Phase von r² wächst gleichmäßig mit der Zeit.
Der Empfänger braucht dafür weder Synchronisation noch die gesendeten Bits. Eindeutig messbar ist
|Δf| < 12 kHz. Wird kein Burst erkannt, wertet er die ganze Aufnahme aus (z. B. nur das Trägerleck
des Modulators).

## Einstellungen

**Sender**

| Feld | Bedeutung |
|---|---|
| Ausgang | Soundkarte zum I/Q-Modulator |
| Symbolrate [Bd] | Symbole pro Sekunde (Standard 1000) |
| Pegel (0..1) | Ausgangspegel (0,2 hat mit dem Modulator funktioniert) |
| Symbole pro Burst | Länge eines Bursts (Standard 2000 = 2 s) |
| Pause Dauersenden [s] | Abstand zwischen den Bursts beim Dauersenden |
| Bitfolge | „Zufall“, „Nur Einsen (Träger)“ (reiner Träger) oder „Eigene Bits“ (wird wiederholt) |

**Empfänger**

| Feld | Bedeutung |
|---|---|
| Eingang | Soundkarte vom I/Q-Demodulator |
| Symbolrate [Bd] | Wie am Sender; nur für die Konstellation nötig |
| Max. Aufnahmedauer [s] | Aufnahme endet spätestens danach |
| WAV laden / speichern | Aufnahme speichern und später erneut auswerten |

## Anzeige im Empfänger

| Grafik | Was man sieht |
|---|---|
| Spektrum | Empfangssignal und r²; die rote Linie liegt bei 2·Δf. |
| Frequenzoffset über der Zeit | Ist der Offset konstant, driftet er oder springt er? |
| Phase Empfang − Sender | Abgewickelte Phase in Umdrehungen; die Steigung ist der Offset. |
| Symbole (I/Q) | Ohne Korrektur liegen die Punkte auf einem Kreis (Phase läuft um), mit Korrektur des gemessenen Offsets auf zwei Punkten. |

Im Textfeld stehen Frequenzoffset, Drift und die Phasendrehung je Symbol.

## Dateien

| Datei | Inhalt |
|---|---|
| `bpsk.py` | Senden, Offset-Messung, Simulation für Tests |
| `sender.py` | Sender-GUI |
| `receiver.py` | Empfänger-GUI (`py -3.9 receiver.py aufnahme.wav` wertet ohne GUI aus) |
| `audio_io.py` | Soundkarte und WAV |
| `tests/test_bpsk.py` | Tests ohne Hardware |
