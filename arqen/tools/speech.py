import base64
import shutil
import subprocess
import tempfile
import threading
import uuid
import asyncio
import ctypes
import re
import unicodedata
import math
import time

_speech_lock = threading.Lock()
_current_alias: str | None = None
_current_process = None
_audio_decode_process = None
_speech_generation = 0
_speech_done = threading.Event()
_speech_cancelled = False
_edge_loop = None
_edge_task = None
_audio_level_callback = None
_kokoro_pipeline = None


def set_audio_level_callback(callback) -> None:
    """Register a lightweight callback receiving normalized audio levels (0..1)."""
    global _audio_level_callback
    _audio_level_callback = callback


def _emit_audio_level(level: float) -> None:
    callback = _audio_level_callback
    if callback is not None:
        try:
            callback(max(0.0, min(1.0, level)))
        except Exception:
            pass


def _analyze_audio(audio_path: str, generation: int) -> None:
    """Decode MP3 to low-rate PCM and report RMS while the file is playing."""
    try:
        process = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-re", "-i", audio_path, "-f", "s16le", "-ac", "1", "-ar", "2000", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        while True:
            # 400 bytes at 2 kHz / 16-bit mono is roughly 100 ms of audio.
            chunk = process.stdout.read(400)
            if not chunk or generation != _speech_generation:
                break
            samples = [int.from_bytes(chunk[index:index + 2], "little", signed=True) for index in range(0, len(chunk) - 1, 2)]
            if samples:
                rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
                _emit_audio_level(min(1.0, rms * 10.0))
        process.terminate()
    except Exception:
        return
    finally:
        if generation == _speech_generation:
            time.sleep(0.25)
        _emit_audio_level(0.0)


def _play_and_analyze_audio(audio_path: str, generation: int, player_path: str) -> None:
    """Play and measure the same PCM stream so visualization cannot drift."""
    global _current_process, _audio_decode_process
    decoder = None
    player = None
    try:
        decoder = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", audio_path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        player = subprocess.Popen(
            [player_path, "-nodisp", "-autoexit", "-loglevel", "quiet", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _audio_decode_process = decoder
        _current_process = player
        assert decoder.stdout is not None and player.stdin is not None
        while generation == _speech_generation:
            chunk = decoder.stdout.read(3200)
            if not chunk:
                break
            player.stdin.write(chunk)
            player.stdin.flush()
            samples = [int.from_bytes(chunk[index:index + 2], "little", signed=True) for index in range(0, len(chunk) - 1, 2)]
            if samples:
                rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
                _emit_audio_level(min(1.0, rms * 10.0))
        player.stdin.close()
        player.wait()
    except Exception:
        return
    finally:
        for process in (decoder, player):
            if process is not None and process.poll() is None:
                process.terminate()
        _audio_decode_process = None
        _current_process = None
        _emit_audio_level(0.0)


def _speech_clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]\(https?://[^)]*\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bwww\.\S+", "", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__|~~|\*|_|#+)", "", text)
    text = re.sub(r"([:/\\|])\1+", " ", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = "".join(char for char in text if unicodedata.category(char) not in {"So", "Sk"})
    return re.sub(r"\s+", " ", text).strip()


def _looks_english(text: str) -> bool:
    """Conservative heuristic used only to select the optional Kokoro voice."""
    words = set(re.findall(r"[a-z]+", text.casefold()))
    english_markers = {
        "a", "an", "and", "are", "can", "could", "do", "for", "from", "hello",
        "how", "i", "is", "it", "my", "of", "please", "say", "the", "this",
        "to", "want", "was", "what", "with", "you", "your",
    }
    swedish_markers = {"att", "det", "den", "du", "jag", "kan", "med", "och", "som", "är"}
    return len(words & english_markers) >= 2 and not words.intersection(swedish_markers)


def _speak_kokoro(text: str, reset: bool = True) -> bool:
    """Speak English locally with Kokoro when the optional dependency is available."""
    global _kokoro_pipeline, _current_process
    try:
        from kokoro import KPipeline
        import numpy as np
        import soundfile as sf
    except Exception:
        return False

    if reset:
        stop_speech()
        global _speech_cancelled
        with _speech_lock:
            _speech_cancelled = False
    _speech_done.clear()
    with _speech_lock:
        generation = _speech_generation

    def worker() -> None:
        audio_path = str(Path(tempfile.gettempdir()) / f"arqen_kokoro_{uuid.uuid4().hex}.wav")
        try:
            if _kokoro_pipeline is None:
                _kokoro_pipeline = KPipeline(lang_code="a")
            pieces = [result.audio.detach().cpu().numpy() for result in _kokoro_pipeline(text, voice="af_heart")]
            if not pieces:
                return
            with _speech_lock:
                if generation != _speech_generation:
                    return
            sf.write(audio_path, np.concatenate(pieces), 24000)
            player = shutil.which("ffplay")
            if player:
                _play_and_analyze_audio(audio_path, generation, player)
        except Exception:
            return
        finally:
            _speech_done.set()
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass

    threading.Thread(target=worker, daemon=True, name="arqen-kokoro-tts").start()
    return True


def stop_speech() -> None:
    global _current_alias, _current_process, _audio_decode_process, _speech_generation, _edge_loop, _edge_task, _speech_cancelled
    with _speech_lock:
        _speech_generation += 1
        _speech_cancelled = True
        if _edge_loop is not None and _edge_task is not None:
            try:
                _edge_loop.call_soon_threadsafe(_edge_task.cancel)
            except RuntimeError:
                pass
        if _current_alias and hasattr(ctypes, "windll"):
            ctypes.windll.winmm.mciSendStringW(f"stop {_current_alias}", None, 0, None)
            ctypes.windll.winmm.mciSendStringW(f"close {_current_alias}", None, 0, None)
        if _current_process is not None:
            try:
                _current_process.terminate()
            except Exception:
                pass
        if _audio_decode_process is not None:
            try:
                _audio_decode_process.terminate()
            except Exception:
                pass
        _current_alias = None
        _current_process = None
        _audio_decode_process = None
        _emit_audio_level(0.0)
        _speech_done.set()
from pathlib import Path
from typing import Any

from arqen.tools.base import Tool


def _speak_edge(text: str, reset: bool = True) -> bool:
    try:
        import edge_tts
    except Exception:
        return False

    if reset:
        stop_speech()
        global _speech_cancelled
        with _speech_lock:
            _speech_cancelled = False
    _speech_done.clear()
    with _speech_lock:
        generation = _speech_generation

    def worker() -> None:
        global _current_alias, _current_process, _edge_loop, _edge_task
        audio_path = str(Path(tempfile.gettempdir()) / f"arqen_tts_{uuid.uuid4().hex}.mp3")
        try:
            loop = asyncio.new_event_loop()
            _edge_loop = loop
            _edge_task = loop.create_task(
                edge_tts.Communicate(text, voice="sv-SE-MattiasNeural").save(audio_path)
            )
            try:
                loop.run_until_complete(_edge_task)
            finally:
                _edge_task = None
                _edge_loop = None
                loop.close()
            with _speech_lock:
                if generation != _speech_generation:
                    return
            player = shutil.which("ffplay")
            if player:
                _current_process = subprocess.Popen(
                    [player, "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                def start_audio_analysis() -> None:
                    if generation == _speech_generation:
                        threading.Thread(target=_analyze_audio, args=(audio_path, generation), daemon=True, name="arqen-audio-level").start()

                threading.Timer(0.22, start_audio_analysis).start()
                _current_process.wait()
                with _speech_lock:
                    _current_process = None
                return
            alias = f"arqen_tts_{uuid.uuid4().hex}"
            with _speech_lock:
                _current_alias = alias
            result = ctypes.windll.winmm.mciSendStringW(
                f'open "{audio_path}" type mpegvideo alias {alias}', None, 0, None
            )
            if result == 0:
                threading.Thread(target=_analyze_audio, args=(audio_path, generation), daemon=True, name="arqen-audio-level").start()
                with _speech_lock:
                    cancelled = generation != _speech_generation
                if cancelled:
                    ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                    return
                ctypes.windll.winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
                ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                with _speech_lock:
                    if _current_alias == alias:
                        _current_alias = None
        except asyncio.CancelledError:
            return
        except Exception:
            # Do not silently switch to a noticeably worse synthetic voice.
            # A future local neural voice can be added as an explicit provider.
            return
        finally:
            _speech_done.set()
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass

    threading.Thread(target=worker, daemon=True, name="arqen-tts").start()
    return True


class SpeakTextTool(Tool):
    name = "speak_text"
    description = "Reads text aloud using the built-in Windows speech engine."
    requires_confirmation = False
    arguments_schema = {"text": str}

    def run(self, arguments: dict[str, Any]) -> str:
        text = arguments["text"].strip()
        if not text:
            return "No text supplied for speech."
        speech_text = _speech_clean(re.sub(r"arqen", "Arkén", text, flags=re.IGNORECASE))
        if _looks_english(speech_text) and _speak_kokoro(speech_text):
            _speech_done.wait()
            return "Speech started with Kokoro English voice."
        fragments = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+|\n+", speech_text) if chunk.strip()]
        chunks: list[str] = []
        current = ""
        for fragment in fragments:
            candidate = f"{current} {fragment}".strip()
            if current and len(candidate) > 650:
                chunks.append(current)
                current = fragment
            else:
                current = candidate
        if current:
            chunks.append(current)
        if len(chunks) > 1 and all(len(chunk) <= 700 for chunk in chunks):
            for index, chunk in enumerate(chunks):
                if not _speak_edge(chunk, reset=index == 0):
                    break
                _speech_done.wait()
                with _speech_lock:
                    if _speech_cancelled:
                        return "Speech stopped."
            else:
                return "Speech started with Swedish neural voice."
        if _speak_edge(speech_text):
            _speech_done.wait()
            return "Speech started with Swedish neural voice."
        return "Svensk neural uppläsning är inte tillgänglig just nu. Ingen reservröst startades."
