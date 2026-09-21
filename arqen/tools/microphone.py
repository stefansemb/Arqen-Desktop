from __future__ import annotations

import threading
from typing import Callable


class MicrophoneRecorder:
    """Record the Windows default microphone and transcribe it locally."""

    def __init__(self, on_result: Callable[[str], None], on_status: Callable[[str], None]) -> None:
        self.on_result = on_result
        self.on_status = on_status
        self._stream = None
        self._chunks: list[object] = []
        self._lock = threading.Lock()
        self._transcribing = False

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> bool:
        if self.recording or self._transcribing:
            return False
        try:
            import sounddevice as sd
        except Exception as exc:
            self.on_status(f"MIC // ERROR // {exc}")
            return False
        self._chunks = []

        def callback(indata, frames, time_info, status) -> None:
            if status:
                self.on_status(f"MIC // {status}")
            with self._lock:
                self._chunks.append(indata.copy())

        try:
            self._stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=callback)
            self._stream.start()
            self.on_status("MIC // RECORDING")
            return True
        except Exception as exc:
            self._stream = None
            self.on_status(f"MIC // ERROR // {exc}")
            return False

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        finally:
            with self._lock:
                chunks = list(self._chunks)
                self._chunks = []
            threading.Thread(target=self._transcribe, args=(chunks,), daemon=True, name="arqen-whisper").start()

    def _transcribe(self, chunks: list[object]) -> None:
        self._transcribing = True
        try:
            if not chunks:
                self.on_status("MIC // EMPTY")
                return
            import numpy as np
            from faster_whisper import WhisperModel

            audio = np.concatenate(chunks, axis=0).reshape(-1)
            if len(audio) < 1600:
                self.on_status("MIC // TOO SHORT")
                return
            self.on_status("MIC // TRANSCRIBING")
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio, language="sv", vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                self.on_result(text)
                self.on_status("MIC // READY")
            else:
                self.on_status("MIC // NO SPEECH")
        except Exception as exc:
            self.on_status(f"MIC // ERROR // {exc}")
        finally:
            self._transcribing = False
