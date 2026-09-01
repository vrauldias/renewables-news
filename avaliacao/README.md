# Bancada de avaliação da triagem

Serve para ajustar os prompts de `llm/prompts.py` medindo o efeito, em vez de
julgar pela prévia no olho.

| arquivo | o que é |
|---|---|
| `amostra_triagem.json` | 87 manchetes reais, estratificadas pelos 16 tópicos |
| `gabarito_triagem.json` | rótulo humano de cada uma (1 = deveria entrar no boletim) |
| `avaliar_triagem.py` | roda a triagem sobre a amostra e compara com o gabarito |
| `montar_amostra.py` | regenera a amostra a partir de um `cache_bruto.json` |
| `resultados/` | uma rodada por arquivo, para comparar versões |

## Como usar

```bash
python avaliacao/avaliar_triagem.py antes    # linha de base
# edite llm/prompts.py — uma regra por vez
python avaliacao/avaliar_triagem.py depois   # mesma amostra, um único fator mudado
```

O script imprime precisão (quanto do que entrou era bom), recall (quanto do que
era bom entrou), F1 e a lista nominal dos erros — que é a parte útil: é ela que
diz qual regra escrever a seguir.

## Duas ressalvas de método

O modelo não é determinístico nem com `temperature=0`. Medida em duas rodadas
idênticas, a variação foi de cerca de um item — então **diferença de um item só
não é melhoria**; confirme repetindo a rodada.

Se um lote falhar (rate limit, por exemplo), `pipeline/triagem.py` aprova o lote
inteiro por segurança, e a rodada fica sem valor de comparação. O script detecta
isso e avisa no cabeçalho.

## Critério do gabarito

Entra no boletim o fato **novo, concreto e datável** que toque uma das 16
categorias de interesse. Ficam de fora projeção de mercado, indicador
macroeconômico, governança corporativa, matéria explicativa e evento. Petróleo e
gás entram quando ligados a combustível marítimo/GNL de bunker; produção
upstream sem essa ligação fica de fora. Os casos discutíveis estão anotados um a
um em `_discutiveis`, dentro do gabarito — é ali que se revisa o escopo editorial
se ele mudar.

## Histórico das versões do prompt de triagem

Medido com `openai/gpt-oss-20b` (Groq), amostra de 87 manchetes:

| versão | precisão | recall | F1 | o que mudou |
|---|---|---|---|---|
| v0 | 66% | 88% | 0,75 | prompt original |
| v1 | 91% | 83% | 0,87 | passo de pertinência, siglas homônimas, listas ampliadas, exemplo resolvido |
| v2 | 90% | 75% | 0,82 | **regressão**: enumerar as cadeias cobertas virou checklist exaustiva e derrubou o que não estava na lista |
| v3 | 95% | 88% | 0,91 | v1 + exclusão de assuntos vizinhos (petróleo upstream, tarifa elétrica, crédito rural) |
| v4 | 100% | 92% | 0,96 | v3 + teste do "cubra a sigla" + exemplos de entrada em mercado novo |

A v4 no `gemini-3.5-flash-lite` deu precisão 100% e recall 71% (F1 0,83): o
Gemini é mais conservador que o Groq com o mesmo prompt.
