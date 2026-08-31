"""Resolução do link real do Google News e extração do texto da matéria."""
import json
import logging

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def resolver_url_final(url_google):
    """Troca o link do agregador pelo link do veículo."""
    resposta = requests.get(url_google, headers=CABECALHOS, timeout=10, allow_redirects=True)

    if "news.google.com" not in resposta.url and "google.com" not in resposta.url:
        return resposta.url

    sopa = BeautifulSoup(resposta.text, "html.parser")
    elemento = sopa.select_one("c-wiz[data-p]")
    if not elemento:
        return url_google if resposta.status_code == 200 else None

    dados = json.loads(elemento.get("data-p").replace("%.@.", '["garturlreq",'))
    corpo = {"f.req": json.dumps([[["Fbv4je", json.dumps(dados[:-6] + dados[-2:]), "null", "generic"]]])}
    lote = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        headers={
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "user-agent": CABECALHOS["User-Agent"],
        },
        data=corpo,
        timeout=10,
    )
    lote.raise_for_status()
    vetor = json.loads(lote.text.replace(")]}'", ""))
    return json.loads(vetor[0][2])[1]


def extrair_texto(url, limite=2500):
    """Texto legível da página, ou None se não der para aproveitar."""
    try:
        resposta = requests.get(url, headers=CABECALHOS, timeout=10)
        tipo = resposta.headers.get("Content-Type", "").lower()
        if "application/pdf" in tipo or tipo.startswith("image"):
            return None
        sopa = BeautifulSoup(resposta.text, "html.parser")
        for elemento in sopa(["script", "style", "header", "footer", "nav",
                              "aside", "form", "iframe", "noscript"]):
            elemento.decompose()
        texto = " ".join(p.strip() for p in sopa.stripped_strings)
        return texto[:limite] if texto and len(texto) > 300 else None
    except Exception as erro:  # noqa: BLE001
        log.debug("  Falha ao extrair texto de %s: %s", url, erro)
        return None
