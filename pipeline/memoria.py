"""Memória dos eventos já enviados.

A versão anterior guardava apenas a URL da notícia principal em um arquivo de
texto. Quando o mesmo fato reaparecia no dia seguinte por outro portal — o que
acontece o tempo todo — a URL era outra e o evento voltava ao boletim como se
fosse novo. Nos e-mails analisados isso responde por mais de mil repetições.

Aqui a memória guarda, por evento: todas as URLs canônicas, a assinatura de
tokens e pistas e a data. Um evento novo é comparado com os eventos da janela
configurada (HISTORICO_JANELA_DIAS) pelo mesmo critério de similaridade usado
no agrupamento.
"""
import json
import logging
import os
from datetime import datetime, timedelta

import config
from pipeline.agrupamento import similaridade

log = logging.getLogger(__name__)


def carregar(caminho=None):
    caminho = caminho or config.ARQUIVO_HISTORICO
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (json.JSONDecodeError, OSError) as erro:
        log.warning("Histórico ilegível (%s). Recomeçando vazio.", erro)
        return []

    limite = datetime.now() - timedelta(days=config.HISTORICO_JANELA_DIAS)
    recentes = []
    for evento in dados:
        try:
            if datetime.fromisoformat(evento["data"]) >= limite:
                recentes.append(evento)
        except (KeyError, ValueError):
            continue
    return recentes


def salvar(historico, clusters, caminho=None):
    caminho = caminho or config.ARQUIVO_HISTORICO
    agora = datetime.now().isoformat(timespec="seconds")
    novos = []
    for cluster in clusters:
        itens = [cluster["principal"], *cluster["outros_sites"]]
        novos.append({
            "data": agora,
            "titulo": cluster["principal"]["titulo_limpo"],
            "urls": sorted({n["url_canonica"] for n in itens if n.get("url_canonica")}),
            "tokens": sorted(set().union(*(n["tokens"] for n in itens))),
            "pistas": sorted(set().union(*(n["pistas"] for n in itens))),
        })
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(historico + novos, arquivo, ensure_ascii=False, indent=1)


def _como_noticia(evento):
    return {"tokens": set(evento.get("tokens", [])), "pistas": set(evento.get("pistas", []))}


def filtrar_novidades(clusters, historico):
    """Separa os eventos inéditos dos que já foram ao ar na janela recente."""
    if not historico:
        return clusters, []

    urls_conhecidas = {url for evento in historico for url in evento.get("urls", [])}
    passados = [_como_noticia(evento) for evento in historico]
    # IDF neutro: a janela é pequena demais para estimar frequência confiável.
    idf = {}

    novos, repetidos = [], []
    for cluster in clusters:
        itens = [cluster["principal"], *cluster["outros_sites"]]
        if any(n.get("url_canonica") in urls_conhecidas for n in itens):
            repetidos.append(cluster)
            continue

        assinatura = {
            "tokens": set().union(*(n["tokens"] for n in itens)),
            "pistas": set().union(*(n["pistas"] for n in itens)),
        }
        if any(similaridade(assinatura, antigo, idf) >= config.HISTORICO_LIMIAR
               for antigo in passados):
            repetidos.append(cluster)
        else:
            novos.append(cluster)

    if repetidos:
        log.info(
            "  Memória: %s eventos já publicados nos últimos %s dias.",
            len(repetidos), config.HISTORICO_JANELA_DIAS,
        )
    if config.HISTORICO_MODO == "marcar":
        for cluster in repetidos:
            cluster["repetido"] = True
        return novos + repetidos, []
    return novos, repetidos
