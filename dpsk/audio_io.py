"""Soundkarten- und WAV-Ein-/Ausgabe."""
import threading

import numpy as np
from scipy.io import wavfile

try:
    import sounddevice as sd
except Exception:          # z. B. keine PortAudio-Bibliothek
    sd = None


def available() -> bool:
    return sd is not None


def rescan():
    """PortAudio neu initialisieren, damit neu angesteckte Geräte erscheinen."""
    if sd is not None:
        sd._terminate()
        sd._initialize()


def list_devices(kind: str):
    """kind = 'input' | 'output' -> Liste (index, name)."""
    if sd is None:
        return []
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            out.append((i, "%d: %s [%s]" % (i, d["name"], api)))
    return out


def device_table() -> str:
    lines = ["Eingabegeräte:"] + ["  " + n for _, n in list_devices("input")]
    lines += ["Ausgabegeräte:"] + ["  " + n for _, n in list_devices("output")]
    return "\n".join(lines)


def play(x: np.ndarray, fs: int, device=None, blocking=True, loop=False):
    """Abspielen; loop=True wiederholt endlos bis stop()."""
    if sd is None:
        raise RuntimeError("sounddevice nicht verfügbar")
    sd.play(np.asarray(x, dtype=np.float32), fs, device=device, loop=loop)
    if blocking and not loop:
        sd.wait()


def stop():
    if sd is not None:
        sd.stop()


class Recorder:
    """Aufnahme bis stop() oder bis max_seconds erreicht ist."""

    def __init__(self, fs: int, channels: int, device=None, max_seconds: float = 60.0):
        if sd is None:
            raise RuntimeError("sounddevice nicht verfügbar")
        self.fs, self.channels, self.device = fs, channels, device
        self.max_frames = int(max_seconds * fs)
        self._chunks, self._n = [], 0
        self._done = threading.Event()
        self.level = 0.0

    def _cb(self, indata, frames, time, status):
        self._chunks.append(indata.copy())
        self._n += frames
        self.level = float(np.max(np.abs(indata))) if frames else 0.0
        if self._n >= self.max_frames:
            self._done.set()
            raise sd.CallbackStop

    def start(self):
        self._stream = sd.InputStream(samplerate=self.fs, channels=self.channels,
                                      device=self.device, dtype="float32", callback=self._cb)
        self._stream.start()

    def stop(self) -> np.ndarray:
        self._done.set()
        self._stream.stop()
        self._stream.close()
        if not self._chunks:
            return np.zeros((0, self.channels), np.float32)
        return np.concatenate(self._chunks)[:self.max_frames]

    def wait(self) -> np.ndarray:
        self._done.wait()
        return self.stop()

    @property
    def seconds(self) -> float:
        return self._n / self.fs


def record(seconds: float, fs: int, channels: int, device=None) -> np.ndarray:
    if sd is None:
        raise RuntimeError("sounddevice nicht verfügbar")
    x = sd.rec(int(seconds * fs), samplerate=fs, channels=channels, device=device, dtype="float32")
    sd.wait()
    return x


def read_wav(path: str):
    """-> (float-Array N x Kanäle, fs)"""
    fs, x = wavfile.read(path)
    if x.dtype == np.int16:
        x = x / 32768.0
    elif x.dtype == np.int32:
        x = x / 2147483648.0
    elif x.dtype == np.uint8:
        x = (x - 128) / 128.0
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    return x, fs


def write_wav(path: str, x: np.ndarray, fs: int):
    x = np.clip(np.asarray(x, dtype=np.float64), -1, 1)
    wavfile.write(path, fs, (x * 32767).astype(np.int16))
