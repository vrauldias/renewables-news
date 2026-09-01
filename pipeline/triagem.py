"""Triagem de relevância: descarta o que não é fato novo do setor.

Roda ANTES do agrupamento, sobre os títulos, e por lotes. Continua sendo
organizada por tópico porque o tópico é contexto útil para o modelo decidir —
mas o resultado volta para um pool único, que é o que o agrupamento consome.
"""
import logging
import re
from collections import defaultdict

import config
from llm import prompts
from llm.provedores import obter_cliente
from pipeline.agrupamento import _extrair_json

log = logging.getLogger(__name__)

TAMANHO_LOTE = 25

# Filtro barato antes de gastar chamada de IA.
PALAVRAS_NEGATIVAS = [
    "futebol", "jogador", "neymar", "messi", "flamengo", "corinthians", "palmeiras",
    "bbb", "reality show", "novela", "ator", "atriz", "celebridade",
    "horóscopo", "signo", "zodíaco", "loteria", "mega-sena", "quina",
    "assalto", "homicídio", "tiroteio", "traficante", "feminicídio",
    "netflix", "spoiler", "resumo da novela", "bilheteria",
    "concurso público", "vaga de emprego", "gabarito", "edital de concurso",
]


def _negativa(titulo):
    baixo = (titulo or "").lower()
    return any(palavra in baixo for palavra in PALAVRAS_NEGATIVAS)


def _ids_relevantes(resposta, tamanho):
    try:
        dados = _extrair_json(resposta)
    except ValueError:
        # Modelo devolveu "0, 2, 5" em vez de JSON — ainda dá para aproveitar.
        return [int(n) for n in re.findall(r"\b\d+\b", resposta or "") if int(n) < tamanho]
    if isinstance(dados, dict):
        dados = dados.get("relevantes") or dados.get("relevant") or []
    if not isinstance(dados, list):
        return []
    return [n for n in dados if isinstance(n, int) and not isinstance(n, bool) and 0 <= n < tamanho]


def triar(pool):
    """Devolve só as notícias aprovadas, preservando o campo `topicos`."""
    if not pool:
        return []

    descartadas_regra = [n for n in pool if _negativa(n["titulo"])]
    candidatas = [n for n in pool if not _negativa(n["titulo"])]
    if descartadas_regra:
        log.info("  Descartadas por palavra-chave negativa: %s", len(descartadas_regra))

    por_topico = defaultdict(list)
    for noticia in candidatas:
        chave = (noticia["topicos"][0] if noticia["topicos"] else noticia.get("termo_busca", "geral"))
        por_topico[chave].append(noticia)

    cliente = obter_cliente()
    aprovadas = []
    for tema, itens in por_topico.items():
        for inicio in range(0, len(itens), TAMANHO_LOTE):
            lote = itens[inicio:inicio + TAMANHO_LOTE]
            lista = "\n".join(
                f"ID {i}: {n['titulo']}".replace("\n", " ") for i, n in enumerate(lote)
            )
            try:
                resposta = cliente.gerar(
                    sistema=prompts.SISTEMA_TRIAGEM,
                    usuario=prompts.USUARIO_TRIAGEM.format(tema=tema, lista=lista),
                    # folga além dos ~30-50 tokens de resposta: modelos de
                    # raciocínio (ex.: gpt-oss na Groq) gastam parte do
                    # orçamento "pensando" antes do JSON final.
                    max_tokens=900,
                    tarefa="triagem",
                    json_esperado=True,
                )
            except Exception as erro:  # noqa: BLE001
                log.error("  Triagem falhou no lote de '%s': %s. Lote mantido.", tema, erro)
                aprovadas.extend(lote)
                continue
            for indice in _ids_relevantes(resposta, len(lote)):
                aprovadas.append(lote[indice])

    # Uma mesma notícia pode ter sido aprovada por mais de um tópico.
    unicas = {}
    for noticia in aprovadas:
        chave = noticia["link"]
        if chave in unicas:
            unicas[chave]["topicos"] = sorted(
                set(unicas[chave]["topicos"]) | set(noticia["topicos"])
            )
        else:
            unicas[chave] = noticia

    log.info("  Triagem: %s candidatas -> %s aprovadas.", len(candidatas), len(unicas))
    return list(unicas.values())
