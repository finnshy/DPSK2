"""Präambel (m-Sequenz) und frei definierbare Symbolfolgen.

Ein DPSK-Symbol d (0..M-1) bedeutet eine Phasenänderung um d * 360°/M
gegenüber dem vorherigen Symbol:
    DBPSK: 0 -> 0°, 1 -> 180°
    DQPSK: 0 -> 0°, 1 -> 90°, 2 -> 180°, 3 -> 270°
Bits werden Gray-codiert auf Symbole abgebildet (DQPSK: 00->0, 01->1, 11->2, 10->3).
"""
import re

import numpy as np

PRESETS = [
    "PN-Folge (zufällig)",
    "Nullen (konstante Phase)",
    "Phasensprung 180° je Symbol",
    "Phasenrampe +90° je Symbol",
    "Eigene Symbole",
    "Eigene Bits",
    "Text (ASCII)",
]

# Rückkopplungen für m-Sequenzen (Fibonacci-LFSR), Grad -> Abgriffe
_TAPS = {5: (5, 3), 6: (6, 5), 7: (7, 6), 8: (8, 6, 5, 4), 9: (9, 5), 10: (10, 7)}

# Gray-Code: Bitwert -> Symbol
_GRAY = {2: [0, 1], 4: [0, 1, 3, 2]}


def mseq(degree: int) -> np.ndarray:
    """m-Sequenz der Länge 2^degree - 1 (Bits 0/1)."""
    taps = _TAPS[degree]
    state = [1] * degree
    out = []
    for _ in range(2 ** degree - 1):
        out.append(state[-1])
        fb = 0
        for t in taps:
            fb ^= state[t - 1]
        state = [fb] + state[:-1]
    return np.array(out, dtype=np.uint8)


def preamble(length: int) -> np.ndarray:
    """BPSK-Präambel (+1/-1) aus einer m-Sequenz."""
    degree = int(np.log2(length + 1))
    if 2 ** degree - 1 != length or degree not in _TAPS:
        raise ValueError("Präambellänge muss 31, 63, 127, 255, 511 oder 1023 sein")
    return 1.0 - 2.0 * mseq(degree)


def bits_to_symbols(bits, M: int) -> np.ndarray:
    k = int(np.log2(M))
    bits = np.asarray(bits, dtype=np.uint8)
    if len(bits) % k:
        bits = np.concatenate([bits, np.zeros(k - len(bits) % k, np.uint8)])
    vals = bits.reshape(-1, k) @ (1 << np.arange(k - 1, -1, -1))
    return np.array(_GRAY[M], dtype=np.int64)[vals]


def symbols_to_bits(syms, M: int) -> np.ndarray:
    k = int(np.log2(M))
    inv = np.argsort(_GRAY[M])                      # Symbol -> Bitwert
    vals = inv[np.asarray(syms, dtype=np.int64) % M]
    return ((vals[:, None] >> np.arange(k - 1, -1, -1)) & 1).astype(np.uint8).ravel()


def build(cfg) -> np.ndarray:
    """Symbolfolge (int 0..M-1) gemäß Konfiguration."""
    M, n = cfg.M, int(cfg.seq_len)
    p = cfg.sequence_preset
    if p == PRESETS[0]:
        k = int(np.log2(M))
        b = np.tile(mseq(9), int(np.ceil(n * k / 511)))[:n * k]
        seq = bits_to_symbols(b, M)
    elif p == PRESETS[1]:
        seq = np.zeros(n, np.int64)
    elif p == PRESETS[2]:
        seq = np.full(n, M // 2, np.int64)
    elif p == PRESETS[3]:
        if M != 4:
            raise ValueError("Phasenrampe +90° gibt es nur bei DQPSK")
        seq = np.ones(n, np.int64)
    elif p == PRESETS[4]:
        tokens = [t for t in re.split(r"[\s,;]+", cfg.sequence_text.strip()) if t]
        try:
            seq = np.array([int(t) for t in tokens], dtype=np.int64)
        except ValueError:
            raise ValueError("Eigene Symbole: nur ganze Zahlen, getrennt durch Leerzeichen/Komma")
        if np.any((seq < 0) | (seq >= M)):
            raise ValueError("Eigene Symbole: Werte müssen zwischen 0 und %d liegen" % (M - 1))
    elif p == PRESETS[5]:
        s = re.sub(r"[\s,;]", "", cfg.sequence_text)
        if not s or set(s) - {"0", "1"}:
            raise ValueError("Eigene Bits: nur 0 und 1 erlaubt")
        seq = bits_to_symbols([int(c) for c in s], M)
    elif p == PRESETS[6]:
        data = cfg.sequence_text.encode("utf-8")
        if not data:
            raise ValueError("Text ist leer")
        seq = bits_to_symbols(np.unpackbits(np.frombuffer(data, np.uint8)), M)
    else:
        raise ValueError("Unbekannte Vorlage: %s" % p)
    seq = np.tile(seq, max(1, int(cfg.repetitions)))
    if len(seq) == 0:
        raise ValueError("Symbolfolge ist leer")
    return seq


def describe(seq, M: int, max_items: int = 24) -> str:
    step = 360 // M
    head = " ".join(str(int(s)) for s in seq[:max_items])
    more = " ..." if len(seq) > max_items else ""
    return "%d Symbole: %s%s  (je Symbol %s)" % (
        len(seq), head, more, ", ".join("%d=%d°" % (i, i * step) for i in range(M)))
