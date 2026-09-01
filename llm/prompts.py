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

O tema acima é apenas o termo que trouxe estas manchetes do buscador — ele NÃO
garante que a manchete seja do setor. Confira sempre o assunto real.

## Passo 1 — Pertinência
Descarte de imediato a manchete que não trate da cadeia de energia, bioenergia,
combustíveis, celulose e papel, açúcar e álcool ou da indústria correlata — mesmo
que ela repita uma palavra ou sigla do tema. Duas armadilhas frequentes:
- sigla ou termo homônimo: "SAF" de clube de futebol ou de entidade civil, "RNG"
  de jogo, "pulp" de odontologia ou de arte, "gás" em nota policial;
- assunto vizinho, mas fora do escopo: exploração e produção de petróleo e gás
  convencional, tarifa e mercado varejista de energia elétrica, mineração,
  agronegócio e crédito rural sem ligação com energia ou combustível.

Teste rápido: cubra a sigla ou a palavra do tema e releia a manchete. Se o que
sobra não fala de energia, combustível ou da indústria que os produz, REJEITE.

## Passo 2 — Aprove (relevante) quando a manchete indicar um FATO CONCRETO E NOVO:
- novo projeto, planta, unidade, terminal ou expansão de capacidade;
- contrato, offtake, joint venture, MoU, fusão, aquisição ou investimento com valor;
- decisão regulatória, leilão, chamada pública, norma, licença ou tributo, e
  também a abertura de consulta pública ou tomada de subsídios por um governo ou
  agência ("abre consulta", "pede contribuições", "seeks input", "call for
  evidence");
- fiscalização, investigação, sanção, embargo, acidente ou paralisação em
  instalação industrial do setor;
- resultado operacional relevante, entrada em operação de uma unidade, ou entrada
  de uma empresa em um mercado novo do setor (um banco que estreia em créditos de
  remoção de carbono, uma empresa que passa a operar mais uma planta);
- inovação tecnológica com aplicação industrial anunciada por empresa identificada.

## Passo 3 — Rejeite (irrelevante):
- projeção de mercado, "mercado deve crescer X% até 20XX", relatório pago de
  consultoria, estudo acadêmico de potencial, ranking genérico, listas de
  "principais players";
- indicador macroeconômico, preço de bomba, cotação, safra, inadimplência, linha
  de crédito genérica, recomendação de compra ou análise de ação;
- governança corporativa sem efeito operacional: nomeação de conselheiro ou
  diretor, mudança de estatuto, convocação de assembleia;
- constatação estatística sem anúncio datável ("o país X dobrou sua frota");
- agenda de evento, convite, webinar, chamada para inscrição, prêmio;
- conteúdo institucional, publieditorial, matéria de opinião ou explicativa
  ("o que é", "como funciona"), sem fato novo;
- vaga de emprego, concurso, edital de contratação;
- esporte, entretenimento, política partidária, polícia, obituário, celebridades,
  loteria.

## Regra de corte
Na dúvida entre aprovar e rejeitar, REJEITE. Um boletim curto e limpo vale mais
que um boletim longo e diluído.

## Exemplo resolvido
[0] Raízen fecha contrato de 10 anos para fornecer 200 mil m³/ano de biometano à Vibra
[1] Cruzeiro conclui a venda de 90% da SAF para investidor norte-americano
[2] Preço médio do etanol nos postos cai 1,2% na semana, aponta levantamento
[3] Ibama embarga terminal de combustíveis em Suape após vazamento
[4] Mercado global de amônia verde deve crescer 38% ao ano até 2032

Saída: {{"relevantes": [0, 3]}}

Raciocínio: 0 é contrato novo, com partes identificadas e volume; 3 é ação de
fiscalização sobre instalação do setor. 1 usa "SAF" como sociedade anônima do
futebol — não é do setor. 2 é variação de preço. 4 é projeção de mercado.

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
