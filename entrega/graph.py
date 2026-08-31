"""Autenticação MSAL e envio de e-mail pelo Microsoft Graph."""
import base64
import json
import logging
import os

import msal
import requests

import config

log = logging.getLogger(__name__)


def ler_chave_privada():
    if not os.path.exists(config.PRIVATE_KEY_FILE_PATH):
        log.error("Chave privada não encontrada em '%s'.", config.PRIVATE_KEY_FILE_PATH)
        return None
    with open(config.PRIVATE_KEY_FILE_PATH, "r", encoding="utf-8") as arquivo:
        return arquivo.read()


def obter_token(escopo=None):
    chave = ler_chave_privada()
    if not chave:
        return None

    aplicacao = msal.ConfidentialClientApplication(
        client_id=config.CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.TENANT_ID}",
        client_credential={"private_key": chave, "thumbprint": config.CERT_THUMBPRINT},
    )
    resultado = aplicacao.acquire_token_for_client(
        scopes=escopo or ["https://graph.microsoft.com/.default"]
    )
    if "access_token" in resultado:
        return resultado["access_token"]

    log.error("Falha ao obter token: %s — %s",
              resultado.get("error"), resultado.get("error_description"))
    return None


def enviar_email(token, destinatarios, assunto, corpo_html,
                 imagem_dados=None, imagem_cid=None):
    url = f"https://graph.microsoft.com/v1.0/users/{config.EMAIL_REMETENTE}/sendMail"
    mensagem = {
        "message": {
            "subject": assunto,
            "body": {"contentType": "HTML", "content": corpo_html},
            "toRecipients": [{"emailAddress": {"address": e}} for e in destinatarios],
        },
        "saveToSentItems": "true",
    }

    if imagem_dados and imagem_cid:
        mensagem["message"]["attachments"] = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "header.png",
            "contentType": "image/png",
            "contentBytes": base64.b64encode(imagem_dados).decode("utf-8"),
            "contentId": imagem_cid,
            "isInline": True,
        }]

    resposta = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(mensagem),
        timeout=30,
    )
    if resposta.status_code == 202:
        log.info("E-mail enviado para: %s", ", ".join(destinatarios))
        return True

    log.error("Erro ao enviar e-mail (%s): %s", resposta.status_code, resposta.text[:400])
    return False
