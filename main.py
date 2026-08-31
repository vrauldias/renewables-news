"""Orquestrador do boletim.

    coleta -> triagem -> AGRUPAMENTO GLOBAL -> resumo -> memória -> envio

A diferença estrutural em relação à versão anterior está na terceira etapa: o
agrupamento acontece UMA VEZ sobre o pool inteiro (todos os tópicos, todos os
idiomas), e não uma vez por tópico. Cada evento agrupado carrega a lista de
categorias que o trouxeram; a personalização por destinatário passa a ser um
filtro aplicado no fim, sobre eventos já deduplicados.
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import config
from entrega import email_html, graph
from pipeline import agrupamento, coleta, memoria, resumo, triagem
from preferencias import fontes


def configurar_log():
    os.makedirs(config.PASTA_LOGS, exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    caminho = os.path.join(config.PASTA_LOGS, f"boletim_{marca}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(caminho, "w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # O console do Windows quebra em caracteres fora do cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def salvar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=1, default=_serializavel)


def _serializavel(objeto):
    return sorted(objeto) if isinstance(objeto, set) else str(objeto)


def eventos_do_perfil(clusters, perfil):
    """Eventos que tocam ao menos uma categoria escolhida pelo destinatário."""
    interesses = set(perfil.get("keywords_for_display", []))
    if not interesses:
        return list(clusters)
    return [c for c in clusters if interesses & set(c.get("topicos", []))]


def main():
    analisador = argparse.ArgumentParser(description="Boletim automático de notícias.")
    analisador.add_argument("--simular", action="store_true",
                            help="roda tudo mas não envia e-mail nem grava o histórico")
    analisador.add_argument("--sem-ia-no-agrupamento", action="store_true",
                            help="usa apenas o agrupamento determinístico")
    argumentos = analisador.parse_args()

    configurar_log()
    if argumentos.sem_ia_no_agrupamento:
        config.AGRUP_USAR_IA = False

    config.validar(exigir_microsoft=not argumentos.simular)

    inicio = datetime.now()
    logging.info("=== %s — início %s ===", config.NOME_BOLETIM, inicio.strftime("%d/%m/%Y %H:%M:%S"))
    logging.info("Provedor de IA configurado: %s", config.LLM_PROVIDER)

    # --- 1. Preferências ------------------------------------------------------
    logging.info("\n[1/6] Preferências dos destinatários")
    perfis = fontes.carregar_perfis()
    if not perfis:
        logging.error("Nenhum perfil encontrado. Encerrando.")
        return 1

    # --- 2. Coleta ------------------------------------------------------------
    logging.info("\n[2/6] Coleta no Google News")
    pool = coleta.coletar(perfis, config.PERIODO_BUSCA)
    salvar_json(config.ARQUIVO_CACHE_BRUTO, pool)
    if not pool:
        logging.warning("Nenhuma notícia coletada. Encerrando.")
        return 0

    # --- 3. Triagem -----------------------------------------------------------
    logging.info("\n[3/6] Triagem de relevância")
    aprovadas = triagem.triar(pool)
    if not aprovadas:
        logging.info("Nenhuma notícia relevante hoje. Encerrando.")
        return 0

    # --- 4. Agrupamento global ------------------------------------------------
    logging.info("\n[4/6] Agrupamento global (todos os tópicos e idiomas juntos)")
    clusters = agrupamento.agrupar(aprovadas)

    # --- 5. Resumo e memória --------------------------------------------------
    logging.info("\n[5/6] Resumo dos eventos e checagem do histórico")
    clusters = resumo.resumir_clusters(clusters)
    historico = memoria.carregar()
    clusters, repetidos = memoria.filtrar_novidades(clusters, historico)
    salvar_json(config.ARQUIVO_CACHE_FILTRADO, clusters)

    if not clusters:
        logging.info("Nada de novo depois do cruzamento com o histórico. Encerrando.")
        return 0
    logging.info("Eventos a distribuir: %s (suprimidos por repetição: %s)",
                 len(clusters), len(repetidos))

    # --- 6. Envio -------------------------------------------------------------
    logging.info("\n[6/6] Montagem e envio dos e-mails")
    if argumentos.simular:
        for perfil in perfis:
            selecionados = eventos_do_perfil(clusters, perfil)
            logging.info("  [simulação] %s -> %s eventos", perfil["email"], len(selecionados))
        _gravar_previa(clusters, perfis[0])
        logging.info("Modo simulação: nada foi enviado e o histórico não foi alterado.")
        return 0

    token = graph.obter_token()
    if not token:
        logging.error("Sem token do Microsoft Graph. Encerrando.")
        return 1

    imagem_dados = None
    cid = "cabecalho_boletim"
    if os.path.exists(config.IMAGEM_CABECALHO):
        with open(config.IMAGEM_CABECALHO, "rb") as arquivo:
            imagem_dados = arquivo.read()
    else:
        cid = None
        logging.warning("Imagem de cabeçalho '%s' não encontrada.", config.IMAGEM_CABECALHO)

    data_envio = time.strftime("%d/%m/%Y")
    enviados = 0
    for perfil in perfis:
        selecionados = eventos_do_perfil(clusters, perfil)
        if not selecionados:
            logging.info("  %s: nada novo.", perfil["email"])
            continue

        corpo = email_html.montar(selecionados, perfil.get("keywords_for_display", []), cid)
        if graph.enviar_email(
            token, [perfil["email"]],
            f"AUTOMÁTICO | {config.NOME_BOLETIM} ({data_envio})",
            corpo, imagem_dados, cid,
        ):
            enviados += 1

    if enviados:
        memoria.salvar(historico, clusters)

    fim = datetime.now()
    logging.info("\n=== Fim. %s e-mails enviados. Duração: %s ===", enviados, fim - inicio)
    return 0


def _gravar_previa(clusters, perfil):
    corpo = email_html.montar(
        eventos_do_perfil(clusters, perfil), perfil.get("keywords_for_display", []), None
    )
    with open("previa.html", "w", encoding="utf-8") as arquivo:
        arquivo.write(corpo)
    logging.info("  Prévia gravada em previa.html")


if __name__ == "__main__":
    sys.exit(main())
