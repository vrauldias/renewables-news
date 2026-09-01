"""Regenera a amostra de avaliação a partir de um cache_bruto.json.

    python avaliacao/montar_amostra.py

Sorteia, com semente fixa, uma amostra estratificada por tópico e a grava em
`avaliacao/amostra_triagem.json`, imprimindo a lista numerada para rotulagem.
Só é preciso rodar isto para trocar a amostra por uma mais recente — trocá-la
invalida o gabarito, que precisa ser rotulado de novo à mão.
"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TOTAL = 80
SEMENTE = 42

with open(config.ARQUIVO_CACHE_BRUTO, encoding="utf-8") as arquivo:
    pool = json.load(arquivo)

por_topico = collections.defaultdict(list)
for indice, noticia in enumerate(pool):
    por_topico[(noticia.get("topicos") or ["(sem)"])[0]].append(indice)

sorteio = random.Random(SEMENTE)
escolhidos = []
for _, indices in sorted(por_topico.items(), key=lambda item: -len(item[1])):
    cota = max(2, round(len(indices) / len(pool) * TOTAL))
    escolhidos += sorteio.sample(indices, min(cota, len(indices)))
escolhidos.sort()

amostra = [dict(pool[i], _idx=i) for i in escolhidos]
destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amostra_triagem.json")
with open(destino, "w", encoding="utf-8") as arquivo:
    json.dump(amostra, arquivo, ensure_ascii=False, indent=1)

print(f"amostra: {len(amostra)} notícias\n")
for indice, noticia in enumerate(amostra):
    print(f"[{indice:02d}] ({noticia['topicos'][0]} | {noticia['idioma']}) {noticia['titulo']}")
