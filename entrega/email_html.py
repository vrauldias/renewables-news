"""Montagem do HTML do boletim."""
import html
from datetime import datetime

import pytz

import config
from pipeline import normalizacao

FUSO = pytz.timezone("America/Sao_Paulo")

ESTILO = """
body{font-family:Arial,Helvetica,sans-serif;margin:0;padding:0;background-color:#f4f4f4}
.email-container{width:100%;max-width:680px;margin:20px auto;background-color:#fff;border:1px solid #ddd}
.header-image{width:100%;max-height:150px;object-fit:cover}
.content{padding:20px}
.news-title-section h1{color:#333;font-size:22px;margin-top:0}
.news-title-section p{color:#555;font-size:14px}
.news-item{margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}
.news-item:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}
.news-item h2{font-size:18px;margin-top:0;margin-bottom:5px}
.news-item h2 a{color:#005a9e;text-decoration:none}
.news-item h2 a:hover{text-decoration:underline}
.news-item .summary{font-size:14px;color:#555;margin:8px 0;font-style:italic;line-height:1.5}
.news-item .details{font-size:12px;color:#777;margin:4px 0}
.tag{display:inline-block;background:#eef4fa;color:#005a9e;font-size:11px;
     padding:2px 7px;border-radius:10px;margin-right:4px}
.tag-repetido{background:#fdf0e3;color:#9a5b00}
.footer{padding:15px;text-align:center;background-color:#f9f9f9;border-top:1px solid #ddd}
.footer p{font-size:12px;color:#888;margin:0}
"""


def formatar_data(data_gmt):
    if not data_gmt:
        return "data não disponível"
    try:
        momento = datetime.strptime(data_gmt, "%a, %d %b %Y %H:%M:%S %Z")
        return pytz.utc.localize(momento).astimezone(FUSO).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return data_gmt


def _bloco_evento(cluster):
    principal = cluster["principal"]
    veiculo = normalizacao.nome_publisher(principal)
    titulo = html.escape(principal.get("titulo_limpo") or principal.get("titulo", "Sem título"))
    resumo = html.escape(principal.get("resumo", ""))
    link = html.escape(principal.get("link", "#"), quote=True)

    partes = [f'<div class="news-item">\n<h2><a href="{link}" target="_blank">{titulo}</a></h2>']

    etiquetas = "".join(
        f'<span class="tag">{html.escape(t)}</span>' for t in cluster.get("topicos", [])
    )
    if cluster.get("repetido"):
        etiquetas += '<span class="tag tag-repetido">já publicado</span>'
    if etiquetas:
        partes.append(f'<p class="details">{etiquetas}</p>')

    if resumo:
        partes.append(f'<p class="summary">{resumo}</p>')

    partes.append(
        f'<p class="details">Publicado em: {formatar_data(principal.get("published date"))} '
        f'por <strong>{html.escape(veiculo)}</strong></p>'
    )

    outros = cluster.get("outros_sites", [])
    if outros:
        vistos, links = set(), []
        for site in outros:
            nome = normalizacao.nome_publisher(site)
            if nome in vistos:
                continue
            vistos.add(nome)
            links.append(
                f'<a href="{html.escape(site.get("link", "#"), quote=True)}" '
                f'target="_blank">{html.escape(nome)}</a>'
            )
        if links:
            partes.append(
                f'<p class="details">Também em ({len(links)}): {", ".join(links)}</p>'
            )

    partes.append("</div>")
    return "\n".join(partes)


def montar(clusters, categorias_usuario, imagem_cid=None):
    corpo = "\n".join(_bloco_evento(c) for c in clusters)
    titulo_pagina = html.escape(config.NOME_BOLETIM)
    preferencias = html.escape(", ".join(categorias_usuario)) or "todas as categorias"

    cabecalho = (
        f'<img src="cid:{imagem_cid}" class="header-image">'
        if imagem_cid else
        f'<div style="background-color:#2c3e50;color:#fff;padding:20px;text-align:center;'
        f'font-size:28px;font-weight:bold">{titulo_pagina}</div>'
    )

    rodape_filtros = ""
    if config.PALAVRAS_EXCLUIDAS_TITULO:
        termos = html.escape(", ".join(config.PALAVRAS_EXCLUIDAS_TITULO))
        rodape_filtros = (
            f'<p style="font-size:10px;color:#aaa;margin-top:5px">'
            f'<i>Notícias com os termos a seguir foram filtradas: {termos}.</i></p>'
        )

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>{titulo_pagina}</title><style>{ESTILO}</style></head><body>
<div class="email-container">
{cabecalho}
<div class="content">
<div class="news-title-section">
<h1>Notícias das últimas {html.escape(config.PERIODO_BUSCA)}</h1>
<p><strong>Suas preferências:</strong> {preferencias}</p>
<p>Para alterar suas preferências clique
<a href="{html.escape(config.LINK_PREFERENCIAS, quote=True)}" target="_blank">aqui</a>.</p>
</div>
<hr style="border:0;border-top:1px solid #eee;margin:20px 0">
{corpo}
</div>
<div class="footer">
<p><img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f916/512.gif"
style="height:16px;width:16px;vertical-align:middle;"> Este é um e-mail automático.</p>
{rodape_filtros}
</div></div></body></html>"""
