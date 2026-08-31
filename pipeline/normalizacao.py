"""Normalização de URLs, títulos e extração de "pistas" (entidades).

É a base do agrupamento: antes de comparar duas notícias é preciso remover o
que difere só por causa do portal (parâmetros de rastreio na URL, sufixo
" - Nome do Veículo" no título) e destacar o que identifica o fato (nomes
próprios, siglas, números com unidade, valores).
"""
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Parâmetros de rastreio: mudam de portal para portal e não identificam a página.
PREFIXOS_RUIDO = ("utm_", "at_", "pk_", "hsa_", "mc_", "wt_", "cx_", "_hs")
PARAMS_RUIDO = {
    "fbclid", "gclid", "gbraid", "wbraid", "igshid", "msclkid", "yclid",
    "ref", "ref_src", "referrer", "source", "src", "spm", "xtor", "cmpid",
    "ncid", "amp", "outputType", "smid", "partner", "cmp", "ito", "CMP",
}

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre
e ou que se ao aos pelo pela pelos pelas seu sua seus suas este esta esse essa isso
mais menos como entre ate apos novo nova ser sera sao tem tem vai vao ja nao
the of to in for on and or with at by from is are was were will be been new its it
as that this has have had after over into up out about more than not can may
der die das und mit von fur im den dem des ein eine einer zur zum auf ist sind
wird werden bei nach aus vor durch uber als auch nicht
""".split())

# Números com unidade: a evidência mais forte de que duas manchetes falam do
# mesmo fato ("12,5 MW", "R$ 148,5 milhões", "15 mil t/ano").
RE_NUM_UNIDADE = re.compile(
    r"\b\d[\d.,]*\s?(?:mw|gw|kw|kwh|mwh|gwh|twh|nm3|m3|bcm|mmbtu|mmbtu|t/ano|tpa|"
    r"kt|mt|bi|bn|mi|mm|k|%|milhoes|milhao|bilhoes|bilhao|million|billion|crore|lakh|"
    r"mil|toneladas|litros|barris|barrels|anos|years)\b",
    re.IGNORECASE,
)
RE_DINHEIRO = re.compile(r"(?:r\$|us\$|u\$|\$|€|£|eur|usd|brl)\s?\d[\d.,]*", re.IGNORECASE)
RE_SIGLA = re.compile(r"\b[A-Z]{2,6}\d?\b")
RE_PROPRIO = re.compile(r"\b[A-ZÁÂÃÀÉÊÍÓÔÕÚÜÇ][\wÀ-ÿ&.'-]{2,}")

# Siglas comuns demais para servirem de pista.
SIGLAS_GENERICAS = {
    "AI", "IA", "EUA", "USA", "UE", "EU", "UK", "CO2", "CO", "GEE", "GHG", "ESG",
    "PIB", "GDP", "SAF", "RNG", "LNG", "GNL", "GNV", "H2", "GH2", "CNG", "HVO",
    "MW", "GW", "KW", "MWH", "GWH", "PDF", "TV", "CEO", "CFO", "COP", "AND", "THE",
    "DER", "DIE", "DAS", "FOR", "NEW", "OR",
}


def remover_acentos(texto):
    forma = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in forma if not unicodedata.combining(c))


def canonicalizar_url(url):
    """Reduz a URL à sua forma comparável.

    Tira www./m./amp., parâmetros de rastreio, sufixo /amp, barra final e
    fragmento, e força https — para que o mesmo artigo servido de três formas
    diferentes vire uma única chave.
    """
    if not url:
        return ""
    try:
        partes = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    host = (partes.netloc or "").lower().split("@")[-1]
    for prefixo in ("www.", "m.", "amp.", "mobile."):
        if host.startswith(prefixo):
            host = host[len(prefixo):]

    caminho = partes.path or "/"
    for sufixo in ("/amp", "/amp/", ".amp", "/amp.html"):
        if caminho.endswith(sufixo):
            caminho = caminho[: -len(sufixo)]
    caminho = caminho.rstrip("/") or "/"

    consulta = [
        (chave, valor)
        for chave, valor in parse_qsl(partes.query, keep_blank_values=False)
        if chave not in PARAMS_RUIDO and not chave.lower().startswith(PREFIXOS_RUIDO)
    ]
    consulta.sort()

    return urlunsplit(("https", host, caminho, urlencode(consulta), ""))


def limpar_titulo(titulo, publisher=None):
    """Remove o sufixo com o nome do veículo, que só atrapalha a comparação."""
    texto = re.sub(r"\s+", " ", (titulo or "").strip())
    if not texto:
        return ""

    if publisher:
        alvo = re.escape(publisher.strip())
        texto = re.sub(rf"\s*[-|–—]\s*{alvo}\s*$", "", texto, flags=re.IGNORECASE)

    # Sem o nome do veículo: corta um rabicho curto depois do último separador.
    partes = re.split(r"\s+[-|–—]\s+", texto)
    if len(partes) > 1 and len(partes[-1]) <= 40 and partes[-1].count(" ") <= 4:
        texto = " ".join(partes[:-1])

    return texto.strip()


def _radical(palavra):
    """Plural simples do português e do inglês, para 'operations' casar com
    'operation' e 'usinas' com 'usina'. Conservador de propósito."""
    if len(palavra) > 4 and palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


def tokenizar(texto):
    """Palavras significativas, sem acento e sem stopwords.

    Compostos com hífen ou barra ("hydrogen-ammonia-methanol", "óleo/gás")
    entram inteiros E em pedaços: é comum um veículo escrever o composto e
    outro escrever os termos separados.
    """
    base = remover_acentos(texto or "").lower()
    brutos = re.findall(r"[a-z0-9][a-z0-9.,%/-]*", base)

    tokens = set()
    for palavra in brutos:
        limpa = palavra.strip(".,/-")
        if not limpa:
            continue
        pedacos = [limpa]
        if "-" in limpa or "/" in limpa:
            pedacos.extend(re.split(r"[-/]+", limpa))
        for pedaco in pedacos:
            if not pedaco or pedaco in STOPWORDS:
                continue
            if len(pedaco) > 3 or any(c.isdigit() for c in pedaco):
                tokens.add(_radical(pedaco))
    return tokens


def extrair_pistas(titulo, resumo=""):
    """Entidades que identificam o fato: siglas, nomes próprios, números, valores."""
    texto = f"{titulo} {resumo}".strip()
    pistas = set()

    for casamento in RE_NUM_UNIDADE.finditer(remover_acentos(texto)):
        pistas.add(re.sub(r"\s+", "", casamento.group(0).lower()))
    for casamento in RE_DINHEIRO.finditer(texto):
        pistas.add(re.sub(r"\s+", "", remover_acentos(casamento.group(0)).lower()))

    for sigla in RE_SIGLA.findall(titulo or ""):
        if sigla.upper() not in SIGLAS_GENERICAS:
            pistas.add(sigla.lower())

    # Nomes próprios: ignora a primeira palavra do título (sempre capitalizada).
    # Em manchete escrita em Title Case ("World's Largest Integrated Green
    # Hydrogen Project...") a maiúscula não distingue nada, então nesse caso
    # ficamos só com siglas e números — senão o título inteiro viraria "pista".
    palavras = (titulo or "").split()
    if not _title_case(palavras):
        for palavra in palavras[1:]:
            candidato = palavra.strip(".,;:!?()[]\"'")
            if len(candidato) < 4 or not RE_PROPRIO.fullmatch(candidato):
                continue
            chave = remover_acentos(candidato).lower()
            if chave in STOPWORDS:
                continue
            pistas.add(chave)

    return pistas


def _title_case(palavras, limite=0.6):
    """Verdadeiro quando a maioria das palavras longas começa com maiúscula."""
    longas = [p for p in palavras if len(p.strip(".,;:!?()[]\"'")) >= 4]
    if len(longas) < 4:
        return False
    capitalizadas = sum(1 for p in longas if p[:1].isupper())
    return capitalizadas / len(longas) >= limite


def assinatura(noticia):
    """Anexa à notícia os campos derivados usados no agrupamento."""
    titulo_limpo = limpar_titulo(noticia.get("titulo"), _nome_publisher(noticia))
    noticia["titulo_limpo"] = titulo_limpo
    noticia["url_canonica"] = canonicalizar_url(noticia.get("link"))
    noticia["tokens"] = tokenizar(titulo_limpo)
    noticia["pistas"] = extrair_pistas(titulo_limpo, noticia.get("resumo", ""))
    return noticia


def _nome_publisher(noticia):
    publisher = noticia.get("publisher")
    if isinstance(publisher, dict):
        return publisher.get("title") or publisher.get("href")
    return publisher


def nome_publisher(noticia):
    """Nome do veículo, aceitando o formato do gnews (dict) ou texto puro."""
    return _nome_publisher(noticia) or "Fonte desconhecida"
