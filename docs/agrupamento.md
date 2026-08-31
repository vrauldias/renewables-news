# Como o agrupamento funciona (e por que a versão anterior falhava)

## O problema observado

A queixa era simples: uma mesma notícia aparece em vários portais e o boletim
manda todas como se fossem eventos diferentes.

Foram analisadas **392 edições reais** do boletim — todos os `.msg` de
"AUTOMÁTICO – Net Zero News" da caixa de entrada que continham notícias,
somando **23.933 itens enviados**. Os números:

| Métrica | Valor |
|---|---|
| Itens por edição (média) | 61,1 |
| Itens que agruparam 2 ou mais portais | 3.140 (**13,1%**) |
| Pares do mesmo assunto que ficaram **separados** na mesma edição | **657** |
| Edições com pelo menos um par separado indevidamente | **250 de 392 (64%)** |
| Itens com **título idêntico** a outro na mesma edição | 101, em 86 edições (22%) |
| — destes, com o **mesmo veículo** também | 57 |
| Itens repetidos de um dia para o outro | **1.120** |
| Resumos vazios ou com a palavra "ERRO" | 751 (3,1%) |

Ter 57 itens com título idêntico **e** veículo idêntico dentro do mesmo e-mail
mostra que não é um problema de "a IA não percebeu que era parecido": esses
pares nunca chegaram a ser comparados.

## As cinco causas

**1. O agrupamento era feito dentro de cada tópico, nunca entre tópicos.**
No código anterior, `agrupar_noticias_hibrido` era chamado dentro do laço
`for chave, lista in noticias_relevantes_por_chave.items()`, com a chave sendo
`termo_de_busca|idioma`. Uma notícia sobre uma planta de biometano encontrada
pelas buscas de "Biogás" e de "Biometano" formava dois eventos independentes,
que nunca eram comparados entre si. O mesmo valia para o mesmo fato em
português e em inglês. Isso explica os títulos idênticos duplicados.

**2. A deduplicação final era por URL exata.**
`eventos_para_email_dict[link_principal]` só colapsa URLs byte a byte iguais.
Bastava um `?utm_source=`, um `www.`, um `/amp` ou o mesmo texto republicado em
outro endereço para escapar — e, quando colapsava, jogava fora o cluster gêmeo
inteiro, perdendo os "também visto em" dele.

**3. O prompt de agrupamento não definia o critério.**
Era, na íntegra: *"Agrupe os IDs das notícias que falam sobre o MESMO FATO ou
EVENTO. Retorne uma lista de listas JSON."* Sem definição de "mesmo fato", sem
regras de decisão, sem exemplo, sem exigir que todo id aparecesse na resposta,
e rodando em `llama-3.1-8b-instant` — um modelo pequeno para uma tarefa de
particionamento.

**4. Quando a IA falhava, o fallback era pior que nada.**
`difflib.SequenceMatcher` com razão > 0,5 sobre o título é comparação de
caracteres. "ITM Power lands 12.5MW green hydrogen contract at Kimberly-Clark
paper mill" e "ITM green hydrogen power to be used to make Andrex toilet paper"
são o mesmo contrato e têm similaridade lexical baixíssima. Na direção oposta,
o fallback também produzia baldes gigantes: há eventos no histórico com 51
"fontes" que na verdade juntam notícias de hidrogênio sem relação alguma.

**5. O material comparado era pobre.**
Só o título cru — **incluindo o sufixo " - Nome do Veículo"**, que é justamente
a parte que difere entre duas cópias da mesma notícia — mais 60 caracteres de
um resumo que a própria IA tinha acabado de escrever com redação diferente para
cada portal.

Some-se a isso que o histórico (`links_enviados.txt`) guardava só a URL do item
principal: no dia seguinte, o mesmo fato vindo por outro portal tinha outra URL
e voltava ao boletim como novidade. Daí os 1.120 reenvios.

## O desenho novo

O agrupamento passa a rodar **uma vez, sobre o pool inteiro** — todos os
tópicos e todos os idiomas juntos. Cada notícia carrega a lista de categorias
que a trouxeram; a personalização por destinatário virou um filtro aplicado no
fim, sobre eventos já deduplicados.

### Etapa 1 — Deduplicação exata (`pipeline/normalizacao.py`)

- **URL canônica**: força `https`, remove `www.`/`m.`/`amp.`, corta `/amp`,
  barra final, fragmento e todo parâmetro de rastreio (`utm_*`, `fbclid`,
  `gclid`, `ref`, `spm`, ...), e ordena o que sobra.
- **Título limpo**: remove o sufixo " - Veículo" usando o nome do publisher
  quando ele é conhecido, e um rabicho curto após o último separador quando não é.
- Itens com a mesma URL canônica, ou mesmo título limpo e mesmo veículo, viram
  um só — fundindo as categorias de origem.

### Etapa 2 — Blocos candidatos (determinístico, sem IA)

Similaridade entre todos os pares:

```
score = 0.70 × jaccard_ponderado_por_IDF(tokens do título)
      + 0.30 × sobreposição(pistas)
      + 0.15  se compartilham um número com unidade
```

- O **IDF é calculado sobre o próprio lote do dia**: "biogás" e "hidrogênio"
  aparecem em quase tudo e valem quase nada; "Kimberly-Clark" ou "Holmaneset"
  valem muito. É isso que impede que duas notícias sejam consideradas parecidas
  só por serem do mesmo setor.
- **Pistas** são as entidades que identificam um fato: siglas não genéricas
  (`ITM`, `KBR`, `MCG`), nomes próprios, números com unidade (`12.5mw`,
  `38200m3`) e valores (`r$148,5milhoes`). Siglas genéricas do setor (`SAF`,
  `RNG`, `CO2`, `LNG`, `MW`) ficam de fora de propósito.

Tudo que passa de `AGRUP_LIMIAR_BLOCO` (padrão **0,22**, propositalmente baixo)
é unido por componentes conexas. O objetivo aqui é **revocação**, não precisão:
é melhor mandar um par duvidoso para a IA arbitrar do que perdê-lo. Blocos
grandes demais para um prompt são subdivididos elevando o limiar.

### Etapa 3 — Partição fina pela IA

Só os blocos com dois ou mais itens vão ao modelo. Rodando sobre as 40 edições
mais recentes, isso dá **~6 chamadas de agrupamento por edição** — contra as
~48 da versão anterior (uma por tópico), com resultado melhor.

O prompt novo (`llm/prompts.py`) traz:

- uma **definição operacional** de "mesmo fato";
- **regras de decisão ordenadas**, com os casos que devem agrupar mesmo sem
  palavras em comum (fornecedor × cliente, marca × empresa-mãe, idiomas
  diferentes, anúncio × repercussão) e os que não devem (dois contratos
  distintos das mesmas empresas, fato × projeção de mercado, só o tema em comum);
- a distinção explícita entre **evidência forte** (número específico, nome
  próprio raro, local) e **evidência nula** (vocabulário genérico do setor);
- um **critério de desempate** — agrupar só com ao menos uma evidência
  específica compartilhada;
- um **exemplo resolvido com explicação**, tirado de um caso real do histórico
  (as quatro manchetes da ITM Power, três delas o mesmo contrato e uma outro);
- um **contrato de saída** explícito: todo id de 0 a N-1 aparece exatamente uma vez.

A resposta é normalizada em `_normalizar_grupos`: ids inválidos são ignorados,
ids repetidos ficam na primeira ocorrência e **ids esquecidos viram grupos de um
elemento**. Nenhuma notícia some por erro de formato do modelo.

Se a chamada falhar, o bloco cai no recorte determinístico com o limiar alto
(`AGRUP_LIMIAR_CERTEZA`, padrão 0,62) — que agrupa pouco e erra pouco, em vez do
`difflib` que agrupava demais e errado.

### Etapa 4 — Resumo depois do agrupamento

O resumo passa a ser gerado **uma vez por evento**, não uma vez por notícia.
Cinco portais sobre o mesmo fato custavam antes cinco downloads e cinco
chamadas de IA. Se a página do representante não puder ser lida, tenta-se o
próximo portal do mesmo evento — e o evento só é descartado se nenhum
funcionar, o que elimina os resumos vazios e os "ERRO" que iam para o e-mail.

### Etapa 5 — Memória de eventos (`pipeline/memoria.py`)

`historico_eventos.json` guarda, por evento enviado: **todas** as URLs
canônicas, os tokens, as pistas e a data. Um evento novo é comparado com os
dos últimos `HISTORICO_JANELA_DIAS` (padrão 7) pelo mesmo critério de
similaridade. `HISTORICO_MODO=suprimir` não reenvia; `marcar` reenvia com a
etiqueta "já publicado".

## Ajuste fino

| Variável | Padrão | Efeito de aumentar |
|---|---|---|
| `AGRUP_LIMIAR_BLOCO` | 0.22 | menos pares vão à IA: mais barato, agrupa menos |
| `AGRUP_LIMIAR_CERTEZA` | 0.62 | fallback mais conservador (só quando a IA falha) |
| `AGRUP_MAX_ITENS_POR_BLOCO` | 25 | prompts maiores; acima de ~30 a qualidade cai |
| `HISTORICO_LIMIAR` | 0.50 | menos supressão por repetição entre dias |

Para trabalhar no algoritmo sem gastar API: `python main.py --simular
--sem-ia-no-agrupamento` roda o pipeline inteiro sem enviar e-mail e sem tocar
no histórico, e grava uma prévia em `previa.html`.

## Resultado medido

Rodando **apenas a camada determinística** (sem IA) sobre os itens que
realmente foram enviados nas 40 edições mais recentes, ela já funde **104
eventos** que a versão anterior tinha mandado separados — inclusive pares em
idiomas diferentes ("Setor de biodiesel vai pressionar Lula..." / "The biodiesel
sector will pressure Lula...") e reescritas completas ("ANDRITZ : RAG Austria
and ANDRITZ celebrate groundbreaking..." / "Andritz to build 12.5-MW green H2
plant for RAG Austria").

Esse é o **piso**. A camada de IA opera sobre os 547 pares candidatos que a
camada determinística não decide sozinha, o que dá **~6 chamadas de agrupamento
por edição** — contra as ~48 da versão anterior (uma por tópico), com resultado
melhor e mais barato.

Alguns pares de controle, com o IDF em condição realista:

| Par | Score | Decisão |
|---|---|---|
| "BNDES aprova recursos de R$ 148,5 milhões para usina de biometano" / "BNDES libera R$ 148,5 milhões para nova usina de biometano no Paraná" | 0,84 | agrupa mesmo sem IA |
| "Setor de biodiesel vai pressionar Lula..." / "The biodiesel sector will pressure Lula..." | 0,49 | candidato, IA confirma |
| "Songyuan green hydrogen-ammonia-methanol project begins operations" / "World's Largest Integrated Green Hydrogen, Ammonia, and Methanol Project Commences Operation in Songyuan" | 0,35 | candidato, IA confirma |
| "ITM Power lands 12.5MW... Kimberly-Clark paper mill" / "ITM green hydrogen power to be used to make Andrex toilet paper" | 0,34 | candidato, IA confirma |
| "Biogas Market Size to Worth USD 265.60 Billion by 2035" / "Green Hydrogen Market Set for Explosive Growth at 54.69% CAGR" | 0,05 | separado, nem vai à IA |

A última linha é o controle negativo que importa: duas manchetes cheias de
palavras em comum ("Market", "Growth", "Billion") mas sem nenhuma entidade
compartilhada. É o IDF calculado sobre o lote do dia que as mantém separadas.
