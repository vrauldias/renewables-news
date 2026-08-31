"""Todos os prompts do projeto, em um único lugar.

Ficam separados do código que os usa para que dê para ajustar o texto sem
mexer na lógica — e para que a diferença entre duas versões do boletim seja
legível num diff.
"""

# =============================================================================
# TRIAGEM DE RELEVÂNCIA
# =============================================================================

SISTEMA_TRIAGEM = (
    "Você é o editor de pauta de um boletim diário de inteligência de mercado "
    "para executivos do setor de energia, bioenergia e combustíveis renováveis. "
    "Sua função é separar o que é FATO NOVO E ACIONÁVEL do que é ruído. "
    "Você responde sempre e apenas com JSON válido."
)

USUARIO_TRIAGEM = """Tema da busca: {tema}

Avalie cada manchete abaixo.

## Aprove (relevante) quando a manchete indicar um FATO CONCRETO E NOVO:
- novo projeto, planta, unidade, terminal ou expansão de capacidade;
- contrato, offtake, joint venture, MoU, fusão, aquisição ou investimento com valor;
- decisão regulatória, leilão, chamada pública, consulta, norma, licença ou tributo;
- resultado operacional/financeiro relevante, entrada em operação, paralisação;
- inovação tecnológica com aplicação industrial anunciada por empresa identificada.

## Rejeite (irrelevante):
- projeção de mercado, "mercado deve crescer X% até 20XX", relatório pago de consultoria,
  ranking genérico, listas de "principais players";
- agenda de evento, convite, webinar, chamada para inscrição, prêmio;
- conteúdo institucional, publieditorial, matéria de opinião sem fato novo;
- vaga de emprego, concurso, edital de contratação;
- esporte, entretenimento, política partidária, polícia, celebridades, loteria;
- assuntos alheios ao setor de energia/bioenergia/combustíveis/indústria correlata.

## Regra de corte
Na dúvida entre aprovar e rejeitar, REJEITE. Um boletim curto e limpo vale mais
que um boletim longo e diluído.

## Manchetes
{lista}

## Saída
Responda APENAS com este JSON, sem texto antes ou depois e sem blocos de código:
{{"relevantes": [ids aprovados]}}
Se nenhuma for relevante: {{"relevantes": []}}
"""


# =============================================================================
# AGRUPAMENTO (deduplicação do mesmo fato entre portais)
# =============================================================================

SISTEMA_AGRUPAMENTO = (
    "Você é o editor de mesa de um boletim de notícias do setor de energia e "
    "combustíveis renováveis. Sua única tarefa é decidir quais manchetes cobrem "
    "O MESMO FATO JORNALÍSTICO e devolver o agrupamento. "
    "Você responde sempre e apenas com JSON válido."
)

USUARIO_AGRUPAMENTO = """## O que é "o mesmo fato"
Duas notícias cobrem o mesmo fato quando relatam o mesmo acontecimento concreto
e datável — o mesmo anúncio, contrato, investimento, licença, decisão, resultado,
inauguração ou publicação — protagonizado pelas mesmas organizações.

## Regras de decisão, nesta ordem

1. AGRUPE quando as manchetes compartilham protagonista E acontecimento, MESMO QUE:
   - usem palavras completamente diferentes para descrever a mesma coisa;
   - uma cite o fornecedor e a outra o cliente; uma cite a marca e a outra a
     empresa-mãe, a subsidiária ou o grupo controlador;
   - uma traga números (capacidade, valor, prazo) e a outra não;
   - estejam em idiomas diferentes;
   - uma seja o anúncio e a outra a repercussão, a análise ou o desdobramento
     imediato do mesmo anúncio.

2. NÃO AGRUPE quando:
   - são acontecimentos distintos das mesmas empresas (dois contratos diferentes,
     duas plantas diferentes, duas rodadas de investimento diferentes);
   - uma é fato e a outra é matéria de contexto: projeção de mercado, ranking,
     relatório de consultoria, agenda de evento, perfil de empresa;
   - compartilham apenas o TEMA (por exemplo "hidrogênio verde", "biometano")
     sem compartilhar o acontecimento.

3. O que conta como evidência forte de que é o mesmo fato: números específicos
   (12,5 MW; R$ 200 milhões; 15 mil t/ano), nomes próprios pouco comuns, locais
   específicos, datas. O que NÃO conta: palavras genéricas do setor (biogás,
   hidrogênio, energia, projeto, planta, sustentável, renovável).

4. Critério de desempate: agrupe apenas se houver PELO MENOS UMA evidência
   específica compartilhada (regra 3). Sem evidência específica, separe.

## Exemplo resolvido
Entrada:
[0] (Bioenergy Insight | en) ITM Power lands 12.5MW green hydrogen contract at Kimberly-Clark paper mill
    pistas: ITM, Kimberly-Clark, 12.5MW
[1] (Hydrogen Insight | en) ITM wins firm order to supply 15MW of electrolysers to 12.5MW UK green hydrogen project
    pistas: ITM, 15MW, 12.5MW, UK
[2] (Proactive Investors | en) ITM green hydrogen power to be used to make Andrex toilet paper
    pistas: ITM, Andrex
[3] (Investing.com | en) ITM Power signs contract with Octopus Energy for green hydrogen system
    pistas: ITM, Octopus Energy
[4] (openPR.com | en) Green Hydrogen Market Set for Explosive Growth at 54.69% CAGR
    pistas: 54.69%

Saída:
{{"grupos": [[0, 1, 2], [3], [4]]}}

Raciocínio: 0, 1 e 2 são o mesmo contrato — mesma empresa (ITM), mesma
capacidade (12,5 MW) e mesma fábrica (a planta da Kimberly-Clark que produz a
marca Andrex), contado por três ângulos diferentes. 3 é outro contrato, com
outro cliente. 4 é projeção de mercado, não é fato — fica sozinho.

## Manchetes a agrupar
{lista}

## Saída
Responda APENAS com este JSON, sem texto antes ou depois e sem blocos de código:
{{"grupos": [[ids], [ids], ...]}}

Cada id de 0 a {ultimo_id} deve aparecer EXATAMENTE UMA VEZ no conjunto de
grupos. Manchete sem par forma um grupo de um único elemento.
"""


# =============================================================================
# RESUMO
# =============================================================================

SISTEMA_RESUMO = (
    "Você escreve resumos de uma frase para um boletim executivo de energia. "
    "Escreve como um analista: direto, específico e sem adjetivos de marketing."
)

USUARIO_RESUMO = """Resuma a notícia abaixo em {idioma}, em UMA frase de no máximo 30 palavras.

Regras:
- Comece direto pelo fato. Nada de "A notícia informa que", "O artigo aborda",
  "Segundo o texto" ou qualquer fórmula introdutória.
- Preserve os dados duros que estiverem no texto: quem, quanto, onde, quando,
  capacidade, valor do investimento, prazo.
- Não invente número, nome ou data que não esteja no texto.
- Não use aspas na resposta e não repita o título literalmente.

Título: {titulo}

Texto: {texto}
"""
