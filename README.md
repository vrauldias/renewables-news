# Radar de Combustíveis Renováveis

Buscador automático de notícias sobre combustíveis renováveis e bioenergia (SAF, biometano, biogás, biodiesel, hidrogênio verde, amônia verde, etc.). O sistema coleta as preferências de cada destinatário, busca notícias recentes no Google News, usa um LLM para filtrar o que é realmente relevante, resume e agrupa notícias sobre o mesmo fato, e envia um boletim por e-mail personalizado para cada pessoa.

## Como funciona

1. **`coleta_preferencias.py`** — busca as preferências dos destinatários (quais categorias e idiomas cada um quer receber) em uma lista do SharePoint, autenticando via MSAL com certificado, e gera `preferencias.json`.
2. **`main.py`** — orquestra todo o processo: obtém o token do Microsoft Graph, roda a etapa 1, busca as notícias brutas por termo/idioma no Google News, chama o filtro de IA, monta o HTML e envia um e-mail por destinatário.
3. **`filtro_ia.py`** — usa a API da Groq (compatível com a API da OpenAI) para descartar notícias irrelevantes, resumir as relevantes em uma frase e agrupar notícias que falam do mesmo evento/fato (com fallback local via `difflib` caso a IA falhe).

## Requisitos

- Python 3.10+
- Um app registrado no Microsoft Entra ID (Azure AD) com um certificado configurado, com permissão para enviar e-mail via Microsoft Graph (`Mail.Send`) e, se for usar a coleta de preferências, ler listas do SharePoint (`Sites.Read.All` ou escopo equivalente).
- Uma chave de API da [Groq](https://console.groq.com/) (ou adapte `filtro_ia.py` para outro provedor compatível com a API da OpenAI).

## Instalação

```bash
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha todos os valores (ver seção abaixo). Coloque o arquivo `.pem` da chave privada do certificado (usado na autenticação MSAL) na raiz do projeto — o nome padrão é `private_key.pem`, configurável via `PRIVATE_KEY_FILE_PATH`. Esse arquivo nunca deve ser commitado.

## Variáveis de ambiente (`.env`)

| Variável | Descrição |
|---|---|
| `GROQ_API_KEY` | Chave de API da Groq, usada em `filtro_ia.py`. |
| `TENANT_ID`, `CLIENT_ID`, `CERT_THUMBPRINT` | Dados do app registrado no Entra ID, usados na autenticação MSAL (Microsoft Graph e SharePoint). |
| `PRIVATE_KEY_FILE_PATH` | Caminho do arquivo `.pem` com a chave privada do certificado. |
| `EMAIL_REMETENTE` | Caixa de e-mail (licenciada no Microsoft 365) a partir da qual os boletins são enviados via Graph. |
| `NOME_BOLETIM` | Nome exibido no assunto do e-mail e no cabeçalho do boletim. |
| `LINK_PREFERENCIAS` | Link exibido no rodapé do e-mail para o destinatário alterar suas preferências. |
| `SHAREPOINT_SITE_URL`, `SHAREPOINT_LIST_NAME` | URL do site e nome da lista do SharePoint de onde as preferências dos destinatários são lidas. |

## Personalizando as categorias de busca

As categorias e termos de busca ficam em arquivos `.txt` separados por tabulação (`chave` \t `termo de busca no Google News`):

- `keywords-to-gnews.txt` — dicionário padrão (português).
- `keywords-to-gnews-en.txt`, `keywords-to-gnews-de.txt` — dicionários para inglês e alemão.
- `languages-to-gnews.txt` — mapeia o nome do idioma (como aparece no SharePoint) para o código de idioma usado pelo `gnews`.

Para adaptar o projeto a outro tema (não apenas combustíveis renováveis), basta editar essas listas com as categorias e termos desejados — o restante do pipeline (busca, filtro por IA, resumo, agrupamento e envio) não precisa mudar.

Se um destinatário não usa SharePoint para gerenciar preferências, você pode ignorar `coleta_preferencias.py` e gerar `preferencias.json` manualmente ou por outro processo — o formato esperado é uma lista de objetos com `email`, `keywords_for_display` e `search_configs` (veja `main.py` para os detalhes).

## Execução

```bash
python main.py
```

O script gera automaticamente os arquivos de cache (`cache_bruto.json`, `cache_filtrado.json`), a lista de links já enviados (`links_enviados.txt`) e os logs (`logs/`). Esses arquivos contêm dados de execução (e, no caso de `preferencias.json` e `links_enviados.txt`, e-mails de destinatários reais), por isso já estão no `.gitignore` e não devem ser commitados.

Para rodar periodicamente, agende `main.py` no Agendador de Tarefas do Windows, cron, ou outro orquestrador de sua preferência.
