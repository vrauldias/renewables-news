import os
import json
import logging
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional

import msal
import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed

# --- 1. CONFIGURAÇÕES (definidas via variáveis de ambiente, ver .env.example) ---
load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CERT_THUMBPRINT = os.getenv("CERT_THUMBPRINT")
PRIVATE_KEY_FILE_PATH = os.getenv("PRIVATE_KEY_FILE_PATH", "private_key.pem")

SHAREPOINT_SITE_URL = os.getenv("SHAREPOINT_SITE_URL")
SHAREPOINT_LIST_NAME = os.getenv("SHAREPOINT_LIST_NAME")

# Arquivos de mapeamento
LANGUAGES_MAPPING_FILE = "languages-to-gnews.txt"
BASE_KEYWORD_FILE = "keywords-to-gnews.txt" # Padrão (pt-419)
OUTPUT_JSON_FILE = "preferencias.json"

# --- 2. CLASSE DE OPERAÇÕES DO SHAREPOINT (Via REST API Pura) ---
class SharePointOperations:
    """Manipula operações do SharePoint usando MSAL + Requests."""

    def __init__(self, site_url: str, tenant_id: str, client_id: str, cert_thumb: str, private_key: str):
        self.site_url = site_url.rstrip("/")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.scope = [f"{self._get_domain(site_url)}/.default"]
        self.cert_thum = cert_thumb
        self.private_key = private_key

        self.token = self._get_token()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }

    def _get_domain(self, site_url: str) -> str:
        parsed = urllib.parse.urlparse(site_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_token(self) -> str:
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cert = {
            "private_key": self.private_key,
            "thumbprint": self.cert_thum
        }
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=cert
        )
        result = app.acquire_token_for_client(scopes=self.scope)
        if "access_token" not in result:
            raise Exception(f"Failed to acquire token: {result.get('error_description')}")
        return result["access_token"]

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def get_list_items(
        self,
        list_title: str,
        select_fields: Optional[List[str]] = None,
        expand_fields: Optional[List[str]] = None,
        top: int = 500,
    ) -> List[Dict[str, Any]]:
        """Busca itens da lista via REST API."""
        try:
            select_str = f"$select={','.join(select_fields)}" if select_fields else ""
            expand_str = f"&$expand={','.join(expand_fields)}" if expand_fields else ""
            list_title_encoded = urllib.parse.quote(list_title)
            url = f"{self.site_url}/_api/web/lists/getbytitle('{list_title_encoded}')/items?$top={top}&{select_str}{expand_str}"

            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()

            data = resp.json()
            items = data.get("d", {}).get("results", [])
            logging.info(f"Retrieved {len(items)} items from {list_title}")
            return items
        except Exception as e:
            logging.error(f"Error retrieving items from {list_title}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"SharePoint Response: {e.response.text}")
            raise

# --- 3. FUNÇÕES AUXILIARES ---

def load_simple_mapping(filepath):
    """Carrega arquivos tabulados chave-valor mantendo o Case original."""
    mappings = {}
    if not os.path.exists(filepath):
        print(f"AVISO: Arquivo '{filepath}' não encontrado.")
        return mappings

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        start_idx = 1 if len(lines) > 0 and ("source:" in lines[0] or "SharePoint" in lines[0]) else 0

        for line in lines[start_idx:]:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                # CORREÇÃO: Mantém a chave original (sem .lower())
                mappings[parts[0].strip()] = parts[1].strip()
    return mappings

def load_all_keyword_dictionaries(languages_map):
    dicts_by_lang = {}
    # Carrega o padrão (assumindo pt-419)
    dicts_by_lang['pt-419'] = load_simple_mapping(BASE_KEYWORD_FILE)

    for sp_lang, code in languages_map.items():
        if code == 'pt-419': continue
        filename = f"keywords-to-gnews-{code}.txt"
        if os.path.exists(filename):
            print(f"Carregando dicionário extra: {filename}")
            dicts_by_lang[code] = load_simple_mapping(filename)
        else:
            print(f"AVISO: Dicionário para '{code}' ({filename}) não encontrado. Usando termos em português como fallback.")
            dicts_by_lang[code] = dicts_by_lang['pt-419']
    return dicts_by_lang

def get_latest_preferences(lang_map, keyword_dicts):
    print("Conectando ao SharePoint para buscar preferências...")
    try:
        with open(PRIVATE_KEY_FILE_PATH, "r") as f:
            private_key = f.read()

        sp_ops = SharePointOperations(
            site_url=SHAREPOINT_SITE_URL,
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            cert_thumb=CERT_THUMBPRINT,
            private_key=private_key
        )

        items = sp_ops.get_list_items(
            list_title=SHAREPOINT_LIST_NAME,
            select_fields=["Quais_x0020_", "Author/EMail", "Modified", "EscolherL_x00ed_nguas"],
            expand_fields=["Author"]
        )
        print(f"Encontrados {len(items)} registros na lista.")

        latest_preferences = {}
        for item in items:
            email = item.get('Author', {}).get('EMail')
            modified_str = item.get('Modified')
            if not email or not modified_str: continue

            modified_date = datetime.strptime(modified_str, '%Y-%m-%dT%H:%M:%SZ')

            if email not in latest_preferences or modified_date > latest_preferences[email]['timestamp']:
                cat_data = item.get('Quais_x0020_', {})
                categories = cat_data.get('results', []) if isinstance(cat_data, dict) else []

                lang_data = item.get('EscolherL_x00ed_nguas', {})
                langs = lang_data.get('results', []) if isinstance(lang_data, dict) else []

                if not langs: langs = ["Português"]

                latest_preferences[email] = {
                    'timestamp': modified_date,
                    'categories': categories,
                    'languages': langs
                }

        output_data = []
        for email, data in latest_preferences.items():
            user_prefs = {
                "email": email,
                "keywords_for_display": data['categories'],
                "search_configs": []
            }

            for lang_name in data['languages']:
                gnews_lang_code = lang_map.get(lang_name)
                if not gnews_lang_code: continue

                current_dict = keyword_dicts.get(gnews_lang_code, keyword_dicts.get('pt-419', {}))

                search_terms = []
                for cat in data['categories']:
                    # CORREÇÃO PRINCIPAL: Busca o termo exato (sem .lower()), respeitando o txt
                    term = current_dict.get(cat)
                    if term:
                        search_terms.append(f'"{term}"')
                    else:
                        # Se não achar, usa a categoria como fallback
                        search_terms.append(f'"{cat}"')

                if search_terms:
                    user_prefs["search_configs"].append({
                        "lang_code": gnews_lang_code,
                        "query_string": " OR ".join(search_terms)
                    })

            output_data.append(user_prefs)

        return output_data

    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar dados do SharePoint: {e}")
        return None

# --- 4. LÓGICA PRINCIPAL ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("--- Coletor de Preferências (Multi-língua) ---")

    lang_map = load_simple_mapping(LANGUAGES_MAPPING_FILE)
    keyword_dicts = load_all_keyword_dictionaries(lang_map)

    final_preferences = get_latest_preferences(lang_map, keyword_dicts)

    if final_preferences:
        try:
            with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_preferences, f, indent=4, ensure_ascii=False)
            print(f"\nPreferências salvas em '{OUTPUT_JSON_FILE}'")
        except Exception as e:
            print(f"\nErro ao salvar JSON: {e}")

    print("--- Fim ---")
