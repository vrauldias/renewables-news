# Montando a lista de preferências no Microsoft Lists

O script `coleta_preferencias.py` lê as preferências dos destinatários de uma
lista do **Microsoft Lists** (que por baixo é uma lista do SharePoint, acessada
aqui pela REST API do SharePoint). Este documento descreve como montar essa
lista e o formulário do zero.

> Se você não usa Microsoft 365, pule para [Alternativa sem Microsoft Lists](#alternativa-sem-microsoft-lists)
> no fim deste documento — o resto do pipeline funciona sem nenhuma dependência da Microsoft.

## 1. Criar a lista

Em [lists.live.com](https://lists.live.com) ou no app **Listas** do Microsoft 365,
crie uma lista em branco. O nome que você der é o valor de `SHAREPOINT_LIST_NAME`
no `.env`.

Adicione duas colunas do tipo **Escolha (Choice)**, ambas com
**"Permitir várias seleções" ativado**:

| Coluna | Tipo | Conteúdo |
|---|---|---|
| Categorias de notícias | Escolha, múltipla seleção | Uma opção por categoria que o usuário pode assinar |
| Idiomas | Escolha, múltipla seleção | Uma opção por idioma disponível |

As opções de **categorias** precisam bater exatamente com a primeira coluna dos
arquivos `keywords-to-gnews*.txt`, e as de **idiomas** com a primeira coluna de
`languages-to-gnews.txt` — é por esse texto que o script faz o de-para para os
termos de busca do Google News.

Exemplo de opções de categorias (as mesmas do `keywords-to-gnews.txt` deste repositório):

```
Sustainable Aviation Fuel
Usinas de Açúcar e Álcool
Papel & Celulose
Combustível Marítimo
Macaúba
Capiaçu
Biochar
```

Exemplo de opções de idiomas (as mesmas do `languages-to-gnews.txt`):

```
Português
Inglês
Alemão
```

Você **não** precisa criar colunas de e-mail nem de data: o script usa as colunas
nativas `Author` (quem criou o item) e `Modified` (quando foi alterado), que o
SharePoint mantém automaticamente em todo item.

## 2. Criar o formulário

Dentro da lista, use **Formulários → Novo formulário** (o botão *Forms* na barra
superior do Lists). Monte o formulário com as duas colunas de escolha marcadas
como obrigatórias e compartilhe o link com quem vai receber o boletim.

Esse link é também o que você coloca em `LINK_PREFERENCIAS` no `.env` — ele
aparece no rodapé de cada e-mail enviado, para o destinatário poder alterar suas
escolhas.

Como o formulário roda autenticado no tenant, cada resposta grava o e-mail do
respondente na coluna `Author`. Um usuário pode responder quantas vezes quiser:
o script agrupa por e-mail e **usa sempre a resposta com `Modified` mais recente**,
descartando as anteriores. Não é necessário editar nem limpar respostas antigas.

## 3. Descobrir o nome interno das colunas

Este é o ponto que mais causa erro. O SharePoint guarda dois nomes por coluna:

- **Nome de exibição** — o que você vê na tela e pode renomear quando quiser.
- **Nome interno** — gerado a partir do nome de exibição **no momento da criação**
  e **congelado para sempre**, mesmo que você renomeie a coluna depois.

A REST API só aceita o **nome interno**. Além disso, caracteres não-ASCII e
espaços viram sequências `_xNNNN_` no nome interno. Alguns exemplos reais:

| Nome de exibição na criação | Nome interno |
|---|---|
| `CategoriasNoticias` | `CategoriasNoticias` |
| `EscolherLínguas` | `EscolherL_x00ed_nguas` (o `í` virou `_x00ed_`) |
| `Quais notícias?` | `Quais_x0020_not_x00ed_cias_x003f_` |

Ou seja: se você criou a coluna com um nome com acento ou espaço e depois a
renomeou, o nome interno continua sendo o codificado do nome **antigo**.

Para descobrir os nomes internos da sua lista, abra no navegador (já autenticado
no tenant):

```
https://<seu-site>/_api/web/lists/getbytitle('<NomeDaLista>')/fields?$select=Title,InternalName,TypeAsString&$filter=Hidden eq false
```

Procure pelas suas colunas e copie o valor de `InternalName` para o `.env`:

```env
SHAREPOINT_FIELD_CATEGORIES=CategoriasNoticias
SHAREPOINT_FIELD_LANGUAGES=EscolherL_x00ed_nguas
```

> **Dica:** para evitar esse problema por completo, crie as colunas com nomes
> simples, sem espaços e sem acentos (`CategoriasNoticias`, `EscolherLinguas`) e
> só depois renomeie para o texto bonito que o usuário verá. O nome interno fica
> limpo e igual ao que você digitou na criação.

## 4. Permissões no Microsoft Entra ID

O app registrado precisa de permissão de aplicativo para ler a lista. Duas opções:

- **`Sites.Read.All`** (SharePoint) — mais simples, dá leitura em todos os sites.
- **`Sites.Selected`** (SharePoint) — mais restrito e recomendado: você concede
  acesso explicitamente só ao site que hospeda a lista.

Em ambos os casos é necessário o consentimento do administrador do tenant. A
autenticação é feita por certificado (não por segredo de cliente): faça o upload
do `.cer` no registro do app e aponte `PRIVATE_KEY_FILE_PATH` para o `.pem`
correspondente e `CERT_THUMBPRINT` para a impressão digital exibida no portal.

## 5. Formato dos dados

Exportando a lista para CSV, cada linha fica assim (veja
[`exemplo-preferencias.csv`](exemplo-preferencias.csv) neste diretório):

```csv
"CreatedTime","CreatedUser","CategoriasNoticias","EscolherLinguas"
"19/06/2025 23:00","fulano@exemplo.com","[""Biochar"",""Capiaçu""]","[""Português"",""Inglês""]"
```

As colunas de escolha múltipla chegam pela API como um objeto com uma lista
dentro (`{"results": ["Biochar", "Capiaçu"]}`) — é assim que
`coleta_preferencias.py` as lê.

Ao final, o script grava `preferencias.json` já traduzido para termos de busca:

```json
[
  {
    "email": "fulano@exemplo.com",
    "keywords_for_display": ["Biochar", "Capiaçu"],
    "search_configs": [
      {
        "lang_code": "pt-419",
        "query_string": "\"biochar OR biocarbono\" OR \"capiaçu OR capim elefante\""
      },
      {
        "lang_code": "en",
        "query_string": "\"biochar\" OR \"elephant grass OR capiacu\""
      }
    ]
  }
]
```

## Alternativa sem Microsoft Lists

O Microsoft Lists é usado **apenas** para coletar preferências. Se você não tem
Microsoft 365 — ou quer só rodar para si mesmo — pule `coleta_preferencias.py`
por completo e escreva o `preferencias.json` acima na mão (ou gere a partir de
um Google Forms, um banco de dados, o que preferir). O `main.py` só precisa do
arquivo no formato mostrado.

Nesse cenário, `SHAREPOINT_*` no `.env` ficam vazios e a ETAPA 1 do `main.py`
pode ser comentada. O envio de e-mail via Microsoft Graph continua exigindo o
registro no Entra ID — para substituí-lo por SMTP comum, troque a função
`enviar_email_graph()` em `main.py` por uma chamada `smtplib`.
