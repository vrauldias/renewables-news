# Radar de Combustíveis Renováveis

Buscador automático de notícias sobre combustíveis renováveis e bioenergia
(SAF, biometano, biogás, biodiesel, hidrogênio verde, amônia verde, etc.).

O sistema lê as preferências de cada destinatário, busca notícias recentes no
Google News, usa um LLM para descartar o irrelevante, **agrupa as notícias que
falam do mesmo fato entre todos os portais e idiomas**, resume cada evento em
uma frase e envia um boletim personalizado por e-mail.

O agrupamento é a parte não trivial e tem documento próprio:
**[docs/agrupamento.md](docs/agrupamento.md)** — inclui a medição em 412 edições
reais que motivou a reescrita, as causas de falha da versão anterior e o
algoritmo atual.

## O pipeline

```
preferências → coleta → triagem → AGRUPAMENTO GLOBAL → resumo → memória → envio
```

| Etapa | Módulo | O que faz |
|---|---|---|
| Preferências | `preferencias/fontes.py` | lê do Microsoft Lists ou de um `preferencias.json` |
| Coleta | `pipeline/coleta.py` | busca cada termo no Google News, uma vez por (termo, idioma) |
| Triagem | `pipeline/triagem.py` | LLM descarta o que não é fato novo do setor |
| Agrupamento | `pipeline/agrupamento.py` | dedup exata + blocos determinísticos + partição por LLM |
| Resumo | `pipeline/resumo.py` | uma frase por **evento** (não por notícia) |
| Memória | `pipeline/memoria.py` | evita reenviar o mesmo fato dias depois |
| Envio | `entrega/` | HTML do boletim + Microsoft Graph |

O agrupamento roda **uma vez sobre o pool inteiro**, com todos os tópicos e
idiomas juntos. Cada evento carrega as categorias que o trouxeram, e a
personalização por destinatário é um filtro aplicado no fim. É essa inversão
que impede a mesma notícia de sair duas vezes por ter vindo de duas buscas
diferentes — o modo de falha mais comum de um agregador por palavra-chave.

## Requisitos

- Python 3.10+
- Uma chave de API de **um** provedor de IA (ver abaixo).
- Um app registrado no Microsoft Entra ID (Azure AD) com certificado, com
  permissão `Mail.Send` no Microsoft Graph e, se for usar o Microsoft Lists para
  as preferências, leitura de listas do SharePoint (`Sites.Read.All` ou equivalente).

## Instalação

```bash
pip install -r requirements.txt
cp .env.example .env      # e preencha
```

Coloque o `.pem` com a chave privada do certificado na raiz do projeto (nome
padrão `private_key.pem`, configurável em `PRIVATE_KEY_FILE_PATH`). Ele nunca
deve ser commitado — já está no `.gitignore`, junto com `.env` e o `header.png`.

## Escolhendo o provedor de IA

Todo o projeto conversa com o modelo por uma única camada
(`llm/provedores.py`). Trocar de provedor é trocar duas linhas do `.env`:

```ini
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

| `LLM_PROVIDER` | Variável da chave | Modelo padrão | Observação |
|---|---|---|---|
| `groq` | `GROQ_API_KEY` | `openai/gpt-oss-120b` | rápido e barato |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` | endpoint compatível com OpenAI |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5` | SDK oficial; melhor qualidade no agrupamento |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | |
| `openrouter` | `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct` | acesso a vários modelos |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` | |
| `mistral` | `MISTRAL_API_KEY` | `mistral-large-latest` | |
| `azure-openai` | `AZURE_OPENAI_API_KEY` | (o nome do seu deployment) | precisa de `AZURE_OPENAI_ENDPOINT` |
| `ollama` | — | `llama3.1:8b` | roda local, sem chave; use `OLLAMA_BASE_URL` |

Preencha só a chave do provedor que vai usar; as outras podem ficar vazias.
Provedores compatíveis com a API da OpenAI usam o pacote `openai`; Claude usa o
SDK oficial `anthropic`.

### Modelo por tarefa

As três tarefas podem usar modelos diferentes:

```ini
LLM_MODELO_TRIAGEM=openai/gpt-oss-20b
LLM_MODELO_AGRUPAMENTO=openai/gpt-oss-120b
LLM_MODELO_RESUMO=openai/gpt-oss-20b
```

Se for economizar em alguma etapa, economize na **triagem**. O **agrupamento** é
a tarefa sensível: usar um modelo pequeno demais nessa etapa é exatamente o que
produzia o problema descrito em [docs/agrupamento.md](docs/agrupamento.md).
Com `LLM_PROVIDER=anthropic` há ainda o controle de esforço por tarefa
(`LLM_EFFORT_*`: `low`, `medium`, `high`, `xhigh`, `max`).

Em branco, cada tarefa usa o modelo padrão do provedor.

### Como adicionar um provedor novo

Se ele expõe API compatível com a da OpenAI, basta uma linha em `PROVEDORES`,
no topo de `llm/provedores.py`:

```python
"meu-provedor": ("MEU_PROVEDOR_API_KEY", "https://api.exemplo.com/v1", "modelo-padrao"),
```

Nenhuma outra parte do projeto muda.

## Categorias e termos de busca

Ficam em arquivos separados por tabulação (`categoria` ⇥ `termos no Google News`):

- `keywords-to-gnews.txt` — português (padrão)
- `keywords-to-gnews-en.txt`, `keywords-to-gnews-de.txt` — inglês e alemão
- `languages-to-gnews.txt` — nome do idioma → código usado pelo `gnews`

A primeira coluna precisa bater exatamente com as opções cadastradas nas
colunas de escolha da lista — é por esse texto que o de-para é feito.

Uma categoria pode listar vários termos separados por ` OR `. Cada termo é
buscado **separadamente** no Google News e todos os resultados são creditados à
mesma categoria. (A versão anterior mandava a expressão inteira entre aspas, o
que o Google trata como busca por frase exata: toda categoria com mais de um
termo devolvia zero resultado.)

Para adaptar o projeto a outro tema — não apenas combustíveis renováveis —
basta trocar o conteúdo desses arquivos. O restante do pipeline não muda.

## Preferências dos destinatários

`FONTE_PREFERENCIAS=sharepoint` lê de uma lista do Microsoft Lists alimentada
por um formulário (vale sempre a resposta mais recente de cada e-mail). Para
montar a lista e o formulário do zero:
[docs/microsoft-list.md](docs/microsoft-list.md).

`FONTE_PREFERENCIAS=arquivo` usa um `preferencias.json` mantido à mão — veja
[`preferencias.exemplo.json`](preferencias.exemplo.json). É a opção para quem
não usa Microsoft 365 ou quer só testar.

## Execução

```bash
python main.py
```

Modos úteis durante o ajuste:

```bash
# roda tudo, não envia e-mail, não grava histórico, gera previa.html
python main.py --simular

# desliga a IA no agrupamento (só a camada determinística) — não gasta API
python main.py --simular --sem-ia-no-agrupamento
```

O script gera `cache_bruto.json`, `cache_filtrado.json`,
`historico_eventos.json`, `preferencias.json` e a pasta `logs/`. Todos contêm
dados de execução (e, em `preferencias.json`, e-mails de destinatários reais),
por isso já estão no `.gitignore`.

Para rodar periodicamente, agende `main.py` no Agendador de Tarefas do Windows,
no cron, ou em outro orquestrador de sua preferência.
