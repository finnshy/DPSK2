# BPSK-Test: Frequenzoffset und Zeitsynchronisation

Einfacher Testaufbau, um den Frequenzoffset zwischen den Oszillatoren (PLLs) von I/Q-Modulator und
I/Q-Demodulator zu messen und darzustellen. Ein Barker-Code dient zur Zeitsynchronisation, eine
Early-Late-Regelung führt den Abtastzeitpunkt nach (Symbol Timing Recovery).

```
Sender:    [Barker-13][Bits] -> ±1 -> Rechteckimpulse -> I (links), Q = 0 (rechts) -> Soundkarte -> I/Q-Modulator
Empfänger: I/Q-Demodulator -> Soundkarte -> Frequenzoffset -> Barker-Synchronisation -> Abtasten mit Timing-Regelung
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

## Zeitsynchronisation mit Barker-Code

Jeder Burst beginnt mit dem Barker-Code der Länge 13: `+1 +1 +1 +1 +1 −1 −1 +1 +1 −1 +1 −1 +1`.
Seine Autokorrelation hat eine Spitze von 13 und Nebenwerte von höchstens 1. Dadurch ist der
Beginn des ersten Symbols eindeutig.

1. Der gemessene Phasenverlauf wird aus dem Empfangssignal herausgerechnet. Übrig bleibt ein reelles
   ±1-Signal, allerdings nur bis auf ein Vorzeichen, weil die Phase aus r² nur bis auf 180° bestimmt ist.
2. Korrelation mit dem Barker-Code (als Rechteckimpulse): Die Spitze liegt genau am Beginn der
   Präambel. Ist sie negativ, wird das Signal invertiert; damit sind auch die Bits eindeutig.
3. **Symbol Timing Recovery:** Ab diesem Zeitpunkt wird jedes Symbol über seine Dauer integriert
   (Integrate & Dump). Zusätzlich wird ein Viertel Symbol früher und später integriert. Ist das Fenster
   zu spät, ist die „späte“ Integration kleiner als die „frühe“ (sie reicht weiter ins nächste Symbol),
   und das Fenster wird etwas nach vorne geschoben, und umgekehrt. So folgt der Empfänger einer
   Taktabweichung zwischen Sender- und Empfänger-Soundkarte. Bei „Nur Einsen“ gibt es keine
   Symbolwechsel, dann bleibt das Fenster stehen.

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
| Symbolrate [Bd] | Wie am Sender |
| Max. Aufnahmedauer [s] | Aufnahme endet spätestens danach |
| Timing-Regelverstärkung | Wie schnell das Abtastfenster nachgeführt wird (Standard 0,05; 0 = keine Nachführung) |
| WAV laden / speichern | Aufnahme speichern und später erneut auswerten |
| Erneut auswerten | Gleiche Aufnahme mit geänderten Einstellungen |
| Vergleich mit Sender | Bitfolge, Symbole pro Burst und eigene Bits wie am Sender, dann werden die Bitfehler gezählt |
| Zeitsignal-Ausschnitt | Welche Symbole im Zeitsignal-Plot gezeigt werden (ab Symbol, Anzahl) |

## Anzeige im Empfänger

**Reiter „Frequenzoffset“**

| Grafik | Was man sieht |
|---|---|
| Spektrum | Empfangssignal und r²; die rote Linie liegt bei 2·Δf. |
| Frequenzoffset über der Zeit | Ist der Offset konstant, driftet er oder springt er? |
| Phase Empfang − Sender | Abgewickelte Phase in Umdrehungen; die Steigung ist der Offset. |
| Symbole (I/Q) | Ohne Korrektur liegen die Punkte auf einem Kreis (Phase läuft um), mit Korrektur und Timing auf zwei Punkten. |

**Reiter „Zeitsynchronisation“**

| Grafik | Was man sieht |
|---|---|
| Barker-13-Korrelation | Schmale Spitze am Beginn der Präambel; Güte nahe 1 = sauber erkannt. |
| Timing-Nachführung | Wie weit das Abtastfenster gegenüber einem starren Raster verschoben wurde. Eine gleichmäßige Rampe bedeutet Taktabweichung zwischen den Soundkarten. |
| Zeitsignal und Abtastzeitpunkte | Rohsignal I (grau), Signal nach Frequenzkorrektur (blau), Symbolgrenzen (senkrechte Linien), Barker-Präambel (orange), Abtastzeitpunkte mit Integrationsergebnis (rot) und entschiedene Bits (oben, B = Barker). |

Im Textfeld stehen Frequenzoffset, Drift, Phasendrehung je Symbol, Barker-Erkennung, Timing-Nachführung,
die ersten Bits und die Bitfehler.

## Dateien

| Datei | Inhalt |
|---|---|
| `bpsk.py` | Senden, Offset-Messung, Barker-Synchronisation, Timing Recovery, Simulation für Tests |
| `sender.py` | Sender-GUI |
| `receiver.py` | Empfänger-GUI (`py -3.9 receiver.py aufnahme.wav` wertet ohne GUI aus) |
| `audio_io.py` | Soundkarte und WAV |
| `tests/test_bpsk.py` | Tests ohne Hardware |
