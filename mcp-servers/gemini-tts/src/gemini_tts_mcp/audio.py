"""Utilitários de áudio: divisão de texto, montagem de WAV, conversão e reprodução."""

from __future__ import annotations

import io
import platform
import re
import shutil
import subprocess
import wave
from pathlib import Path

# Formato padrão do áudio devolvido pelo Gemini TTS: PCM 16 bits, mono, 24 kHz.
DEFAULT_SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2
CHANNELS = 1

# Tamanho máximo de cada requisição. Textos maiores são divididos em blocos
# e o áudio é concatenado, o que permite narrar documentos longos.
MAX_CHARS_PER_CHUNK = 4_000


def sample_rate_from_mime(mime_type: str | None) -> int:
    """Lê a taxa de amostragem de um mime type como 'audio/L16;codec=pcm;rate=24000'."""
    if mime_type:
        match = re.search(r"rate=(\d+)", mime_type)
        if match:
            return int(match.group(1))
    return DEFAULT_SAMPLE_RATE


def split_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    """Divide o texto em blocos de até max_chars, respeitando parágrafos e frases."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        flush()
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        # Parágrafo grande demais: quebra por frases e, em último caso, por tamanho.
        for sentence in re.split(r"(?<=[.!?;:])\s+", paragraph):
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                if current:
                    flush()
                chunks.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            candidate = f"{current} {sentence}" if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush()
                current = sentence
    flush()
    return chunks


def split_script(script: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    """Divide um roteiro de diálogo por linhas, sem cortar a fala de um locutor."""
    chunks: list[str] = []
    current = ""
    for line in script.strip().splitlines():
        if not line.strip():
            continue
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return chunks


def pcm_to_wav(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def pcm_duration_seconds(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> float:
    return len(pcm) / (sample_rate * SAMPLE_WIDTH * CHANNELS)


def silence(seconds: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    return b"\x00" * (int(seconds * sample_rate) * SAMPLE_WIDTH * CHANNELS)


def write_audio(pcm: bytes, sample_rate: int, path: Path, audio_format: str) -> Path:
    """Grava o áudio em WAV ou MP3 (MP3 exige ffmpeg instalado)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wav_bytes = pcm_to_wav(pcm, sample_rate)
    if audio_format == "wav":
        path.write_bytes(wav_bytes)
        return path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "O formato mp3 exige o ffmpeg instalado e no PATH. "
            "Instale o ffmpeg ou use audio_format='wav'."
        )
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-qscale:a", "2", str(path)],
        input=wav_bytes,
        check=True,
        capture_output=True,
    )
    return path


def play_audio(path: Path) -> str:
    """Toca o arquivo em segundo plano no player nativo do sistema operacional."""
    system = platform.system()
    if system == "Darwin":
        command = ["afplay", str(path)]
    elif system == "Windows":
        # O Start-Process abre o player padrão do Windows para wav e mp3.
        command = ["powershell", "-NoProfile", "-Command", f"Start-Process -FilePath '{path}'"]
    else:
        for player, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
                             ("paplay", []), ("aplay", ["-q"])):
            if shutil.which(player) and (player == "ffplay" or path.suffix == ".wav"):
                command = [player, *args, str(path)]
                break
        else:
            return "Nenhum player encontrado (instale ffmpeg/ffplay ou pulseaudio)."
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"Não foi possível tocar o áudio: {exc}"
    return "Reprodução iniciada."
