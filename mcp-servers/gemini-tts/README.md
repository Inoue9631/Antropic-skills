# Gemini TTS MCP

Servidor MCP que dá ao Claude a capacidade de **transformar texto em áudio falado** usando os modelos de voz do Google Gemini. Funciona no Claude Desktop e no Claude Code.

Casos de uso no tributário:
- Ouvir o radar da Reforma Tributária, o Tax News ou um parecer no trajeto ou entre reuniões.
- Gerar um briefing em formato de podcast com dois locutores.
- Narrar treinamentos internos e materiais de onboarding.

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `gemini_tts_speak` | Narra um texto com uma voz. Aceita instrução de estilo ("tom executivo, pausado"), idioma, modelo, formato `wav`/`mp3` e reprodução automática. Divide e emenda sozinho textos longos. |
| `gemini_tts_dialogue` | Gera áudio com **dois locutores** a partir de um roteiro `Nome: fala`, cada um com sua voz. |
| `gemini_tts_list_voices` | Lista as 30 vozes pré-definidas com o estilo de cada uma, os modelos disponíveis e a configuração atual. |

Os arquivos são salvos em `~/gemini-tts/` (configurável), e a ferramenta devolve o caminho, a duração e o modelo usado.

## Pré-requisitos

1. **Chave da API Gemini**: gere em <https://aistudio.google.com/apikey>.
2. **uv** (gerenciador Python): <https://docs.astral.sh/uv/getting-started/installation/>
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. *(Opcional)* **ffmpeg**, para salvar em MP3 e para tocar áudio no Linux.

Clone o repositório e anote o caminho da pasta `mcp-servers/gemini-tts`.

## Instalação no Claude Desktop

Abra *Settings → Developer → Edit Config* e adicione em `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gemini-tts": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\caminho\\para\\Antropic-skills\\mcp-servers\\gemini-tts", "gemini-tts-mcp"],
      "env": {
        "GEMINI_API_KEY": "sua-chave-aqui",
        "GEMINI_TTS_LANGUAGE": "pt-BR",
        "GEMINI_TTS_OUTPUT_DIR": "C:\\Users\\seu-usuario\\Documents\\gemini-tts"
      }
    }
  }
}
```

No macOS, troque os caminhos por algo como `/Users/seu-usuario/Antropic-skills/mcp-servers/gemini-tts`. Reinicie o Claude Desktop. As ferramentas aparecem no menu de conectores.

> Se o Claude Desktop não encontrar o `uv`, use o caminho completo (ex.: `C:\\Users\\seu-usuario\\.local\\bin\\uv.exe` ou `/Users/seu-usuario/.local/bin/uv`).

## Instalação no Claude Code

```bash
claude mcp add gemini-tts \
  -e GEMINI_API_KEY=sua-chave-aqui \
  -e GEMINI_TTS_LANGUAGE=pt-BR \
  -- uv run --directory /caminho/para/Antropic-skills/mcp-servers/gemini-tts gemini-tts-mcp
```

Use `--scope user` para deixar disponível em todos os projetos. Confira com `claude mcp list`.

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | (obrigatória) | Chave da API Gemini. `GOOGLE_API_KEY` também é aceita. |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-tts` | Modelo padrão. Para volume alto e menor custo: `gemini-3.8-flash-lite-tts`. |
| `GEMINI_TTS_VOICE` | `Kore` | Voz padrão. |
| `GEMINI_TTS_LANGUAGE` | detecção automática | Idioma padrão, ex.: `pt-BR`. |
| `GEMINI_TTS_OUTPUT_DIR` | `~/gemini-tts` | Pasta onde os áudios são salvos. |

## Exemplos de pedidos ao Claude

- "Lê esse resumo em voz alta com a voz Charon, em tom executivo, e toca pra mim."
- "Transforma o radar da reforma tributária de hoje em um podcast de 3 minutos com a Ana (voz Kore) e o Beto (voz Puck), e salva em mp3."
- "Quais vozes do Gemini combinam com um treinamento formal?"

Formato de roteiro para diálogo:

```
Ana: Bom dia! Hoje vamos falar das novas notas técnicas do IBS e da CBS.
Beto: E o que muda para o nosso fechamento de outubro?
```

## Segurança e custos

- A chave fica só na configuração local do MCP; não é gravada em arquivos do projeto nem enviada ao Claude.
- Cada chamada consome créditos da API Gemini. Textos longos viram várias chamadas.
- O texto é enviado ao Google para síntese. Não use com dados sigilosos sem conferir a política de dados da sua conta Gemini (no plano pago, os dados não são usados para treinar modelos).

## Desenvolvimento

```bash
uv run --extra dev pytest -q   # testes sem chamar a API (usam um cliente falso)
```

## Limitações

- O diálogo aceita exatamente dois locutores por áudio.
- Textos muito longos são divididos em blocos de cerca de 4.000 caracteres; pode haver pequenas variações de entonação entre blocos.
- MP3 exige ffmpeg. Sem ele, use WAV.
- A lista de vozes é uma referência das 30 vozes pré-definidas. O modelo 3.8 aceita outras, e o servidor repassa qualquer nome informado.
