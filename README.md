# DPSK-Einträgerübertragung zur Phasenanalyse

Testsoftware, um den Frequenz- und Phasenversatz zwischen den Oszillatoren (PLLs) von Modulator und
Demodulator zu untersuchen. Der Sender schickt eine Präambel und eine frei definierte Symbolfolge als
DPSK-Signal über die Soundkarte an den I/Q-Modulator. Der Empfänger kennt diese Folge und misst für jedes
Symbol, wie stark und wie die Phase des Empfangssignals von der gesendeten abweicht.

Die OFDM-Software in `C:\Users\Finn\ofdm_link` ist davon unabhängig.

```
Sender:    Symbolfolge -> differentielle Codierung -> RRC-Impulsformung -> Mischung auf ZF -> I/Q -> [Modulator]
Empfänger: [Demodulator] -> I/Q -> Frequenzsuche -> Mischen + Matched Filter -> Präambel suchen -> Symbole -> Phasenanalyse
```

## Start

```
py -3.9 -m pip install --user -r requirements.txt
py -3.9 sender.py
py -3.9 receiver.py
py -3.9 -m pytest -v tests          # Modultests ohne Hardware
```

Ablauf mit Hardware:
1. In beiden Programmen dieselben Einstellungen und dieselbe Symbolfolge wählen
   (oder am Sender „Konfiguration speichern“ und am Empfänger „Konfiguration laden“).
2. Empfänger: **„Aufnahme starten“**.
3. Sender: **„Einmal senden“** oder **„Dauersenden“**.
4. Empfänger: **„Aufnahme stoppen und auswerten“** (oder warten, bis „Max. Dauer“ erreicht ist).

Als Audiogerät wählen beide Programme automatisch das **WDM-KS**-Gerät der USB-Soundkarte, falls vorhanden.
Nur dort kommt der Eingang in Stereo (I und Q) und ohne Windows-Audioverarbeitung an.

## Signal

- **DBPSK** oder **DQPSK**: Die Information steckt in der *Phasenänderung* von Symbol zu Symbol
  (DBPSK: 0°/180°, DQPSK: 0°/90°/180°/270°). Ein fester Phasenversatz stört deshalb nicht. Ein
  Frequenzversatz Δf dreht jede Phasenänderung um 360° · Δf / Symbolrate. Ohne Korrektur kann ein
  DPSK-Empfänger richtig entscheiden, solange diese Drehung unter 180°/M bleibt (M = 2 oder 4); bei
  1000 Bd und DQPSK sind das ±125 Hz.
- **Präambel**: m-Sequenz (BPSK), 31 bis 255 Symbole. Der Empfänger sucht sie *differentiell*, also über
  das Produkt aufeinanderfolgender Symbole. Das funktioniert unabhängig von Phase und Frequenzversatz.
- **ZF (Zwischenfrequenz)**: Das Signal liegt im I/Q-Basisband nicht bei 0 Hz, sondern bei `f_if`
  (Standard 3 kHz). So stören Gleichanteil, Trägerleck und Netzbrummen weniger, und der Versatz wird
  mit Vorzeichen sichtbar.
- **Frequenzsuche**: grob über das Spektrum im Bereich ZF ± „Max. Freq.-Versatz“ (Standard ±20 kHz),
  dann fein über die Präambel. Das Signal muss dabei im Bereich ±24 kHz der Soundkarte bleiben.

## Sender (`sender.py`)

| Bereich | Element | Bedeutung |
|---|---|---|
| Audiogerät | Ausgang | Soundkarten-Ausgang zum I/Q-Modulator (links = I, rechts = Q). |
| Signal | Modulation | DBPSK oder DQPSK. |
| | Symbolrate [Bd] | Symbole pro Sekunde. Wird so gerundet, dass 48000 / Symbolrate eine ganze Zahl ist. |
| | Roll-off | Flankensteilheit des Impulsfilters (0…1). Bandbreite = Symbolrate · (1 + Roll-off). |
| | ZF-Frequenz [Hz] | Lage des Signals im I/Q-Basisband. |
| | Präambellänge | 31, 63, 127 oder 255 Symbole. Länger = sicherere Erkennung bei schlechtem Signal. |
| | Pegel (0..1) | Spitzenpegel am Ausgang. 0,2 war mit dem Modulator bewährt. |
| | Pause Dauersenden [s] | Abstand zwischen den Bursts beim Dauersenden. |
| Symbolfolge | Vorlage | Siehe unten. |
| | Länge (Vorlagen) | Anzahl Symbole für die Vorlagen. |
| | Wiederholungen | Wie oft die Folge hintereinander gesendet wird. |
| | Textfeld | Inhalt für „Eigene Symbole“, „Eigene Bits“ und „Text (ASCII)“. |
| Senden | Einmal senden | Ein Burst. |
| | Dauersenden | Burst + Pause, endlos bis „Stopp“. Gut, um den Versatz über längere Zeit zu beobachten. |
| | Als WAV speichern | Signal als Stereo-WAV (zum Testen des Empfängers ohne Hardware). |

Die graue Zeile unter den Einstellungen zeigt Abtastwerte pro Symbol, Bitrate, das belegte Band und bis zu
welchem Versatz ein DPSK-Empfänger ohne Korrektur noch richtig entscheiden kann.

### Symbolfolgen

| Vorlage | Inhalt | Wozu |
|---|---|---|
| PN-Folge (zufällig) | Pseudozufällige Symbole | Normaler Datenbetrieb, Fehlerraten messen. |
| Nullen (konstante Phase) | Phasenänderung immer 0° | Nach der Präambel ein reiner Träger: Phase und Frequenz der Oszillatoren direkt sichtbar. |
| Phasensprung 180° je Symbol | Immer 180° | Linie bei ZF ± Symbolrate/2. |
| Phasenrampe +90° je Symbol | Immer +90° (nur DQPSK) | Linie bei ZF + Symbolrate/4: Prüft, ob die Drehrichtung (I/Q) stimmt. |
| Eigene Symbole | z. B. `0 1 2 3 0 0 2` | DQPSK: 0 = 0°, 1 = 90°, 2 = 180°, 3 = 270°; DBPSK: 0 = 0°, 1 = 180°. |
| Eigene Bits | z. B. `0011 0110` | Gray-codiert: DQPSK 00→0°, 01→90°, 11→180°, 10→270°. |
| Text (ASCII) | z. B. `Hallo` | Text als Bits (UTF-8). |

Der Empfänger muss dieselbe Folge eingestellt haben, sonst stimmen Fehlerzählung und Phasenmessung
nach der Präambel nicht.

## Empfänger (`receiver.py`)

| Bereich | Element | Bedeutung |
|---|---|---|
| Audiogerät | Eingang | Soundkarten-Eingang vom I/Q-Demodulator (Stereo). |
| Aufnahme | Max. Dauer [s] | Aufnahme endet spätestens danach und wird ausgewertet. |
| | Aufnahme starten / stoppen und auswerten | |
| | WAV laden und auswerten | Stereo-WAV (z. B. vom Sender gespeichert). |
| | Erneut auswerten | Gleiche Aufnahme mit geänderten Einstellungen auswerten. |
| Kanalsimulation | aktiv + Werte | Nur bei WAV: SNR, Frequenzversatz, Drift, Phasenrauschen und Taktabweichung künstlich hinzufügen. |
| Ergebnis | Burst | Welcher Burst angezeigt wird (bei mehreren in einer Aufnahme). |
| | Rohsignal ab [s], Länge [ms], Zeigen | Ausschnitt für die Zeitbereichsgrafiken im Reiter „Rohsignal“. |
| | Symboldaten als CSV exportieren | Je Symbol: Zeit, Empfangs- und Sendesymbol, Phasen, Momentanfrequenz, Differenzphasen. |
| | Rohaufnahme als WAV speichern | Zum späteren Auswerten. |
| Signal | wie beim Sender | Zusätzlich „Max. Freq.-Versatz [Hz]“: Suchbereich um die ZF. |

### Ergebnistext

| Angabe | Bedeutung |
|---|---|
| Frequenzversatz gesamt | Mittlerer Versatz Empfangs- gegen Sendeoszillator über den Burst (grob aus dem Spektrum + fein aus der Phase). |
| Phasendrehung je Symbol | Drehung jeder Phasenänderung durch den Versatz, verglichen mit der Entscheidungsgrenze. |
| Frequenzdrift | Änderung des Versatzes während des Bursts [Hz/s]. |
| Phasenrauschen | Streuung der Phase nach Abzug von Versatz und Drift [° rms]. Enthält auch den Anteil des Rauschens. |
| SNR | Aus der Abweichung der korrigierten Symbole vom Sollpunkt. |
| Symbolfehler ohne / mit Frequenzkorrektur | Wie viele DPSK-Entscheidungen falsch wären: ohne jede Korrektur bzw. nach Abzug des gemessenen Versatzes. |

### Grafiken

**Reiter „Phase“**

| Grafik | Was man sieht |
|---|---|
| Phasendifferenz Empfang − Sender | Abgewickelte Phase über der Zeit in Umdrehungen. Die Steigung ist der Frequenzversatz. |
| Phasenrest | Dieselbe Phase nach Abzug des mittleren Versatzes. Eine Parabel bedeutet Drift, Zittern bedeutet Phasenrauschen, Stufen bedeuten Phasensprünge. |
| Momentane Frequenzabweichung | Geglätteter Versatz über der Zeit. |
| Phasenänderung je Symbol | Was ein DPSK-Empfänger ohne Korrektur sieht (blau) gegenüber dem Gesendeten (schwarz); Fehlentscheidungen rot. |

**Reiter „Signal“**: Spektrum der Aufnahme (Soll-ZF und gemessene Lage), Symbole nach voller Korrektur
(Farbe = Zeit), DPSK-Entscheidungsebene ohne und mit Korrektur, Frequenzversatz je Burst (bei Dauersenden)
bzw. Symbolbetrag.

**Reiter „Rohsignal“** (funktioniert auch, wenn kein Burst erkannt wird):

| Grafik | Was man sieht |
|---|---|
| Spektrogramm | Frequenzinhalt über der Zeit. |
| Stärkste Spektrallinie − ZF | Bei „Nullen (konstante Phase)“ der Frequenzversatz über der Zeit. |
| I/Q | Zeitverlauf im gewählten Ausschnitt. |
| Phase relativ zur ZF | Abgewickelte Phase im Ausschnitt; die Steigung ist der Momentanversatz. |

## Kommandozeile

```
py -3.9 sender.py --wav tx.wav --config dpsk_config.json
py -3.9 sender.py --play --out-dev 26 --loop
py -3.9 receiver.py --wav aufnahme.wav --config dpsk_config.json --csv symbole.csv
py -3.9 receiver.py --record 10 --in-dev 27 --save-raw rx.wav
py -3.9 sender.py --list-devices
```

Hardwaretest (sendet und nimmt gleichzeitig auf, wertet aus):

```
py -3.9 tests/hw_test.py --list
py -3.9 tests/hw_test.py --out 26 --in 27 --bursts 3
py -3.9 tests/hw_test.py --out 26 --in 27 --preset "Nullen (konstante Phase)" --len 3000 --save rx.wav
```

Optionen: `--mod`, `--rate` (Symbolrate), `--amp`, `--fif`, `--preset`, `--len`, `--bursts`, `--save`.
Die Gerätenummern können sich ändern (`--list`).

## Module (`dpsk/`)

| Datei | Inhalt |
|---|---|
| `config.py` | Alle Parameter |
| `sequences.py` | m-Sequenz-Präambel, Vorlagen und eigene Symbolfolgen, Gray-Codierung |
| `modem.py` | Sender, Empfänger, Phasenanalyse, Rohsignal-Analyse |
| `channel.py` | Kanalsimulation: Versatz, Drift, Phasenrauschen, Taktabweichung, Rauschen |
| `audio_io.py` | Soundkarte und WAV |
| `gui_common.py` | Gemeinsame GUI-Teile |

## Erste Messung mit dem Modulator (09.11.2026)

Aufbau: USB Audio CODEC (WDM-KS), I/Q-Modulator und -Demodulator 2,4 GHz, Kabel mit Dämpfungsglied.
Gesendet: Präambel + „Nullen (konstante Phase)“, also ein Träger bei 3 kHz.

- Am Empfänger kommt **kein durchgehender Träger** an, sondern **kurze Impulse alle 2,29 ms**
  (Wiederholrate 435 Hz); dazwischen ist das Signal etwa 20 dB schwächer.
- Bei jedem Impuls springt die Phase weiter. Das Spektrum ist ein Kamm aus Linien bei ZF + k · 435 Hz
  über mehrere kHz. Die scheinbaren „435 Hz Versatz“ sind nur diese Wiederholrate.
- Dieselben Impulse sind **auch ohne Sendesignal** da (vom Trägerleck des Modulators).
- Folge: Die Präambel wird nicht sicher erkannt (Metrik 0,46–0,48 statt nahe 1), und Daten kommen
  nicht durch.

Das spricht dafür, dass einer der beiden Oszillatoren **nicht eingerastet** ist und periodisch über die
Sollfrequenz hinwegläuft (z. B. eine PLL im Suchlauf). Nur in dem kurzen Moment, in dem beide
Frequenzen nahe beieinander liegen, fällt das Signal in den Bereich der Soundkarte. Zu prüfen:
Lock-Anzeige der PLLs, Referenztakt, Schleifenfilter, Versorgung; ggf. mit dem Spektrumanalysator
am HF-Ausgang des Modulators und am LO des Demodulators nachmessen.
