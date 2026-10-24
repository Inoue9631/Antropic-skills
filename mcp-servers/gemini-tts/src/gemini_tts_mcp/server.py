"""Servidor MCP que expõe o Text-to-Speech do Gemini como ferramentas para o Claude."""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from google import genai
from google.genai import errors, types
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from gemini_tts_mcp import audio

DEFAULT_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
DEFAULT_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Kore")
DEFAULT_LANGUAGE = os.environ.get("GEMINI_TTS_LANGUAGE") or None
OUTPUT_DIR = Path(
    os.environ.get("GEMINI_TTS_OUTPUT_DIR", Path.home() / "gemini-tts")
).expanduser()

TTS_MODELS = {
    "gemini-3.8-flash-tts": "Qualidade alta e boa expressividade. Padrão recomendado.",
    "gemini-3.8-flash-lite-tts": "Mais rápido e barato, indicado para volume alto e narrações longas.",
    "gemini-3.1-flash-tts-preview": "Geração anterior (preview).",
}

# Vozes pré-definidas do Gemini TTS e o estilo de cada uma. A API aceita outros
# nomes (vozes novas ou personalizadas), então a lista é referência, não trava.
PREBUILT_VOICES = {
    "Zephyr": "Brilhante", "Puck": "Animada", "Charon": "Informativa",
    "Kore": "Firme", "Fenrir": "Empolgada", "Leda": "Jovial",
    "Orus": "Firme", "Aoede": "Leve", "Callirrhoe": "Descontraída",
    "Autonoe": "Brilhante", "Enceladus": "Sussurrada", "Iapetus": "Clara",
    "Umbriel": "Descontraída", "Algieba": "Suave", "Despina": "Suave",
    "Erinome": "Clara", "Algenib": "Rouca", "Rasalgethi": "Informativa",
    "Laomedeia": "Animada", "Achernar": "Delicada", "Alnilam": "Firme",
    "Schedar": "Equilibrada", "Gacrux": "Madura", "Pulcherrima": "Assertiva",
    "Achird": "Amigável", "Zubenelgenubi": "Casual", "Vindemiatrix": "Gentil",
    "Sadachbia": "Vívida", "Sadaltager": "Experiente", "Sulafat": "Calorosa",
}

AudioFormat = Literal["wav", "mp3"]

mcp = MCPServer(
    name="gemini-tts",
    instructions=(
        "Converte texto em áudio falado com o Gemini TTS. Use gemini_tts_speak para "
        "narrar um texto com uma voz, gemini_tts_dialogue para roteiros com dois "
        "locutores (ex.: podcast ou briefing) e gemini_tts_list_voices para escolher "
        "vozes. Os arquivos são salvos em disco e o caminho é devolvido. Textos longos "
        "são divididos automaticamente; não é preciso resumir antes."
    ),
)

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ToolError(
                "GEMINI_API_KEY não configurada. Gere uma chave em "
                "https://aistudio.google.com/apikey e informe-a na configuração do servidor MCP."
            )
        _client = genai.Client(api_key=api_key)
    return _client


class Speaker(BaseModel):
    name: Annotated[str, Field(description="Nome do locutor exatamente como aparece no roteiro, ex.: 'Ana'.")]
    voice: Annotated[str, Field(description="Nome da voz do Gemini para este locutor, ex.: 'Kore'.")]


def _slug(text: str, limit: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:limit].rstrip("-") or "audio"


def _resolve_output(output_path: str | None, hint: str, audio_format: AudioFormat) -> Path:
    if output_path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = OUTPUT_DIR / path
        if path.suffix.lower() not in (".wav", ".mp3"):
            path = path.with_suffix(f".{audio_format}")
        return path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return OUTPUT_DIR / f"{stamp}-{_slug(hint)}.{audio_format}"


def _voice_config(voice: str) -> types.VoiceConfig:
    return types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))


async def _synthesize(contents: str, speech_config: types.SpeechConfig, model: str) -> tuple[bytes, int]:
    """Chama o Gemini e devolve (pcm, sample_rate) de um único bloco de texto."""
    response = await get_client().aio.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        ),
    )
    candidates = response.candidates or []
    parts = (candidates[0].content.parts if candidates and candidates[0].content else None) or []
    for part in parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data, audio.sample_rate_from_mime(part.inline_data.mime_type)
    reason = candidates[0].finish_reason if candidates else "sem candidatos"
    raise ToolError(f"O Gemini não devolveu áudio (motivo: {reason}). Revise o texto e tente novamente.")


async def _render(
    chunks: list[str],
    prefix: str,
    speech_config: types.SpeechConfig,
    model: str,
    output: Path,
    audio_format: AudioFormat,
    play: bool,
) -> dict:
    pcm_parts: list[bytes] = []
    sample_rate = audio.DEFAULT_SAMPLE_RATE
    for index, chunk in enumerate(chunks):
        try:
            pcm, sample_rate = await _synthesize(f"{prefix}{chunk}", speech_config, model)
        except errors.APIError as exc:
            raise ToolError(
                f"Erro da API Gemini no bloco {index + 1}/{len(chunks)} "
                f"({exc.code} {exc.status}): {exc.message}"
            ) from exc
        if pcm_parts:
            pcm_parts.append(audio.silence(0.35, sample_rate))
        pcm_parts.append(pcm)

    pcm_all = b"".join(pcm_parts)
    try:
        path = audio.write_audio(pcm_all, sample_rate, output, audio_format)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise ToolError(f"Não foi possível salvar o áudio em {output}: {exc}") from exc
    result = {
        "file_path": str(path.resolve()),
        "format": audio_format,
        "duration_seconds": round(audio.pcm_duration_seconds(pcm_all, sample_rate), 1),
        "model": model,
        "chunks": len(chunks),
    }
    if play:
        result["playback"] = audio.play_audio(path)
    return result


def _style_prefix(style: str | None) -> str:
    style = (style or "").strip().rstrip(":")
    return f"{style}:\n" if style else ""


@mcp.tool(
    annotations=ToolAnnotations(
        title="Gerar fala com Gemini TTS",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
async def gemini_tts_speak(
    text: Annotated[str, Field(min_length=1, description="Texto a ser falado. Textos longos são divididos e emendados automaticamente.")],
    voice: Annotated[str | None, Field(description="Voz do Gemini (ver gemini_tts_list_voices). Padrão: Kore ou GEMINI_TTS_VOICE.")] = None,
    style: Annotated[str | None, Field(description="Instrução de estilo em linguagem natural, ex.: 'Leia em tom executivo, calmo e pausado'.")] = None,
    language_code: Annotated[str | None, Field(description="Código BCP-47 do idioma, ex.: 'pt-BR'. Se omitido, o modelo detecta sozinho.")] = None,
    model: Annotated[str | None, Field(description="Modelo de TTS. Padrão: gemini-3.8-flash-tts.")] = None,
    audio_format: Annotated[AudioFormat, Field(description="Formato do arquivo: 'wav' (padrão) ou 'mp3' (exige ffmpeg).")] = "wav",
    output_path: Annotated[str | None, Field(description="Caminho do arquivo de saída. Relativo ao diretório de saída configurado. Se omitido, o nome é gerado.")] = None,
    play: Annotated[bool, Field(description="Se true, toca o áudio no computador assim que ficar pronto.")] = False,
) -> dict:
    """Converte um texto em áudio falado com uma única voz e salva o arquivo.

    Devolve o caminho absoluto do arquivo, a duração em segundos e o modelo usado.
    """
    speech_config = types.SpeechConfig(
        voice_config=_voice_config(voice or DEFAULT_VOICE),
        language_code=language_code or DEFAULT_LANGUAGE,
    )
    return await _render(
        chunks=audio.split_text(text),
        prefix=_style_prefix(style),
        speech_config=speech_config,
        model=model or DEFAULT_MODEL,
        output=_resolve_output(output_path, text, audio_format),
        audio_format=audio_format,
        play=play,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Gerar diálogo com Gemini TTS",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
async def gemini_tts_dialogue(
    script: Annotated[str, Field(min_length=1, description="Roteiro com uma fala por linha no formato 'Nome: fala'. Os nomes devem bater com os de speakers.")],
    speakers: Annotated[list[Speaker], Field(min_length=2, max_length=2, description="Os dois locutores do roteiro e a voz de cada um.")],
    style: Annotated[str | None, Field(description="Instrução de estilo para a conversa, ex.: 'Conversa de podcast, natural e animada'.")] = None,
    language_code: Annotated[str | None, Field(description="Código BCP-47 do idioma, ex.: 'pt-BR'.")] = None,
    model: Annotated[str | None, Field(description="Modelo de TTS. Padrão: gemini-3.8-flash-tts.")] = None,
    audio_format: Annotated[AudioFormat, Field(description="Formato do arquivo: 'wav' (padrão) ou 'mp3' (exige ffmpeg).")] = "wav",
    output_path: Annotated[str | None, Field(description="Caminho do arquivo de saída. Se omitido, o nome é gerado.")] = None,
    play: Annotated[bool, Field(description="Se true, toca o áudio assim que ficar pronto.")] = False,
) -> dict:
    """Gera um áudio com dois locutores a partir de um roteiro 'Nome: fala'.

    Útil para briefings em formato de podcast, treinamentos e simulações de reunião.
    """
    names_in_script = {
        match.group(1).strip()
        for match in re.finditer(r"^\s*([^:\n]{1,40}):", script, flags=re.MULTILINE)
    }
    missing = [s.name for s in speakers if s.name not in names_in_script]
    if missing:
        raise ToolError(
            f"Locutor(es) {missing} não aparecem no roteiro. Use linhas no formato "
            f"'{speakers[0].name}: texto'. Nomes encontrados: {sorted(names_in_script)}."
        )

    speech_config = types.SpeechConfig(
        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                types.SpeakerVoiceConfig(speaker=s.name, voice_config=_voice_config(s.voice))
                for s in speakers
            ]
        ),
        language_code=language_code or DEFAULT_LANGUAGE,
    )
    names = " e ".join(s.name for s in speakers)
    prefix = f"{style.strip().rstrip(':')}. " if style and style.strip() else ""
    prefix = f"{prefix}Produza a conversa a seguir entre {names}:\n"
    return await _render(
        chunks=audio.split_script(script),
        prefix=prefix,
        speech_config=speech_config,
        model=model or DEFAULT_MODEL,
        output=_resolve_output(output_path, f"dialogo-{names}", audio_format),
        audio_format=audio_format,
        play=play,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Listar vozes e modelos do Gemini TTS",
        read_only_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def gemini_tts_list_voices() -> dict:
    """Lista as vozes pré-definidas (com o estilo de cada uma), os modelos de TTS e a configuração atual."""
    return {
        "voices": [{"name": name, "style": style} for name, style in PREBUILT_VOICES.items()],
        "models": [{"id": model_id, "notes": notes} for model_id, notes in TTS_MODELS.items()],
        "defaults": {
            "model": DEFAULT_MODEL,
            "voice": DEFAULT_VOICE,
            "language_code": DEFAULT_LANGUAGE,
            "output_dir": str(OUTPUT_DIR),
        },
        "tips": [
            "Todas as vozes falam vários idiomas, inclusive português.",
            "Use 'style' para controlar tom, ritmo e emoção em linguagem natural.",
            "Para narrações longas e baratas, use o modelo gemini-3.8-flash-lite-tts.",
        ],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
