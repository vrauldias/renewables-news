"""Configuração central do boletim, lida do .env.

Todo o resto do projeto importa daqui em vez de chamar os.getenv espalhado.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _txt(nome, padrao=""):
    valor = os.getenv(nome)
    return valor.strip() if valor and valor.strip() else padrao


def _num(nome, padrao):
    try:
        return float(os.getenv(nome, "").strip())
    except (TypeError, ValueError):
        return padrao


def _int(nome, padrao):
    try:
        return int(float(os.getenv(nome, "").strip()))
    except (TypeError, ValueError):
        return padrao


def _bool(nome, padrao):
    valor = _txt(nome)
    if not valor:
        return padrao
    return valor.lower() in ("1", "true", "sim", "yes", "on")


# --- 1. Provedor de IA -------------------------------------------------------
LLM_PROVIDER = _txt("LLM_PROVIDER", "groq").lower()

LLM_MODELO_TRIAGEM = _txt("LLM_MODELO_TRIAGEM")
LLM_MODELO_AGRUPAMENTO = _txt("LLM_MODELO_AGRUPAMENTO")
LLM_MODELO_RESUMO = _txt("LLM_MODELO_RESUMO")

LLM_EFFORT_TRIAGEM = _txt("LLM_EFFORT_TRIAGEM", "low")
LLM_EFFORT_AGRUPAMENTO = _txt("LLM_EFFORT_AGRUPAMENTO", "medium")
LLM_EFFORT_RESUMO = _txt("LLM_EFFORT_RESUMO", "low")

LLM_INTERVALO_ENTRE_CHAMADAS = _num("LLM_INTERVALO_ENTRE_CHAMADAS", 1.0)
LLM_MAX_TENTATIVAS = _int("LLM_MAX_TENTATIVAS", 5)

# --- 2. Agrupamento ----------------------------------------------------------
AGRUP_LIMIAR_BLOCO = _num("AGRUP_LIMIAR_BLOCO", 0.22)
AGRUP_LIMIAR_CERTEZA = _num("AGRUP_LIMIAR_CERTEZA", 0.62)
AGRUP_MAX_ITENS_POR_BLOCO = _int("AGRUP_MAX_ITENS_POR_BLOCO", 25)
AGRUP_USAR_IA = _bool("AGRUP_USAR_IA", True)

HISTORICO_JANELA_DIAS = _int("HISTORICO_JANELA_DIAS", 7)
HISTORICO_LIMIAR = _num("HISTORICO_LIMIAR", 0.50)
HISTORICO_MODO = _txt("HISTORICO_MODO", "suprimir").lower()

# --- 3. Microsoft ------------------------------------------------------------
TENANT_ID = _txt("TENANT_ID")
CLIENT_ID = _txt("CLIENT_ID")
CERT_THUMBPRINT = _txt("CERT_THUMBPRINT")
PRIVATE_KEY_FILE_PATH = _txt("PRIVATE_KEY_FILE_PATH", "private_key.pem")

# --- 4. Boletim --------------------------------------------------------------
EMAIL_REMETENTE = _txt("EMAIL_REMETENTE")
NOME_BOLETIM = _txt("NOME_BOLETIM", "Radar de Combustíveis Renováveis")
LINK_PREFERENCIAS = _txt("LINK_PREFERENCIAS", "#")
PERIODO_BUSCA = _txt("PERIODO_BUSCA", "24h")
IMAGEM_CABECALHO = _txt("IMAGEM_CABECALHO", "header.png")

PALAVRAS_EXCLUIDAS_TITULO = ["concurso", "vaga de emprego", "edital"]

# --- 5. Preferências ---------------------------------------------------------
FONTE_PREFERENCIAS = _txt("FONTE_PREFERENCIAS", "sharepoint").lower()
SHAREPOINT_SITE_URL = _txt("SHAREPOINT_SITE_URL")
SHAREPOINT_LIST_NAME = _txt("SHAREPOINT_LIST_NAME")
SHAREPOINT_FIELD_CATEGORIES = _txt("SHAREPOINT_FIELD_CATEGORIES", "CategoriasNoticias")
SHAREPOINT_FIELD_LANGUAGES = _txt("SHAREPOINT_FIELD_LANGUAGES", "EscolherLinguas")
IDIOMA_PADRAO = _txt("IDIOMA_PADRAO", "Português")

# --- 6. Arquivos -------------------------------------------------------------
ARQUIVO_PREFERENCIAS = "preferencias.json"
ARQUIVO_CACHE_BRUTO = "cache_bruto.json"
ARQUIVO_CACHE_FILTRADO = "cache_filtrado.json"
ARQUIVO_HISTORICO = "historico_eventos.json"
PASTA_LOGS = "logs"

ARQUIVO_IDIOMAS = "languages-to-gnews.txt"
ARQUIVO_KEYWORDS_BASE = "keywords-to-gnews.txt"
IDIOMA_BASE = "pt-419"


def validar(exigir_microsoft=True):
    """Aborta cedo com mensagem clara se faltar configuração essencial."""
    faltando = []
    if not LLM_PROVIDER:
        faltando.append("LLM_PROVIDER")
    if exigir_microsoft:
        for nome in ("TENANT_ID", "CLIENT_ID", "CERT_THUMBPRINT", "EMAIL_REMETENTE"):
            if not globals()[nome]:
                faltando.append(nome)
    if faltando:
        print(
            "ERRO: variáveis obrigatórias ausentes no .env: "
            + ", ".join(faltando)
            + "\nCopie .env.example para .env e preencha."
        )
        sys.exit(1)
