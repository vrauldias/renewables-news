"""Resumo de uma frase, gerado UMA VEZ POR EVENTO.

Na versão anterior o resumo era gerado para toda notícia aprovada, antes do
agrupamento — cinco portais sobre o mesmo fato custavam cinco downloads e
cinco chamadas de IA, das quais quatro eram jogadas fora. Aqui só o
representante de cada evento é resumido; se o link dele falhar, tenta-se o
próximo portal do mesmo evento, o que também torna o processo mais robusto.
"""
import logging
import re

from llm import prompts
from llm.provedores import obter_cliente
from pipeline import extracao, normalizacao

log = logging.getLogger(__name__)

IDIOMAS = {"pt-419": "português", "pt": "português", "en": "inglês", "de": "alemão", "es": "espanhol"}

RE_INTRODUCAO = re.compile(
    r"^\s*(?:aqui est[áa]|segue|claro[,!]?|resumo:|em resumo[,:]?|o (?:artigo|texto|resumo)|"
    r"a not[íi]cia|here (?:is|'s)|the (?:article|text))\b[^.]*[.:]?\s*",
    re.IGNORECASE,
)


def _limpar(texto):
    if not texto:
        return ""
    limpo = texto.strip().strip('"').strip("«»").strip()
    limpo = RE_INTRODUCAO.sub("", limpo).strip()
    limpo = re.sub(r"\s+", " ", limpo)
    return limpo[:1].upper() + limpo[1:] if limpo else ""


def _texto_da_noticia(noticia):
    """Tenta o corpo da matéria; cai para a descrição do feed."""
    try:
        url_final = extracao.resolver_url_final(noticia["link"])
    except Exception:  # noqa: BLE001
        url_final = None
    if url_final:
        noticia["link"] = url_final
        noticia["url_canonica"] = normalizacao.canonicalizar_url(url_final)
        corpo = extracao.extrair_texto(url_final)
        if corpo:
            return corpo
    descricao = (noticia.get("descricao") or "").strip()
    return descricao if len(descricao) > 80 else None


def resumir_clusters(clusters):
    """Preenche `resumo` no representante de cada evento.

    Eventos cujo texto não pôde ser obtido em nenhum dos portais são
    descartados — é o que evitava, na versão anterior, resumos "ERRO" e
    resumos vazios chegarem ao e-mail.
    """
    cliente = obter_cliente()
    mantidos = []

    for cluster in clusters:
        candidatos = [cluster["principal"], *cluster["outros_sites"]]
        resumo = ""
        for candidato in candidatos:
            texto = _texto_da_noticia(candidato)
            if not texto:
                continue
            idioma = IDIOMAS.get(candidato.get("idioma", ""), "português")
            try:
                bruto = cliente.gerar(
                    sistema=prompts.SISTEMA_RESUMO,
                    usuario=prompts.USUARIO_RESUMO.format(
                        idioma=idioma, titulo=candidato["titulo_limpo"], texto=texto
                    ),
                    max_tokens=200,
                    tarefa="resumo",
                )
            except Exception as erro:  # noqa: BLE001
                log.warning("  Resumo falhou: %s", erro)
                continue
            resumo = _limpar(bruto)
            if len(resumo) >= 25:
                # O portal que respondeu passa a ser o principal do evento.
                if candidato is not cluster["principal"]:
                    cluster["outros_sites"] = [
                        n for n in candidatos if n is not candidato
                    ]
                    cluster["principal"] = candidato
                break
            resumo = ""

        if not resumo:
            log.info("  Evento descartado (nenhum portal pôde ser lido): %s",
                     cluster["principal"]["titulo_limpo"][:70])
            continue

        cluster["principal"]["resumo"] = resumo
        mantidos.append(cluster)

    log.info("  Resumos: %s eventos mantidos de %s.", len(mantidos), len(clusters))
    return mantidos
