from __future__ import annotations

import threading
import os
from typing import Callable

_whisper_model = None
_whisper_lock = threading.Lock()


class MicrophoneRecorder:
    """Record the Windows default microphone and transcribe it locally."""

    def __init__(self, on_result: Callable[[str], None], on_status: Callable[[str], None]) -> None:
        self.on_result = on_result
        self.on_status = on_status
        self._stream = None
        self._chunks: list[object] = []
        self._lock = threading.Lock()
        self._transcribing = False
        # Optional live input level (0..1) for visualisation; called from the audio thread.
        self.on_level: Callable[[float], None] | None = None

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
            on_level = self.on_level
            if on_level is not None:
                try:
                    rms = float((indata ** 2).mean()) ** 0.5
                    on_level(min(1.0, rms * 12.0))
                except Exception:
                    pass

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
        self.on_status("MIC // STOPPING")
        threading.Thread(target=self._finish_recording, args=(stream,), daemon=True, name="arqen-mic-stop").start()

    def _finish_recording(self, stream) -> None:
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            self.on_status(f"MIC // ERROR // {exc}")
            return
        with self._lock:
            chunks = list(self._chunks)
            self._chunks = []
        print(f"Microphone captured {len(chunks)} audio chunks", flush=True)
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
            self.on_status("MIC // LOADING MODEL")
            print("Microphone transcription started", flush=True)
            global _whisper_model
            with _whisper_lock:
                if _whisper_model is None:
                    print("Whisper model loading started", flush=True)
                    whisper_model = os.environ.get("ARQEN_WHISPER_MODEL", "small")
                    whisper_device = os.environ.get("ARQEN_WHISPER_DEVICE", "cpu")
                    whisper_compute = os.environ.get(
                        "ARQEN_WHISPER_COMPUTE_TYPE",
                        "int8" if whisper_device == "cpu" else "float16",
                    )
                    print(
                        f"Whisper configuration: model={whisper_model} "
                        f"device={whisper_device} compute={whisper_compute}",
                        flush=True,
                    )
                    _whisper_model = WhisperModel(
                        whisper_model,
                        device=whisper_device,
                        compute_type=whisper_compute,
                    )
                    print("Whisper model loading completed", flush=True)
                model = _whisper_model
            self.on_status("MIC // DECODING")
            print("Whisper decoding started", flush=True)
            segments, _ = model.transcribe(
                audio,
                language="sv",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt="Svenskt tal på svenska. Arqen Desktop.",
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            print("Whisper decoding completed", flush=True)
            if text:
                self.on_result(text)
                self.on_status("MIC // READY")
            else:
                self.on_status("MIC // NO SPEECH")
        except Exception as exc:
            self.on_status(f"MIC // ERROR // {exc}")
        finally:
            self._transcribing = False
