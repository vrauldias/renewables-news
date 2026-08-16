import os
import json
import time
import requests
import sys
import logging
import re
import difflib
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# --- 1. CONFIGURAÇÕES ---
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    print("ERRO: Chave GROQ_API_KEY não encontrada no arquivo .env")
    sys.exit(1)

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

MODELO_GROQ = "llama-3.1-8b-instant"
ARQUIVO_CACHE_ENTRADA = "cache_bruto.json"
ARQUIVO_CACHE_SAIDA = "cache_filtrado.json"

# Rate Limit Seguro
INTERVALO_ENTRE_CHAMADAS = 3.0 
LAST_CALL_TIME = 0

PALAVRAS_NEGATIVAS = [
    "futebol", "jogador", "neymar", "messi", "cr7", "flamengo", "corinthians", "palmeiras",
    "bbb", "reality", "novela", "ator", "atriz", "famoso", "celebridade", "show",
    "horóscopo", "signo", "zodíaco", "loteria", "mega-sena", "aposta", "jogo",
    "polícia", "preso", "assalto", "homicídio", "tiroteio", "morto", "traficante", "crime",
    "netflix", "série", "filme", "cinema", "streaming", "spoiler", "resumo da novela"
]

logging.basicConfig(level=logging.INFO, format='%(message)s')

# --- 2. CONTROLE DE FLUXO E VISUALIZAÇÃO ---

def aguardar_rate_limit():
    global LAST_CALL_TIME
    agora = time.time()
    delta = agora - LAST_CALL_TIME
    if delta < INTERVALO_ENTRE_CHAMADAS:
        time.sleep(INTERVALO_ENTRE_CHAMADAS - delta)
    LAST_CALL_TIME = time.time()

def safe_print(texto):
    """
    Imprime texto no console tratando erros de codificação (Windows CP1252).
    Substitui caracteres não suportados em vez de travar o script.
    """
    try:
        print(texto)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding if sys.stdout.encoding else 'utf-8'
        texto_safe = texto.encode(encoding, errors='replace').decode(encoding)
        print(texto_safe)

# --- 3. FUNÇÕES DE REDE ---

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def resolver_url_final(google_news_url: str) -> str | None:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        initial_resp = requests.get(google_news_url, headers=headers, timeout=10, allow_redirects=True)
        
        if "news.google.com" not in initial_resp.url and "google.com" not in initial_resp.url:
            return initial_resp.url

        soup = BeautifulSoup(initial_resp.text, 'html.parser')
        c_wiz_element = soup.select_one('c-wiz[data-p]')
        
        if not c_wiz_element: 
            return google_news_url if initial_resp.status_code == 200 else None

        data_p = c_wiz_element.get('data-p')
        obj = json.loads(data_p.replace('%.@.', '["garturlreq",'))
        payload = {'f.req': json.dumps([[['Fbv4je', json.dumps(obj[:-6] + obj[-2:]), 'null', 'generic']]])}
        
        response = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", 
                               headers={'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'user-agent': 'Mozilla/5.0'}, 
                               data=payload, timeout=10)
        response.raise_for_status()
        data_array = json.loads(response.text.replace(")]}'", ""))
        return json.loads(data_array[0][2])[1]
    except Exception:
        raise 

def extrair_texto_do_url(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/pdf' in content_type or 'image' in content_type: return None
        soup = BeautifulSoup(response.text, 'html.parser')
        for el in soup(["script", "style", "header", "footer", "nav", "aside", "form", "ads", "iframe"]): el.decompose()
        text = ' '.join(t.strip() for t in soup.stripped_strings)
        return text[:2500] if text and len(text) > 300 else None
    except Exception:
        return None

def normalizar_titulo(titulo):
    if not titulo: return ""
    t = titulo.strip()
    t = re.sub(r'\s+', ' ', t)
    m = re.split(r'\s[-|]\s', t)
    if len(m) > 1 and len(m[-1]) <= 40:
        t = ' '.join(m[:-1])
    return t.lower().strip()

# --- 4. FUNÇÕES IA ---

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=30), retry=retry_if_exception_type(Exception))
def chamar_groq(messages, max_tokens=150, temperature=0.1):
    aguardar_rate_limit()
    try:
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=MODELO_GROQ,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        safe_print(f"    -> [Groq] Erro: {e}. Retentando...")
        raise e

def analisar_lote_relevancia(termo, lote_noticias):
    texto_lote = ""
    for i, n in enumerate(lote_noticias):
        titulo_limpo = n.get('title', '').replace('\n', ' ')
        texto_lote += f"ID {i}: {titulo_limpo}\n"

    prompt = f"""
    Atue como um analista de inteligência de mercado em energia.
    Tópico: {termo}
    
    Lista de manchetes:
    {texto_lote}
    
    Identifique quais são RELEVANTES para o setor de energia, biogás, SAF ou combustíveis avançados.
    Critérios: Novos projetos, plantas, investimentos, regulação ou fusões.
    
    Responda APENAS com os números (IDs) das relevantes, separados por vírgula (ex: 0, 2, 5).
    Se nenhuma, responda: NULL.
    """
    
    resp = chamar_groq(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.0
    )
    
    if "NULL" in resp or "null" in resp.lower(): return []
    ids_relevantes = [int(s) for s in re.findall(r'\b\d+\b', resp)]
    return ids_relevantes

def resumir_noticia(titulo, texto, lang_code):
    idioma = "Português"
    if lang_code == 'en': idioma = "Inglês"
    elif lang_code == 'de': idioma = "Alemão"

    prompt = f"""
    Resuma em {idioma} em UMA frase técnica e objetiva de até 30 palavras.
    NÃO use frases introdutórias. Vá direto ao assunto.
    
    Título: {titulo}
    Texto: {texto}
    """
    
    return chamar_groq(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120,
        temperature=0.1
    )

# --- 5. CLUSTERIZAÇÃO HÍBRIDA (GRAFO + IA) ---

def agrupar_noticias_hibrido(lista_noticias, topico):
    if not lista_noticias: return []
    if len(lista_noticias) == 1: return [{'principal': lista_noticias[0], 'outros_sites': []}]

    texto_lote = ""
    for i, n in enumerate(lista_noticias):
        titulo = n['titulo'].replace('\n', ' ')
        resumo_curto = n.get('resumo', '')[:60]
        texto_lote += f"[{i}] {titulo} || {resumo_curto}...\n"

    prompt_agrupamento = f"""
    Analise estas manchetes sobre '{topico}'.
    Agrupe os IDs das notícias que falam sobre o MESMO FATO ou EVENTO.
    
    Retorne uma lista de listas JSON.
    Exemplo: [[0, 2], [1], [3, 4, 5]]
    
    Lista:
    {texto_lote}
    """

    try:
        resp = chamar_groq(
            messages=[{"role": "user", "content": prompt_agrupamento}],
            max_tokens=500,
            temperature=0.0
        )
        
        resp_limpa = resp.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[\[.*\]\]', resp_limpa, re.DOTALL)
        if match: resp_limpa = match.group(0)
            
        grupos_ids = json.loads(resp_limpa)
        
        clusters = []
        ids_ja_agrupados = set()

        for grupo in grupos_ids:
            grupo = [idx for idx in grupo if isinstance(idx, int) and 0 <= idx < len(lista_noticias)]
            if not grupo: continue

            itens_grupo = [lista_noticias[i] for i in grupo]
            itens_grupo.sort(key=lambda x: len(x['titulo']), reverse=True)
            
            principal = itens_grupo[0]
            outros = itens_grupo[1:]
            
            clusters.append({'principal': principal, 'outros_sites': outros})
            ids_ja_agrupados.update(grupo)

        for i, n in enumerate(lista_noticias):
            if i not in ids_ja_agrupados:
                clusters.append({'principal': n, 'outros_sites': []})
        
        return clusters

    except Exception as e:
        safe_print(f"    -> Erro no agrupamento IA: {e}. Usando fallback (difflib).")
        return agrupar_fallback_grafo(lista_noticias)

def agrupar_fallback_grafo(lista_noticias):
    clusters = []
    usados = set()
    norm_titulos = [normalizar_titulo(n['titulo']) for n in lista_noticias]
    
    for i in range(len(lista_noticias)):
        if i in usados: continue
        grupo = [lista_noticias[i]]
        usados.add(i)
        
        for j in range(i + 1, len(lista_noticias)):
            if j in usados: continue
            if difflib.SequenceMatcher(None, norm_titulos[i], norm_titulos[j]).ratio() > 0.5:
                grupo.append(lista_noticias[j])
                usados.add(j)
        
        clusters.append({'principal': grupo[0], 'outros_sites': grupo[1:]})
    return clusters

# --- 6. LÓGICA PRINCIPAL ---
if __name__ == "__main__":
    safe_print("--- INICIANDO FILTRO GROQ (V8.1: SAFE PRINT) ---")
    
    try:
        with open(ARQUIVO_CACHE_ENTRADA, 'r', encoding='utf-8') as f: 
            cache_bruto = json.load(f)
    except FileNotFoundError:
        print(f"ERRO: {ARQUIVO_CACHE_ENTRADA} não encontrado."); exit(1)

    noticias_relevantes_por_chave = {}
    total_aprovado = 0

    safe_print("\n--- ETAPA A: Triagem e Resumo ---")
    
    for chave_composta, noticias in cache_bruto.items():
        termo_exibicao = chave_composta.split('|')[0]
        lang_code = chave_composta.split('|')[1] if '|' in chave_composta else 'pt'
        
        if not noticias: continue
        safe_print(f"\n>> Tópico: '{termo_exibicao}' ({len(noticias)} itens)")
        
        noticias_relevantes_por_chave[chave_composta] = []
        noticias_para_analise = []
        
        for n in noticias:
            if not any(neg in n.get('title', '').lower() for neg in PALAVRAS_NEGATIVAS):
                noticias_para_analise.append(n)

        TAMANHO_LOTE = 30 
        for i in range(0, len(noticias_para_analise), TAMANHO_LOTE):
            lote = noticias_para_analise[i:i + TAMANHO_LOTE]
            
            try:
                safe_print(f"  Triagem: lote de {len(lote)} manchetes...")
                ids_aprovados = analisar_lote_relevancia(termo_exibicao, lote)
            except Exception as e:
                safe_print(f"    -> Erro triagem: {e}")
                continue
            
            for id_rel in ids_aprovados:
                if id_rel >= len(lote): continue
                noticia = lote[id_rel]
                safe_print(f"  [+] Processando: {noticia['title'][:50]}...")
                
                try:
                    url_final = resolver_url_final(noticia['url'])
                    if not url_final: continue
                    texto = extrair_texto_do_url(url_final)
                    
                    if not texto:
                        if noticia.get('description') and len(noticia['description']) > 80:
                            texto = noticia['description']
                        else: continue
                    
                    resumo = resumir_noticia(noticia['title'], texto, lang_code)
                    # Tratamento de aspas no resumo
                    safe_resumo = resumo.strip('"')
                    
                    noticias_relevantes_por_chave[chave_composta].append({
                        'titulo': noticia['title'],
                        'link': url_final,
                        'resumo': safe_resumo,
                        'published date': noticia.get('published date'),
                        'publisher': noticia.get('publisher')
                    })
                    safe_print(f"    -> Resumo OK.")
                    total_aprovado += 1
                except Exception as e:
                    safe_print(f"    -> Erro processamento: {e}")

    safe_print("\n--- ETAPA B: Agrupamento Semântico (IA) ---")
    cache_filtrado_final = {}
    
    for chave, lista in noticias_relevantes_por_chave.items():
        if not lista: continue
        termo_clean = chave.split('|')[0]
        
        clusters = agrupar_noticias_hibrido(lista, termo_clean)
        
        cache_filtrado_final[chave] = clusters
        safe_print(f"  [{termo_clean}] {len(lista)} notícias -> {len(clusters)} grupos.")

    safe_print(f"--- Concluído: {total_aprovado} notícias relevantes.")
    
    with open(ARQUIVO_CACHE_SAIDA, 'w', encoding='utf-8') as f:
        json.dump(cache_filtrado_final, f, indent=4, ensure_ascii=False)
