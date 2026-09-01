"""Mede a qualidade da triagem contra um gabarito fixo.

    python avaliacao/avaliar_triagem.py <rotulo-da-rodada>

Roda `pipeline.triagem.triar()` sobre `avaliacao/amostra_triagem.json` — 87
manchetes reais, estratificadas por tópico — e compara o resultado com
`avaliacao/gabarito_triagem.json`. Serve para ajustar os prompts de
`llm/prompts.py` medindo o efeito em vez de julgar no olho: mude uma regra,
rode de novo com outro rótulo e compare precisão, recall e a lista de erros.

Duas ressalvas de método:
 - o modelo não é determinístico. A variação entre duas rodadas iguais é de
   cerca de um item, então diferença de um item só não é melhoria;
 - se um lote falhar (rate limit, por exemplo), a triagem aprova o lote inteiro
   por segurança e a rodada fica contaminada. O script avisa quando isso ocorre.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import triagem  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


class _ContadorDeFalhas(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.falhas = []

    def emit(self, registro):
        self.falhas.append(registro.getMessage())


def main():
    rotulo = sys.argv[1] if len(sys.argv) > 1 else "rodada"
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    contador = _ContadorDeFalhas()
    logging.getLogger().addHandler(contador)

    with open(os.path.join(AQUI, "amostra_triagem.json"), encoding="utf-8") as arquivo:
        amostra = json.load(arquivo)
    with open(os.path.join(AQUI, "gabarito_triagem.json"), encoding="utf-8") as arquivo:
        gabarito = json.load(arquivo)["labels"]

    aprovadas = triagem.triar([dict(n) for n in amostra])
    links_aprovados = {n["link"] for n in aprovadas}

    vp = fp = fn = vn = 0
    erros = []
    decisoes = {}
    for indice, noticia in enumerate(amostra):
        esperado = gabarito[str(indice)]
        obtido = 1 if noticia["link"] in links_aprovados else 0
        decisoes[str(indice)] = obtido
        if esperado and obtido:
            vp += 1
        elif esperado:
            fn += 1
            erros.append(("FN (perdeu)", indice, noticia))
        elif obtido:
            fp += 1
            erros.append(("FP (ruído)", indice, noticia))
        else:
            vn += 1

    precisao = vp / (vp + fp) if vp + fp else 0.0
    recall = vp / (vp + fn) if vp + fn else 0.0
    f1 = 2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0

    print(f"\n===== {rotulo} =====")
    if contador.falhas:
        print(f"ATENÇÃO: {len(contador.falhas)} lote(s) falharam e entraram inteiros no "
              "resultado. Os números abaixo NÃO valem para comparação.")
    print(f"aprovadas pela IA: {vp + fp}/{len(amostra)}  (gabarito: {vp + fn})")
    print(f"VP {vp}  FP {fp}  FN {fn}  VN {vn}")
    print(f"precisão {precisao:.0%}  recall {recall:.0%}  F1 {f1:.2f}  "
          f"acurácia {(vp + vn) / len(amostra):.0%}")
    print("\n--- erros ---")
    for tipo, indice, noticia in sorted(erros):
        print(f"{tipo} [{indice:02d}] ({noticia['topicos'][0]}) {noticia['titulo'][:95]}")

    destino = os.path.join(AQUI, "resultados")
    os.makedirs(destino, exist_ok=True)
    caminho = os.path.join(destino, f"{rotulo}.json")
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump({"rotulo": rotulo, "lotes_falhos": len(contador.falhas),
                   "metricas": {"vp": vp, "fp": fp, "fn": fn, "vn": vn, "precisao": precisao,
                                "recall": recall, "f1": f1},
                   "decisoes": decisoes}, arquivo, ensure_ascii=False, indent=1)
    print(f"\ngravado em {os.path.relpath(caminho)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
