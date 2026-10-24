import wave
from types import SimpleNamespace

import pytest

from gemini_tts_mcp import audio, server


class FakeModels:
    def __init__(self):
        self.calls = []

    async def generate_content(self, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        pcm = b"\x01\x00" * 2400  # 0,1 s a 24 kHz
        part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm, mime_type="audio/L16;codec=pcm;rate=24000"))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")])


@pytest.fixture
def fake(monkeypatch, tmp_path):
    models = FakeModels()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    monkeypatch.setattr(server, "get_client", lambda: client)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    return models


def test_split_text_respects_limit():
    text = "\n\n".join(["Frase curta. " * 40] * 10)
    chunks = audio.split_text(text, max_chars=600)
    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)
    assert "".join(chunks).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")


def test_split_text_long_word_run():
    chunks = audio.split_text("a" * 1500, max_chars=500)
    assert [len(c) for c in chunks] == [500, 500, 500]


def test_split_script_keeps_lines_whole():
    script = "\n".join(f"Ana: fala número {i}" if i % 2 else f"Beto: resposta {i}" for i in range(200))
    chunks = audio.split_script(script, max_chars=300)
    assert all(line.startswith(("Ana:", "Beto:")) for c in chunks for line in c.splitlines())


async def test_speak_writes_wav(fake, tmp_path):
    result = await server.gemini_tts_speak(
        text="Olá, equipe tributária.", voice="Charon", style="Leia em tom executivo",
        language_code="pt-BR", output_path="teste",
    )
    path = tmp_path / "teste.wav"
    assert result["file_path"] == str(path.resolve())
    with wave.open(str(path)) as wav:
        assert wav.getframerate() == 24_000 and wav.getnchannels() == 1
    call = fake.calls[0]
    assert call.model == server.DEFAULT_MODEL
    assert call.contents == "Leia em tom executivo:\nOlá, equipe tributária."
    assert call.config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Charon"
    assert call.config.speech_config.language_code == "pt-BR"
    assert result["duration_seconds"] == 0.1


async def test_speak_long_text_concatenates(fake, monkeypatch):
    monkeypatch.setattr(audio, "MAX_CHARS_PER_CHUNK", 100)
    monkeypatch.setattr(audio.split_text, "__defaults__", (100,))
    result = await server.gemini_tts_speak(text="Parágrafo de teste. " * 30)
    assert result["chunks"] == len(fake.calls) > 1
    assert result["duration_seconds"] > 0.1 * len(fake.calls)


async def test_dialogue_builds_multispeaker_config(fake):
    result = await server.gemini_tts_dialogue(
        script="Ana: Saiu nova nota técnica do IBS.\nBeto: O que muda para nós?",
        speakers=[server.Speaker(name="Ana", voice="Kore"), server.Speaker(name="Beto", voice="Puck")],
        audio_format="wav",
    )
    configs = fake.calls[0].config.speech_config.multi_speaker_voice_config.speaker_voice_configs
    assert [(c.speaker, c.voice_config.prebuilt_voice_config.voice_name) for c in configs] == [("Ana", "Kore"), ("Beto", "Puck")]
    assert result["file_path"].endswith(".wav")


async def test_dialogue_rejects_unknown_speaker(fake):
    with pytest.raises(server.ToolError, match="Carla"):
        await server.gemini_tts_dialogue(
            script="Ana: oi\nBeto: olá",
            speakers=[server.Speaker(name="Ana", voice="Kore"), server.Speaker(name="Carla", voice="Puck")],
        )


async def test_mp3_conversion(fake, tmp_path):
    if not audio.shutil.which("ffmpeg"):
        pytest.skip("ffmpeg não instalado")
    result = await server.gemini_tts_speak(text="Teste mp3", audio_format="mp3")
    assert result["file_path"].endswith(".mp3")


def test_list_voices():
    data = server.gemini_tts_list_voices()
    assert len(data["voices"]) == 30
    assert data["defaults"]["model"] == server.DEFAULT_MODEL


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(server, "_client", None)
    with pytest.raises(server.ToolError, match="GEMINI_API_KEY"):
        server.get_client()
