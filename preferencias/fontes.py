"""Preferências dos destinatários.

Duas fontes possíveis, escolhidas por FONTE_PREFERENCIAS no .env:
  * `sharepoint` — lê a lista do Microsoft Lists (uma linha por resposta de
    formulário; vale a resposta mais recente de cada e-mail);
  * `arquivo`    — usa um preferencias.json mantido à mão.

Formato de saída (o que o resto do pipeline consome):

    [{"email": "...",
      "keywords_for_display": ["Biogás", "Biometano"],
      "search_configs": [{"lang_code": "pt-419",
                          "termos": [{"categoria": "Biogás",
                                      "expressao": "biogás OR biodigestor"}]}]}]

Note o campo `termos`: uma lista de pares categoria/expressão, em vez da
`query_string` única e entre aspas da versão anterior. É o que permite buscar
cada termo separadamente no Google News e, ainda assim, saber a que categoria
o resultado pertence.
"""
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime

import msal
import requests
from tenacity import retry, stop_after_attempt, wait_fixed

import config
from entrega import graph

log = logging.getLogger(__name__)


# =============================================================================
# Dicionários de palavras-chave
# =============================================================================

def carregar_mapeamento(caminho):
    mapa = {}
    if not os.path.exists(caminho):
        return mapa
    with open(caminho, "r", encoding="utf-8") as arquivo:
        for numero, linha in enumerate(arquivo):
            if numero == 0 or not linha.strip():
                continue
            partes = linha.rstrip("\n").split("\t")
            if len(partes) >= 2 and partes[0].strip():
                mapa[partes[0].strip()] = partes[1].strip()
    return mapa


def carregar_dicionarios(mapa_idiomas):
    dicionarios = {config.IDIOMA_BASE: carregar_mapeamento(config.ARQUIVO_KEYWORDS_BASE)}
    for codigo in set(mapa_idiomas.values()):
        if codigo == config.IDIOMA_BASE:
            continue
        caminho = f"keywords-to-gnews-{codigo}.txt"
        if os.path.exists(caminho):
            dicionarios[codigo] = carregar_mapeamento(caminho)
        else:
            log.warning("Dicionário '%s' não encontrado; usando o padrão.", caminho)
            dicionarios[codigo] = dicionarios[config.IDIOMA_BASE]
    return dicionarios


def montar_search_configs(categorias, idiomas, mapa_idiomas, dicionarios):
    configuracoes = []
    for nome_idioma in idiomas:
        codigo = mapa_idiomas.get(nome_idioma)
        if not codigo:
            continue
        dicionario = dicionarios.get(codigo, dicionarios.get(config.IDIOMA_BASE, {}))
        termos = [
            {"categoria": categoria, "expressao": dicionario.get(categoria, categoria)}
            for categoria in categorias
        ]
        if termos:
            configuracoes.append({"lang_code": codigo, "termos": termos})
    return configuracoes


# =============================================================================
# Fonte: arquivo
# =============================================================================

def _do_arquivo():
    if not os.path.exists(config.ARQUIVO_PREFERENCIAS):
        sys.exit(
            f"ERRO: FONTE_PREFERENCIAS=arquivo mas '{config.ARQUIVO_PREFERENCIAS}' "
            "não existe. Use preferencias.exemplo.json como modelo."
        )
    with open(config.ARQUIVO_PREFERENCIAS, "r", encoding="utf-8") as arquivo:
        perfis = json.load(arquivo)

    # Aceita o formato antigo (query_string) para não quebrar quem já tem o arquivo.
    mapa_idiomas = carregar_mapeamento(config.ARQUIVO_IDIOMAS)
    dicionarios = carregar_dicionarios(mapa_idiomas)
    for perfil in perfis:
        for configuracao in perfil.get("search_configs", []):
            if "termos" in configuracao:
                continue
            import re
            expressoes = re.findall(r'"(.*?)"', configuracao.get("query_string", ""))
            configuracao["termos"] = [
                {"categoria": perfil.get("keywords_for_display", [""])[0] if expressoes else "",
                 "expressao": e}
                for e in expressoes
            ]
    del dicionarios  # só carregado para validar a existência dos arquivos
    return perfis


# =============================================================================
# Fonte: SharePoint / Microsoft Lists
# =============================================================================

class OperacoesSharePoint:
    def __init__(self, site_url, chave_privada):
        self.site_url = site_url.rstrip("/")
        partes = urllib.parse.urlparse(site_url)
        dominio = f"{partes.scheme}://{partes.netloc}"

        aplicacao = msal.ConfidentialClientApplication(
            config.CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{config.TENANT_ID}",
            client_credential={"private_key": chave_privada, "thumbprint": config.CERT_THUMBPRINT},
        )
        resultado = aplicacao.acquire_token_for_client(scopes=[f"{dominio}/.default"])
        if "access_token" not in resultado:
            raise RuntimeError(f"token do SharePoint negado: {resultado.get('error_description')}")

        self.headers = {
            "Authorization": f"Bearer {resultado['access_token']}",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def itens(self, lista, campos, expandir):
        url = (
            f"{self.site_url}/_api/web/lists/getbytitle('{lista}')/items"
            f"?$select={','.join(campos)}&$expand={','.join(expandir)}&$top=5000"
        )
        resposta = requests.get(url, headers=self.headers, timeout=60)
        resposta.raise_for_status()
        return resposta.json().get("d", {}).get("results", [])


def _do_sharepoint(mapa_idiomas, dicionarios):
    chave = graph.ler_chave_privada()
    if not chave:
        sys.exit("ERRO: chave privada necessária para ler as preferências no SharePoint.")

    operacoes = OperacoesSharePoint(config.SHAREPOINT_SITE_URL, chave)
    registros = operacoes.itens(
        config.SHAREPOINT_LIST_NAME,
        [config.SHAREPOINT_FIELD_CATEGORIES, "Author/EMail", "Modified",
         config.SHAREPOINT_FIELD_LANGUAGES],
        ["Author"],
    )
    log.info("Registros na lista: %s", len(registros))

    mais_recentes = {}
    for registro in registros:
        email = (registro.get("Author") or {}).get("EMail")
        modificado = registro.get("Modified")
        if not email or not modificado:
            continue
        try:
            quando = datetime.strptime(modificado, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        if email in mais_recentes and quando <= mais_recentes[email]["quando"]:
            continue

        def _lista(campo):
            valor = registro.get(campo, {})
            return valor.get("results", []) if isinstance(valor, dict) else []

        mais_recentes[email] = {
            "quando": quando,
            "categorias": _lista(config.SHAREPOINT_FIELD_CATEGORIES),
            "idiomas": _lista(config.SHAREPOINT_FIELD_LANGUAGES) or [config.IDIOMA_PADRAO],
        }

    return [
        {
            "email": email,
            "keywords_for_display": dados["categorias"],
            "search_configs": montar_search_configs(
                dados["categorias"], dados["idiomas"], mapa_idiomas, dicionarios
            ),
        }
        for email, dados in mais_recentes.items()
    ]


# =============================================================================
# Ponto de entrada
# =============================================================================

def carregar_perfis():
    if config.FONTE_PREFERENCIAS == "arquivo":
        perfis = _do_arquivo()
    else:
        mapa_idiomas = carregar_mapeamento(config.ARQUIVO_IDIOMAS)
        dicionarios = carregar_dicionarios(mapa_idiomas)
        perfis = _do_sharepoint(mapa_idiomas, dicionarios)
        with open(config.ARQUIVO_PREFERENCIAS, "w", encoding="utf-8") as arquivo:
            json.dump(perfis, arquivo, ensure_ascii=False, indent=2)

    log.info("Perfis carregados: %s", len(perfis))
    return perfis
