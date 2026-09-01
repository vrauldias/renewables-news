"""Agrupamento de notícias que cobrem o mesmo fato.

Três etapas, nesta ordem:

1. DEDUPLICAÇÃO EXATA — mesma URL canônica ou mesmo título+veículo viram um
   item só. Não custa nada e resolve a maior parte das repetições grosseiras.

2. BLOCOS CANDIDATOS (determinístico, sem IA) — calcula a similaridade entre
   todos os pares e une, por componentes conexas, tudo que passa de um limiar
   propositalmente BAIXO. O objetivo aqui é revocação: é melhor mandar um par
   duvidoso para a IA decidir do que perdê-lo. A similaridade pesa tokens do
   título por IDF (palavra rara vale mais que palavra comum do setor) e dá
   peso extra às "pistas" — siglas, nomes próprios e números com unidade.

3. PARTIÇÃO POR IA — cada bloco com dois ou mais itens é submetido ao modelo,
   que decide o recorte fino. A resposta é validada: todo id precisa aparecer
   exatamente uma vez. Se a IA falhar, o bloco cai no recorte determinístico
   com o limiar alto (AGRUP_LIMIAR_CERTEZA).

O ponto crítico é que este módulo recebe o pool INTEIRO da execução — todos os
tópicos e todos os idiomas de uma vez. Agrupar dentro de cada tópico, como a
versão anterior fazia, torna impossível detectar que a mesma notícia veio pelas
buscas de "biogás" e de "biometano".
"""
import json
import logging
import math
import re
from collections import defaultdict

import config
from llm import prompts
from llm.provedores import obter_cliente
from pipeline import normalizacao

log = logging.getLogger(__name__)


# =============================================================================
# 1. Deduplicação exata
# =============================================================================

def deduplicar(noticias):
    """Colapsa itens que são literalmente a mesma página."""
    por_chave = {}
    for noticia in noticias:
        normalizacao.assinatura(noticia)
        chave = noticia["url_canonica"] or (
            normalizacao.remover_acentos(noticia["titulo_limpo"]).lower(),
            normalizacao.nome_publisher(noticia),
        )
        anterior = por_chave.get(chave)
        if anterior is None:
            por_chave[chave] = noticia
            continue
        # Mantém o item com o título mais informativo e funde os tópicos.
        vencedor, perdedor = (
            (noticia, anterior)
            if len(noticia["titulo_limpo"]) > len(anterior["titulo_limpo"])
            else (anterior, noticia)
        )
        vencedor["topicos"] = sorted(set(vencedor.get("topicos", [])) | set(perdedor.get("topicos", [])))
        por_chave[chave] = vencedor

    removidos = len(noticias) - len(por_chave)
    if removidos:
        log.info("  Deduplicação exata: %s itens repetidos removidos.", removidos)
    return list(por_chave.values())


# =============================================================================
# 2. Similaridade e blocos candidatos
# =============================================================================

def _calcular_idf(noticias):
    """IDF sobre o próprio lote: 'biogás' aparece em tudo e vale pouco."""
    total = len(noticias)
    frequencia = defaultdict(int)
    for noticia in noticias:
        for token in noticia["tokens"]:
            frequencia[token] += 1
    return {
        token: math.log((total + 1) / (ocorrencias + 0.5))
        for token, ocorrencias in frequencia.items()
    }


def similaridade(a, b, idf):
    """0.0 a ~1.15. Jaccard ponderado por IDF + sobreposição de pistas."""
    tokens_a, tokens_b = a["tokens"], b["tokens"]
    if not tokens_a or not tokens_b:
        return 0.0

    comuns = tokens_a & tokens_b
    if not comuns:
        return 0.0

    peso_comum = sum(idf.get(t, 1.0) for t in comuns)
    peso_uniao = sum(idf.get(t, 1.0) for t in tokens_a | tokens_b)
    score_tokens = peso_comum / peso_uniao if peso_uniao else 0.0

    pistas_a, pistas_b = a["pistas"], b["pistas"]
    score_pistas = 0.0
    if pistas_a and pistas_b:
        score_pistas = len(pistas_a & pistas_b) / min(len(pistas_a), len(pistas_b))

    score = 0.70 * score_tokens + 0.30 * score_pistas

    # Um número com unidade em comum (12.5mw, r$148,5milhoes) é sinal forte.
    numericas = {p for p in (pistas_a & pistas_b) if any(c.isdigit() for c in p)}
    if numericas:
        score += 0.15

    return score


def _blocos_por_limiar(indices, matriz, limiar):
    """Componentes conexas do grafo de similaridade (union-find)."""
    pai = {i: i for i in indices}

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for (a, b), score in matriz.items():
        if a in pai and b in pai and score >= limiar:
            ra, rb = raiz(a), raiz(b)
            if ra != rb:
                pai[ra] = rb

    grupos = defaultdict(list)
    for i in indices:
        grupos[raiz(i)].append(i)
    return list(grupos.values())


def montar_blocos(noticias):
    """Blocos candidatos, cada um pequeno o bastante para caber num prompt."""
    idf = _calcular_idf(noticias)
    matriz = {}
    for a in range(len(noticias)):
        for b in range(a + 1, len(noticias)):
            score = similaridade(noticias[a], noticias[b], idf)
            if score >= config.AGRUP_LIMIAR_BLOCO:
                matriz[(a, b)] = score

    blocos = _blocos_por_limiar(list(range(len(noticias))), matriz, config.AGRUP_LIMIAR_BLOCO)

    # Bloco grande demais para um prompt: sobe o limiar até quebrá-lo.
    finais = []
    for bloco in blocos:
        finais.extend(_subdividir(bloco, matriz, config.AGRUP_LIMIAR_BLOCO))
    return finais, matriz


def _subdividir(bloco, matriz, limiar):
    if len(bloco) <= config.AGRUP_MAX_ITENS_POR_BLOCO:
        return [bloco]
    novo_limiar = limiar + 0.08
    if novo_limiar >= 1.0:
        # Não dá para separar mais: corta em pedaços do tamanho máximo.
        tamanho = config.AGRUP_MAX_ITENS_POR_BLOCO
        return [bloco[i:i + tamanho] for i in range(0, len(bloco), tamanho)]
    partes = []
    for parte in _blocos_por_limiar(bloco, matriz, novo_limiar):
        partes.extend(_subdividir(parte, matriz, novo_limiar))
    return partes


# =============================================================================
# 3. Partição fina por IA
# =============================================================================

def _formatar_bloco(noticias, bloco):
    linhas = []
    for id_local, indice in enumerate(bloco):
        noticia = noticias[indice]
        veiculo = normalizacao.nome_publisher(noticia)
        idioma = noticia.get("idioma", "?")
        pistas = sorted(noticia["pistas"])[:8]
        linhas.append(f"[{id_local}] ({veiculo} | {idioma}) {noticia['titulo_limpo']}")
        if pistas:
            linhas.append(f"    pistas: {', '.join(pistas)}")
    return "\n".join(linhas)


def _extrair_json(texto):
    """Aceita a resposta com blocos de código, texto ao redor ou lista solta."""
    if not texto:
        raise ValueError("resposta vazia")
    limpo = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        pass
    for padrao in (r"\{.*\}", r"\[\s*\[.*\]\s*\]"):
        achado = re.search(padrao, limpo, re.DOTALL)
        if achado:
            try:
                return json.loads(achado.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"não foi possível ler JSON da resposta: {texto[:200]!r}")


def _normalizar_grupos(bruto, tamanho):
    """Garante uma partição válida: todo id exatamente uma vez."""
    if isinstance(bruto, dict):
        bruto = bruto.get("grupos") or bruto.get("groups") or []
    if not isinstance(bruto, list):
        raise ValueError("formato inesperado")

    vistos = set()
    grupos = []
    for grupo in bruto:
        if isinstance(grupo, int):
            grupo = [grupo]
        if not isinstance(grupo, list):
            continue
        limpo = []
        for item in grupo:
            if isinstance(item, bool) or not isinstance(item, int):
                continue
            if 0 <= item < tamanho and item not in vistos:
                vistos.add(item)
                limpo.append(item)
        if limpo:
            grupos.append(limpo)

    # Ids que a IA esqueceu viram grupos de um elemento — nunca somem.
    for i in range(tamanho):
        if i not in vistos:
            grupos.append([i])
    return grupos


def _particionar_com_ia(noticias, bloco):
    cliente = obter_cliente()
    lista = _formatar_bloco(noticias, bloco)
    usuario = prompts.USUARIO_AGRUPAMENTO.format(lista=lista, ultimo_id=len(bloco) - 1)

    resposta = cliente.gerar(
        sistema=prompts.SISTEMA_AGRUPAMENTO,
        usuario=usuario,
        # folga extra: modelos de raciocínio (ex.: gpt-oss na Groq) gastam
        # parte do orçamento "pensando" antes do JSON final.
        max_tokens=1800,
        tarefa="agrupamento",
        json_esperado=True,
    )
    grupos_locais = _normalizar_grupos(_extrair_json(resposta), len(bloco))
    return [[bloco[i] for i in grupo] for grupo in grupos_locais]


def _particionar_deterministico(bloco, matriz):
    """Rede de segurança: só une o que passa do limiar de certeza."""
    return _blocos_por_limiar(bloco, matriz, config.AGRUP_LIMIAR_CERTEZA)


# =============================================================================
# Montagem dos clusters
# =============================================================================

def _pontuar_representante(noticia):
    """O melhor título é o mais informativo, não o mais comprido."""
    return (
        2 * len(noticia["pistas"])
        + len(noticia["tokens"])
        + (1 if noticia.get("resumo") else 0)
    )


def _montar_cluster(noticias, indices):
    itens = sorted((noticias[i] for i in indices), key=_pontuar_representante, reverse=True)
    principal, outros = itens[0], itens[1:]
    topicos = set()
    for item in itens:
        topicos.update(item.get("topicos", []))
    return {
        "principal": principal,
        "outros_sites": outros,
        "topicos": sorted(topicos),
        "n_fontes": len(itens),
    }


def agrupar(noticias):
    """Ponto de entrada: recebe o pool inteiro e devolve a lista de clusters."""
    if not noticias:
        return []

    noticias = deduplicar(noticias)
    if len(noticias) == 1:
        return [_montar_cluster(noticias, [0])]

    blocos, matriz = montar_blocos(noticias)
    candidatos = [b for b in blocos if len(b) > 1]
    log.info(
        "  %s itens -> %s blocos candidatos (%s deles com mais de um item).",
        len(noticias), len(blocos), len(candidatos),
    )

    clusters = []
    falhas_ia = 0
    for bloco in blocos:
        if len(bloco) == 1:
            clusters.append(_montar_cluster(noticias, bloco))
            continue

        if config.AGRUP_USAR_IA:
            try:
                particoes = _particionar_com_ia(noticias, bloco)
            except Exception as erro:  # noqa: BLE001
                falhas_ia += 1
                log.warning("  Agrupamento por IA falhou num bloco (%s). Usando o determinístico.", erro)
                particoes = _particionar_deterministico(bloco, matriz)
        else:
            particoes = _particionar_deterministico(bloco, matriz)

        for particao in particoes:
            clusters.append(_montar_cluster(noticias, particao))

    agrupados = sum(1 for c in clusters if c["n_fontes"] > 1)
    log.info(
        "  Resultado: %s eventos (%s com mais de uma fonte). Falhas de IA: %s.",
        len(clusters), agrupados, falhas_ia,
    )
    return clusters
