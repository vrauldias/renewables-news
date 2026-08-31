"""Busca das notícias brutas no Google News.

Correção importante em relação à versão anterior: cada categoria do arquivo de
palavras-chave é uma expressão com vários termos ("SAF OR Sustainable Aviation
Fuel OR BioQAV"). A versão anterior mandava a expressão inteira entre aspas
para o Google News, o que vira uma busca por frase exata e devolve zero
resultado. Aqui a expressão é quebrada nos seus termos e cada termo é buscado
separadamente; todos os resultados são creditados à mesma categoria.
"""
import logging
import re

from gnews import GNews

log = logging.getLogger(__name__)


def separar_termos(expressao):
    """'SAF OR Sustainable Aviation Fuel OR BioQAV' -> os três termos."""
    if not expressao:
        return []
    partes = re.split(r"\s+(?:OR|\|)\s+", expressao.strip(), flags=re.IGNORECASE)
    return [p.strip().strip('"') for p in partes if p.strip().strip('"')]


def buscar(termo, idioma, periodo, pais=None):
    log.info("  [%s] %s", idioma, termo)
    google_news = GNews(language=idioma, country=pais, period=periodo)
    try:
        return google_news.get_news(termo) or []
    except Exception as erro:  # noqa: BLE001
        log.error("    -> erro na busca: %s", erro)
        return []


def coletar(perfis, periodo):
    """Executa cada par (termo, idioma) uma única vez e devolve o pool bruto.

    Cada notícia carrega a lista de CATEGORIAS que a trouxeram — é isso que
    permite agrupar globalmente e, só na hora de montar o e-mail, decidir se
    aquele evento interessa a cada destinatário.
    """
    buscas = {}  # (termo, idioma) -> conjunto de categorias
    for perfil in perfis:
        for configuracao in perfil.get("search_configs", []):
            idioma = configuracao.get("lang_code")
            if not idioma:
                continue
            for entrada in configuracao.get("termos", []):
                categoria = entrada.get("categoria", "")
                for termo in separar_termos(entrada.get("expressao", "")):
                    buscas.setdefault((termo, idioma), set()).add(categoria)

    log.info("Buscas únicas a executar: %s", len(buscas))

    pool = []
    for (termo, idioma), categorias in sorted(buscas.items()):
        for bruta in buscar(termo, idioma, periodo):
            pool.append({
                "titulo": bruta.get("title", ""),
                "link": bruta.get("url", ""),
                "descricao": bruta.get("description", ""),
                "published date": bruta.get("published date"),
                "publisher": bruta.get("publisher"),
                "idioma": idioma,
                "topicos": sorted(categorias),
                "termo_busca": termo,
            })

    log.info("Notícias brutas coletadas: %s", len(pool))
    return pool
