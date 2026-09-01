"""Camada de provedores de IA.

Um único ponto do projeto sabe qual provedor está em uso. O resto do código
chama `obter_cliente().gerar(...)` e não precisa saber se por trás está Groq,
Gemini, Claude, OpenAI, Ollama etc.

Dois caminhos de código apenas:
  * `anthropic`  -> SDK oficial da Anthropic (`anthropic`);
  * todo o resto -> SDK da OpenAI apontando para a base_url do provedor,
    porque Groq, Gemini, OpenRouter, DeepSeek, Mistral, Azure e Ollama
    expõem endpoints compatíveis com a API da OpenAI.

Para acrescentar um provedor novo compatível com OpenAI, basta uma entrada em
PROVEDORES — nenhuma outra parte do projeto muda.
"""
import os
import sys
import time
import logging

import config

log = logging.getLogger(__name__)

# nome -> (variável da chave, base_url, modelo padrão)
PROVEDORES = {
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "openai": ("OPENAI_API_KEY", None, "gpt-4o-mini"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-chat"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-large-latest"),
    "ollama": (None, None, "llama3.1:8b"),
    "azure-openai": ("AZURE_OPENAI_API_KEY", None, None),
    # Claude usa o SDK oficial da Anthropic, não a base_url acima.
    "anthropic": ("ANTHROPIC_API_KEY", None, "claude-opus-5"),
}

# Modelos Claude alternativos, caso queira trocar capacidade por custo no .env:
#   claude-opus-5 (padrão) | claude-sonnet-5 | claude-haiku-4-5


class ErroLLM(Exception):
    pass


class _ClienteBase:
    """Serializa as chamadas e aplica o intervalo mínimo entre elas."""

    nome = "?"

    def __init__(self):
        self._ultima_chamada = 0.0

    def _respeitar_rate_limit(self):
        intervalo = config.LLM_INTERVALO_ENTRE_CHAMADAS
        espera = intervalo - (time.time() - self._ultima_chamada)
        if espera > 0:
            time.sleep(espera)
        self._ultima_chamada = time.time()

    def gerar(self, sistema, usuario, max_tokens=1024, tarefa="triagem", json_esperado=False):
        """Executa a chamada com retentativa exponencial. Retorna texto puro."""
        ultimo_erro = None
        for tentativa in range(config.LLM_MAX_TENTATIVAS):
            try:
                self._respeitar_rate_limit()
                return self._chamar(sistema, usuario, max_tokens, tarefa, json_esperado)
            except Exception as erro:  # noqa: BLE001 - o tipo varia por SDK
                ultimo_erro = erro
                espera = min(2 ** tentativa, 30)
                log.warning(
                    "[%s] falha na chamada (%s/%s): %s -- nova tentativa em %ss",
                    self.nome, tentativa + 1, config.LLM_MAX_TENTATIVAS, erro, espera,
                )
                time.sleep(espera)
        raise ErroLLM(
            f"{self.nome}: falhou apos {config.LLM_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
        )

    def _chamar(self, sistema, usuario, max_tokens, tarefa, json_esperado):
        raise NotImplementedError


class ClienteCompativelOpenAI(_ClienteBase):
    """Groq, Gemini, OpenAI, OpenRouter, DeepSeek, Mistral, Azure e Ollama."""

    def __init__(self, provedor):
        super().__init__()
        try:
            from openai import OpenAI, AzureOpenAI
        except ImportError:
            sys.exit("ERRO: o pacote 'openai' nao esta instalado. Rode: pip install -r requirements.txt")

        self.nome = provedor
        var_chave, base_url, modelo_padrao = PROVEDORES[provedor]
        self.modelo_padrao = modelo_padrao

        if provedor == "azure-openai":
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
            if not endpoint:
                sys.exit("ERRO: AZURE_OPENAI_ENDPOINT nao definido no .env.")
            self.cliente = AzureOpenAI(
                api_key=_exigir_chave(var_chave, provedor),
                azure_endpoint=endpoint,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip(),
            )
            return

        if provedor == "ollama":
            # Servidor local: aceita qualquer chave, mas o SDK exige uma string.
            chave = "ollama"
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
        else:
            chave = _exigir_chave(var_chave, provedor)

        self.cliente = OpenAI(api_key=chave, base_url=base_url)

    def _chamar(self, sistema, usuario, max_tokens, tarefa, json_esperado):
        parametros = {
            "model": _modelo_da_tarefa(tarefa, self.modelo_padrao),
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        }
        if json_esperado:
            # Suportado por Groq, OpenAI, Gemini, DeepSeek, Mistral e Ollama
            # recente. Se o provedor recusar o parâmetro, repetimos sem ele: o
            # prompt já exige JSON e o parser tolera texto ao redor.
            parametros["response_format"] = {"type": "json_object"}

        resposta = self._criar_tolerando_parametros(parametros)
        return (resposta.choices[0].message.content or "").strip()

    def _criar_tolerando_parametros(self, parametros):
        """Refaz a chamada sem os parâmetros que o provedor específico recusa.

        Os endpoints "compatíveis com OpenAI" divergem em detalhes: alguns não
        aceitam `response_format`, outros exigem `max_completion_tokens` no
        lugar de `max_tokens`, outros recusam `temperature`. Em vez de manter
        uma tabela de exceções por provedor, cada recusa é tratada uma vez.
        """
        for _ in range(3):
            try:
                return self.cliente.chat.completions.create(**parametros)
            except Exception as erro:  # noqa: BLE001
                mensagem = str(erro).lower()
                if "response_format" in mensagem and "response_format" in parametros:
                    parametros.pop("response_format")
                elif "max_tokens" in mensagem and "max_tokens" in parametros:
                    parametros["max_completion_tokens"] = parametros.pop("max_tokens")
                elif "temperature" in mensagem and "temperature" in parametros:
                    parametros.pop("temperature")
                else:
                    raise
        return self.cliente.chat.completions.create(**parametros)


class ClienteAnthropic(_ClienteBase):
    """Claude via SDK oficial da Anthropic."""

    nome = "anthropic"

    def __init__(self):
        super().__init__()
        try:
            import anthropic
        except ImportError:
            sys.exit(
                "ERRO: LLM_PROVIDER=anthropic exige o pacote 'anthropic'. "
                "Rode: pip install anthropic"
            )
        self.modelo_padrao = PROVEDORES["anthropic"][2]
        self.cliente = anthropic.Anthropic(api_key=_exigir_chave("ANTHROPIC_API_KEY", "anthropic"))

    def _chamar(self, sistema, usuario, max_tokens, tarefa, json_esperado):
        # Os modelos Claude atuais rejeitam temperature/top_p (HTTP 400); o
        # controle equivalente é o nível de esforço em output_config.
        resposta = self.cliente.messages.create(
            model=_modelo_da_tarefa(tarefa, self.modelo_padrao),
            max_tokens=max_tokens,
            system=sistema,
            output_config={"effort": _effort_da_tarefa(tarefa)},
            messages=[{"role": "user", "content": usuario}],
        )
        partes = [bloco.text for bloco in resposta.content if bloco.type == "text"]
        return "\n".join(partes).strip()


def _exigir_chave(var_chave, provedor):
    chave = os.getenv(var_chave, "").strip()
    if not chave:
        sys.exit(
            f"ERRO: LLM_PROVIDER={provedor} exige a variavel {var_chave} preenchida no .env."
        )
    return chave


def _modelo_da_tarefa(tarefa, padrao):
    escolhido = {
        "triagem": config.LLM_MODELO_TRIAGEM,
        "agrupamento": config.LLM_MODELO_AGRUPAMENTO,
        "resumo": config.LLM_MODELO_RESUMO,
    }.get(tarefa, "")
    modelo = escolhido or padrao
    if not modelo:
        sys.exit(
            f"ERRO: nenhum modelo definido para a tarefa '{tarefa}'. "
            f"Preencha LLM_MODELO_{tarefa.upper()} no .env."
        )
    return modelo


def _effort_da_tarefa(tarefa):
    return {
        "triagem": config.LLM_EFFORT_TRIAGEM,
        "agrupamento": config.LLM_EFFORT_AGRUPAMENTO,
        "resumo": config.LLM_EFFORT_RESUMO,
    }.get(tarefa, "low")


_cliente_unico = None


def obter_cliente():
    """Devolve (criando na primeira vez) o cliente do provedor configurado."""
    global _cliente_unico
    if _cliente_unico is not None:
        return _cliente_unico

    provedor = config.LLM_PROVIDER
    if provedor not in PROVEDORES:
        sys.exit(
            f"ERRO: LLM_PROVIDER='{provedor}' desconhecido. "
            f"Valores aceitos: {', '.join(sorted(PROVEDORES))}."
        )

    if provedor == "anthropic":
        _cliente_unico = ClienteAnthropic()
    else:
        _cliente_unico = ClienteCompativelOpenAI(provedor)

    log.info("Provedor de IA: %s", provedor)
    return _cliente_unico
