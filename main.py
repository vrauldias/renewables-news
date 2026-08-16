from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from gnews import GNews
import time
from datetime import datetime
import pytz
import base64
import json
import subprocess
import sys
import re
import os
import requests
import msal
import logging
from dotenv import load_dotenv

load_dotenv()

# --- Classe para redirecionar o output para o log ---
class LoggerWriter:
    def __init__(self, level):
        self.level = level

    def write(self, message):
        if message != '\n':
            self.level(message)

    def flush(self):
        pass

#CONFIGURAÇÕES MSAL (definidas via variáveis de ambiente, ver .env.example)
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CERT_THUMBPRINT = os.getenv("CERT_THUMBPRINT")
PRIVATE_KEY_FILE_PATH = os.getenv("PRIVATE_KEY_FILE_PATH", "private_key.pem")

# --- Configurações Gerais ---
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")
PERIODO = '24h'
PALAVRAS_EXCLUIDAS_TITULO = ["concurso", "vaga de emprego", "edital"]

ARQUIVO_PREFERENCIAS = "preferencias.json"
ARQUIVO_CACHE_BRUTO = "cache_bruto.json"
ARQUIVO_CACHE_FILTRADO = "cache_filtrado.json"
ARQUIVO_LINKS_ENVIADOS = "links_enviados.txt"
caminho_imagem_cabecalho = "header.png"
PASTA_LOGS = "logs" # <-- Adicionado para logs

LINK_PREFERENCIAS = os.getenv("LINK_PREFERENCIAS", "#")
NOME_BOLETIM = os.getenv("NOME_BOLETIM", "Radar de Combustíveis Renováveis")

# --- Funções ---
def obter_token_acesso():
    """
    Autentica na Azure AD usando o certificado e a chave privada
    para obter um token de acesso para a API do Microsoft Graph.
    """
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    scope = ["https://graph.microsoft.com/.default"]

    if not os.path.exists(PRIVATE_KEY_FILE_PATH):
        logging.error(f"Erro: Arquivo da chave privada não encontrado em '{PRIVATE_KEY_FILE_PATH}'")
        return None

    try:
        with open(PRIVATE_KEY_FILE_PATH, 'r') as pem_file:
            private_key = pem_file.read()
    except Exception as e:
        logging.error(f"Erro ao ler o arquivo da chave privada: {e}")
        return None

    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        authority=authority,
        client_credential={"private_key": private_key, "thumbprint": CERT_THUMBPRINT}
    )

    result = app.acquire_token_for_client(scopes=scope)

    if "access_token" in result:
        logging.info("Token de acesso obtido com sucesso!")
        return result['access_token']
    else:
        logging.error("Erro ao obter o token de acesso:")
        logging.error(result.get("error"))
        logging.error(result.get("error_description"))
        return None

def buscar_noticias(palavras_chave, lingua, pais=None, periodo=None): # pais=None por padrão
    logging.info(f"  Buscando notícias [{lingua}]: {palavras_chave}")
    # country=None permite busca global filtrada apenas pela lingua
    google_news = GNews(language=lingua, country=pais, period=periodo)
    try:
        noticias = google_news.get_news(palavras_chave)
        return noticias if noticias else []
    except Exception as e:
        logging.error(f"    -> Erro ao buscar notícias: {e}")
        return []

def carregar_links_enviados(arquivo):
    try:
        with open(arquivo, 'r', encoding='utf-8') as f: return set(line.strip() for line in f)
    except FileNotFoundError: return set()

def salvar_link_enviado(arquivo, link):
    with open(arquivo, 'a', encoding='utf-8') as f: f.write(link + "\n")

def carregar_json(arquivo_json):
    try:
        with open(arquivo_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"ERRO: Arquivo de entrada '{arquivo_json}' não encontrado.")
        return None
    except json.JSONDecodeError:
        logging.error(f"ERRO: O arquivo '{arquivo_json}' contém um erro de formatação.")
        return None

def enviar_email_graph(access_token, destinatarios_lista, assunto, corpo_html, remetente, imagem_header_data=None, imagem_header_cid=None):
    """
    Envia um e-mail usando a API do Microsoft Graph com autenticação OAuth.
    """
    graph_url = f"https://graph.microsoft.com/v1.0/users/{remetente}/sendMail"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    email_body = {
        'message': {
            'subject': assunto,
            'body': {'contentType': 'HTML', 'content': corpo_html},
            'toRecipients': [{'emailAddress': {'address': addr}} for addr in destinatarios_lista]
        },
        'saveToSentItems': 'true'
    }

    # Adiciona a imagem de cabeçalho como um anexo embutido (inline)
    if imagem_header_data and imagem_header_cid:
        encoded_image = base64.b64encode(imagem_header_data).decode('utf-8')
        email_body['message']['attachments'] = [
            {
                '@odata.type': '#microsoft.graph.fileAttachment',
                'name': 'header.png',
                'contentType': 'image/png',
                'contentBytes': encoded_image,
                'contentId': imagem_header_cid,
                'isInline': True
            }
        ]

    response = requests.post(graph_url, headers=headers, data=json.dumps(email_body))

    if response.status_code == 202:
        logging.info(f"E-mail enviado com sucesso para: {', '.join(destinatarios_lista)}")
        return True
    else:
        logging.error(f"Erro ao enviar e-mail: Status {response.status_code} - {response.text}")
        return False

def formatar_data_publicacao(data_str_gmt):
    if not data_str_gmt: return "Data não disponível"
    try:
        dt_gmt = datetime.strptime(data_str_gmt, '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=pytz.utc)
        return dt_gmt.astimezone(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
    except Exception: return data_str_gmt

# --- Lógica Principal com Orquestração em 4 Passos ---
if __name__ == "__main__":
    # --- Configuração do Logging ---
    if not os.path.exists(PASTA_LOGS):
        os.makedirs(PASTA_LOGS)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = os.path.join(PASTA_LOGS, f"main_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, 'w', 'utf-8'),
            logging.StreamHandler()
        ]
    )

    # Redireciona o stdout e stderr para o logger
    sys.stdout = LoggerWriter(logging.info)
    sys.stderr = LoggerWriter(logging.error)

    logging.info("--- INICIANDO ORQUESTRADOR DE NOTÍCIAS ---")

    hora_inicio = datetime.now()
    logging.info(f"Início da execução: {hora_inicio.strftime('%d/%m/%Y %H:%M:%S')}")


    logging.info("\nETAPA 0: Obtendo token de acesso do Microsoft Graph...")
    access_token = obter_token_acesso()
    if not access_token:
        logging.error("!!! ERRO CRÍTICO: Não foi possível obter o token de acesso. Verifique as configurações e permissões no Azure. Abortando.")
        sys.exit(1)

    # --- ETAPA 1 ---
    try:
        logging.info("\nETAPA 1: Executando o script de coleta de preferências (coleta_preferencias.py)...")
        resultado_coleta = subprocess.run([sys.executable, "coleta_preferencias.py"], check=True, text=True, encoding='utf-8', errors='replace', capture_output=True)
        logging.info(resultado_coleta.stdout)
        logging.info(">>> Coleta de preferências executada com sucesso.")
    except Exception as e:
        logging.error(f"!!! ERRO CRÍTICO na ETAPA 1: {e}")
        if isinstance(e, subprocess.CalledProcessError): logging.error(f"--- Log de Erro do Coletor ---\n{e.stderr}")
        sys.exit(1)

    # --- ETAPA 2 ---
    logging.info("\nETAPA 2: Buscando notícias brutas (Multi-língua)...")
    perfis_de_usuario = carregar_json(ARQUIVO_PREFERENCIAS)
    if not perfis_de_usuario:
        sys.exit(1)

    # Conjunto para evitar buscas duplicadas: (termo_limpo, lang_code)
    buscas_unicas = set()

    for perfil in perfis_de_usuario:
        configs = perfil.get("search_configs", [])
        for cfg in configs:
            lang = cfg['lang_code']
            query = cfg['query_string']
            # Extrai termos individuais da query string "termo1" OR "termo2"
            termos = re.findall(r'"(.*?)"', query)
            for t in termos:
                buscas_unicas.add((t, lang))

    cache_bruto = {}
    for termo, lang in buscas_unicas:
        # A chave do cache agora precisa incluir a lingua para diferenciar
        chave_cache = f"{termo}|{lang}"
        # Busca com country=None
        noticias = buscar_noticias(f'"{termo}"', lang, pais=None, periodo=PERIODO)
        cache_bruto[chave_cache] = noticias

    with open(ARQUIVO_CACHE_BRUTO, 'w', encoding='utf-8') as f: json.dump(cache_bruto, f, indent=4)
    logging.info(">>> Cache de notícias bruto salvo com sucesso.")

    # --- ETAPA 3 ---
    try:
        logging.info("\nETAPA 3: Executando filtro com IA (filtro_ia.py)...")
        resultado_filtro = subprocess.run([sys.executable, "filtro_ia.py"], check=True, text=True, encoding='utf-8', errors='replace', capture_output=True)
        logging.info(resultado_filtro.stdout)
    except Exception as e:
        logging.error(f"!!! ERRO CRÍTICO na ETAPA 3: {e}")
        if isinstance(e, subprocess.CalledProcessError): logging.error(e.stderr)
        sys.exit(1)

    # --- ETAPA 0-adicional ---
    logging.info("\nETAPA 0-adicional: Obtendo token de acesso do Microsoft Graph...")
    access_token = obter_token_acesso()
    if not access_token:
        logging.error("!!! ERRO CRÍTICO: Não foi possível obter o token de acesso. Verifique as configurações e permissões no Azure. Abortando.")
        sys.exit(1)

    # --- ETAPA 4 ---
    logging.info("\nETAPA 4: Montando e-mails...")
    cache_filtrado = carregar_json(ARQUIVO_CACHE_FILTRADO)
    if cache_filtrado is None:
        logging.info("Não foi possível carregar o cache filtrado. Finalizando.")
        sys.exit(1)

    links_ja_enviados = carregar_links_enviados(ARQUIVO_LINKS_ENVIADOS)
    id_imagem_cabecalho = 'image_header_cid'
    dados_imagem_cabecalho = None
    try:
        with open(caminho_imagem_cabecalho, 'rb') as f_img:
            dados_imagem_cabecalho = f_img.read()
    except FileNotFoundError:
        logging.warning(f"AVISO: Imagem '{caminho_imagem_cabecalho}' não encontrada.")

    for perfil in perfis_de_usuario:
        email_destinatario = perfil.get("email")
        # Agora pegamos termos de todas as configurações de lingua
        configs = perfil.get("search_configs", [])
        termos_exibicao_usuario = perfil.get("keywords_for_display", []) # Categorias originais para exibir no email

        if not email_destinatario: continue

        logging.info(f"Processando e-mail para: {email_destinatario}")

        eventos_para_email_dict = {}

        # Itera sobre todas as linguas que o usuário pediu
        for cfg in configs:
            lang = cfg['lang_code']
            query = cfg['query_string']
            termos_busca = re.findall(r'"(.*?)"', query)

            for termo in termos_busca:
                # Reconstrói a chave usada no cache filtrado
                chave_cache = f"{termo}|{lang}"
                eventos_do_termo = cache_filtrado.get(chave_cache, [])

                for evento in eventos_do_termo:
                    link_principal = evento['principal']['link']
                    if link_principal not in links_ja_enviados:
                        eventos_para_email_dict[link_principal] = evento

        eventos_para_email = list(eventos_para_email_dict.values())

        if eventos_para_email:
            logging.info(f"Encontrados {len(eventos_para_email)} novos eventos de notícia para este usuário.")
            data_envio_formatada = time.strftime('%d/%m/%Y')
            termos_pesquisados_str = ", ".join(termos_exibicao_usuario)

            html_noticias = ""
            for evento in eventos_para_email:
                principal = evento['principal']
                outros = evento.get('outros_sites', [])

                publisher_name = principal.get('publisher', {}).get('title', 'Fonte desconhecida')
                titulo_original = principal.get('titulo', 'Sem título')
                resumo = principal.get('resumo', '')
                titulo_limpo = titulo_original.rsplit(f' - {publisher_name}', 1)[0]

                # <<<--- CORREÇÃO 1: Adicionando o resumo e links clicáveis ---<<<
                html_noticias += f"""
                <div class="news-item">
                    <h2><a href="{principal['link']}" target="_blank">{titulo_limpo}</a></h2>
                    <p class="summary">{resumo}</p>
                    <p class="details">Publicado em: {formatar_data_publicacao(principal.get('published date', ''))} por <strong>{publisher_name}</strong></p>"""

                if outros:
                    # Gera a lista de links HTML para os outros publishers
                    links_outros = [
                        f"<a href=\"{site.get('link', '#')}\" target=\"_blank\">{site.get('publisher', {}).get('title', 'Fonte')}</a>"
                        for site in outros
                    ]
                    html_noticias += f"""
                    <p class="details" style="margin-top: 5px;">
                        Também visto em: {", ".join(links_outros)}
                    </p>"""

                html_noticias += "</div>"

            # <<<--- CORREÇÃO 2: Adicionando estilo para a classe .summary ---<<<
            corpo_email_html = f"""
<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>{NOME_BOLETIM}</title><style>
body{{font-family:Arial,Helvetica,sans-serif;margin:0;padding:0;background-color:#f4f4f4}}
.email-container{{width:100%;max-width:680px;margin:20px auto;background-color:#fff;border:1px solid #ddd}}
.header-image{{width:100%;max-height:150px;object-fit:cover}}
.content{{padding:20px}}
.aviso-box{{
    background-color:#e7f3fe; /* Cor de fundo azul claro */
    border-left:5px solid #005a9e; /* Borda esquerda azul escuro */
    padding:15px;
    margin-bottom:25px;
    font-size:14px;
    color:#333;
}}
.aviso-box ul{{
    padding-left:20px;
    margin-top:10px;
    margin-bottom:10px;
}}
.aviso-box li{{
    margin-bottom:5px;
}}
.news-title-section h1{{color:#333;font-size:22px;margin-top:0}}
.news-title-section p{{color:#555;font-size:14px}}
.news-item{{margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}}
.news-item:last-child{{border-bottom:none;margin-bottom:0;padding-bottom:0}}
.news-item h2{{font-size:18px;margin-top:0;margin-bottom:5px}}
.news-item h2 a{{color:#005a9e;text-decoration:none}}
.news-item h2 a:hover{{text-decoration:underline}}
.news-item .summary{{font-size:14px;color:#555555;margin-top:8px;margin-bottom:8px;font-style:italic;line-height:1.5;}}
.news-item .details{{font-size:12px;color:#777}}
.footer{{padding:15px;text-align:center;background-color:#f9f9f9;border-top:1px solid #ddd}}
.footer p{{font-size:12px;color:#888;margin:0}}
</style></head><body><div class="email-container">
"""
            if dados_imagem_cabecalho:
                corpo_email_html += f'<img src="cid:{id_imagem_cabecalho}" class="header-image">'
            else:
                corpo_email_html += f'<div style="background-color:#2c3e50;color:#fff;padding:20px;text-align:center;font-size:28px;font-weight:bold">{NOME_BOLETIM}</div>'

# Para exibir um aviso pontual no boletim, insira um bloco como o exemplo abaixo
# logo após a abertura da <div class="content"> (o estilo .aviso-box já existe no CSS):
#
# <div class="aviso-box">
#   <p><strong>AVISO:</strong> texto do comunicado.</p>
# </div>

            corpo_email_html += f"""
<div class="content">
<div class="news-title-section"><h1>Notícias das últimas {PERIODO}</h1><p><strong>Suas preferências:</strong> {termos_pesquisados_str}</p><p>Para alterar suas preferências clique <a href="{LINK_PREFERENCIAS}" target="_blank">aqui</a>.</p></div><hr style="border:0;border-top:1px solid #eee;margin:20px 0">
{html_noticias}
</div><div class="footer"><p style="font-size:12px;color:#888;margin:0;"><img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f916/512.gif" style="height:16px;width:16px;vertical-align:middle;"> Este é um e-mail automático.</p>"""
            if PALAVRAS_EXCLUIDAS_TITULO:
                corpo_email_html += f"""<p style="font-size:10px;color:#aaa;margin-top:5px"><i>Notícias com os termos a seguir foram filtradas: {', '.join(PALAVRAS_EXCLUIDAS_TITULO)}.</i></p>"""
            corpo_email_html += """</div></div></body></html>"""

            assunto_email = f"AUTOMÁTICO | {NOME_BOLETIM} ({data_envio_formatada})"

            sucesso_envio = enviar_email_graph(
                access_token,
                [email_destinatario],
                assunto_email,
                corpo_email_html,
                EMAIL_REMETENTE,
                imagem_header_data=dados_imagem_cabecalho,
                imagem_header_cid=id_imagem_cabecalho
            )

            if sucesso_envio:
                for evento in eventos_para_email:
                    salvar_link_enviado(ARQUIVO_LINKS_ENVIADOS, evento['principal']['link'])
        else:
            logging.info("Nenhum evento de notícia novo e relevante encontrado para este usuário.")

    hora_fim = datetime.now()
    logging.info(f"Fim da execução: {hora_fim.strftime('%d/%m/%Y %H:%M:%S')}")
    logging.info(f"Tempo total de execução: {hora_fim - hora_inicio}")

    logging.info("\n--- PROCESSO COMPLETO FINALIZADO ---")
