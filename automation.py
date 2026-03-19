"""
hirings-automation — Worker de automação de chamados de contratação.

Pipeline ETL (Extract→Transform→Load) que monitora filas ITSM no Verdanadesk/GLPI,
extrai dados de chamados via LLM (OpenAI), aplica regras de negócio Dexian e devolve
um template padronizado em inglês como acompanhamento privado.
"""

import logging
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurações e credenciais
# ---------------------------------------------------------------------------
load_dotenv()

_REQUIRED_ENV_VARS: list[str] = [
    "VERDANADESK_URL",
    "USER_TOKEN",
    "APP_TOKEN",
    "OPENAI_API_KEY",
    "CATEGORIA_CONTRATACAO_IDS",
]


def _carregar_configuracao() -> dict[str, str]:
    """Carrega e valida todas as variáveis de ambiente obrigatórias.

    Raises:
        SystemExit: Se qualquer variável obrigatória estiver ausente.
    """
    config: dict[str, str] = {}
    ausentes: list[str] = []

    for var in _REQUIRED_ENV_VARS:
        valor = os.getenv(var)
        if not valor:
            ausentes.append(var)
        else:
            config[var] = valor

    if ausentes:
        logger.critical(
            "Variáveis de ambiente obrigatórias não definidas: %s",
            ", ".join(ausentes),
        )
        sys.exit(1)

    os.environ["OPENAI_API_KEY"] = config["OPENAI_API_KEY"]
    return config


CONFIG = _carregar_configuracao()

VERDANADESK_URL: str = CONFIG["VERDANADESK_URL"].strip()
USER_TOKEN: str = CONFIG["USER_TOKEN"].strip()
APP_TOKEN: str = CONFIG["APP_TOKEN"].strip()
CATEGORIA_CONTRATACAO_IDS: list[str] = [
    cat_id.strip() for cat_id in CONFIG["CATEGORIA_CONTRATACAO_IDS"].split(",")
]

HTTP_TIMEOUT: int = 30  # segundos

# ---------------------------------------------------------------------------
# Contrato de dados (Pydantic)
# ---------------------------------------------------------------------------


class DadosColaborador(BaseModel):
    """Esquema estrito de saída esperado pelo LLM para cada chamado de contratação."""

    nome_completo: str
    is_pj: bool = Field(
        description=(
            "True se o texto mencionar CNPJ, 'Substituição: Não' "
            "associado a consultoria externa, ou for cooperado"
        )
    )
    data_inicio_dd_mm_yyyy: str
    cargo_ingles: str = Field(
        description="O cargo da pessoa, traduzido para o inglês corporativo (ex: DevOps PL Analyst)"
    )
    centro_custo: str
    cidade_escritorio: str
    telefone: str
    gestor_nome: str
    fornecedor_equipamento: str = Field(description="DEXIAN ou CLIENTE")


# ---------------------------------------------------------------------------
# Motor de regras de negócio
# ---------------------------------------------------------------------------


class GeradorDeChamado:
    """Consome um ``DadosColaborador`` e produz o template de e-mail padronizado."""

    def __init__(self, dados: DadosColaborador) -> None:
        self.dados = dados

    @staticmethod
    def remover_acentos(texto: str) -> str:
        """Remove diacríticos convertendo para a representação ASCII mais próxima."""
        return unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("utf-8")

    def extrair_nomes(self) -> tuple[str, str, str]:
        """Retorna ``(primeiro_nome, ultimo_sobrenome, nome_formatado)``."""
        partes = self.remover_acentos(self.dados.nome_completo).split()
        primeiro_nome = partes[0]
        ultimo_sobrenome = partes[-1]
        nome_formatado = f"{primeiro_nome}.{ultimo_sobrenome}".lower()
        return primeiro_nome, ultimo_sobrenome, nome_formatado

    def formatar_telefone(self) -> str:
        """Normaliza o telefone para o padrão internacional ``+55 DDNNNNNNNNN``."""
        numeros = re.sub(r"\D", "", self.dados.telefone)
        if len(numeros) >= 11:
            numeros = numeros[-11:]
        return f"+55 {numeros[:2]}{numeros[2:]}" if numeros else "Não informado"

    def formatar_data_americana(self) -> str:
        """Converte ``DD-MM-YYYY`` para ``MM/DD/YY``."""
        try:
            return datetime.strptime(self.dados.data_inicio_dd_mm_yyyy, "%d-%m-%Y").strftime(
                "%m/%d/%y"
            )
        except ValueError:
            logger.warning(
                "Formato de data inesperado: '%s'. Valor original mantido.",
                self.dados.data_inicio_dd_mm_yyyy,
            )
            return self.dados.data_inicio_dd_mm_yyyy

    def formatar_gestor(self) -> str:
        """Formata o nome do gestor para o padrão ``nome.sobrenome``."""
        partes = self.remover_acentos(self.dados.gestor_nome).split()
        return f"{partes[0].lower()}.{partes[-1].lower()}" if len(partes) >= 2 else partes[0].lower()

    def gerar_template(self) -> str:
        """Monta e retorna o template de solicitação de conta em inglês."""
        primeiro, ultimo, nome_formatado = self.extrair_nomes()

        email = (
            f"{nome_formatado}-ext@dexian.com" if self.dados.is_pj else f"{nome_formatado}@dexian.com"
        )
        distribution_list = (
            "Distribution/Brazil"
            if self.dados.is_pj
            else "Distribution/Brazil Distribution Groups/todos-brasil"
        )

        if self.dados.fornecedor_equipamento.upper() == "DEXIAN":
            licenca = "Microsoft F3"
            rbac_group = "RBAC-APPS-ENTRA-VERDANADESK-BR"
            dexian_laptop = "Y"
        else:
            licenca = "Microsoft Kiosk"
            rbac_group = "RBAC-APPS-ENTRA-VERDANADESK-CLOUD-USER"
            dexian_laptop = "N"

        return (
            f"Hello! Good day!\n"
            f"Please, create an e-mail account for:\n"
            f"\n"
            f"Name: {self.remover_acentos(self.dados.nome_completo)}\n"
            f"Display name: {ultimo}, {primeiro}\n"
            f"First name: {primeiro}\n"
            f"Last name: {ultimo}\n"
            f"Profile: {self.dados.cargo_ingles}\n"
            f"Office: {self.dados.cidade_escritorio}\n"
            f"e-mail: {email}\n"
            f"Distribution Lists: {distribution_list}\n"
            f"OU = South America / Brazil / Brasil-Consultants\n"
            f"Description: Brazil External Consultant\n"
            f"\n"
            f"{rbac_group}\n"
            f"\n"
            f"Department: {self.dados.centro_custo}\n"
            f"Mobile Phone: {self.formatar_telefone()}\n"
            f"License: {licenca}\n"
            f"Dexian Laptop: {dexian_laptop}\n"
            f"Reporting Manager: {self.formatar_gestor()}\n"
            f"Employee ID: Info pending – will be added later.\n"
            f"Employee hire date: {self.formatar_data_americana()}\n"
            f"\n"
            f'Please, set the option "User must change the password at next logon" to TRUE … it is very important!\n'
            f"Thank you very much!"
        )


# ---------------------------------------------------------------------------
# Integração Verdanadesk (GLPI API)
# ---------------------------------------------------------------------------


class VerdanadeskAutomator:
    """Orquestra autenticação, polling de chamados e invocação do pipeline de IA."""

    def __init__(self) -> None:
        self.session_token: str = self._iniciar_sessao()
        self._atualizar_headers()
        self.extrator_chain = self._criar_extrator_chain()

    # --- Sessão & headers ---------------------------------------------------

    def _iniciar_sessao(self) -> str:
            """Autentica na API do Verdanadesk e retorna o ``session_token``."""
            url = f"{VERDANADESK_URL}/initSession"
            headers = {
                "App-Token": APP_TOKEN, 
                "Authorization": f"user_token {USER_TOKEN}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            
            # --- BLOCO DE DIAGNÓSTICO PROFUNDO ---
            if response.status_code != 200:
                logger.critical("Falha na autenticação! Código: %s | Resposta do Servidor: %s", 
                                response.status_code, response.text)
                response.raise_for_status()
            # ------------------------------------------

            token: Optional[str] = response.json().get("session_token")
            if not token:
                raise RuntimeError("API não retornou session_token na resposta de initSession.")
            logger.info("Sessão iniciada com sucesso no Verdanadesk.")
            return token

    def _atualizar_headers(self) -> None:
        """Reconstrói os headers padrão com o session_token atual."""
        self.headers: dict[str, str] = {
            "App-Token": APP_TOKEN,
            "Session-Token": self.session_token,
            "Content-Type": "application/json",
        }

    def _renovar_sessao(self) -> None:
        """Renova o session_token e atualiza os headers."""
        logger.warning("Renovando sessão no Verdanadesk...")
        self.session_token = self._iniciar_sessao()
        self._atualizar_headers()

    # --- Pipeline de IA -----------------------------------------------------

    @staticmethod
    def _criar_extrator_chain():
        """Constrói a chain LangChain (Prompt → LLM → Structured Output)."""
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        return ChatPromptTemplate.from_messages([
            ("system", "Extraia os dados do chamado de contratação de TI seguindo estritamente o esquema JSON."),
            ("human", "{texto}"),
        ]) | llm.with_structured_output(DadosColaborador)

    # --- Busca de chamados --------------------------------------------------

    def buscar_novos_chamados(self) -> list[dict]:
        """Consulta chamados com status *Novo* nas categorias configuradas."""
        url = f"{VERDANADESK_URL}/search/Ticket"
        chamados_encontrados: list[dict] = []

        for cat_id in CATEGORIA_CONTRATACAO_IDS:
            params = {
                "criteria[0][field]": 7,
                "criteria[0][searchtype]": "equals",
                "criteria[0][value]": cat_id,
                "criteria[1][link]": "AND",
                "criteria[1][field]": 12,
                "criteria[1][searchtype]": "equals",
                "criteria[1][value]": 1,
            }
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=HTTP_TIMEOUT)
                response.raise_for_status()
                dados = response.json().get("data", [])
                chamados_encontrados.extend(dados)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    self._renovar_sessao()
                    return self.buscar_novos_chamados()
                logger.error("Erro HTTP ao buscar chamados (categoria %s): %s", cat_id, exc)
            except requests.exceptions.RequestException as exc:
                logger.error("Erro de rede ao buscar chamados (categoria %s): %s", cat_id, exc)

        return chamados_encontrados

    # --- Processamento individual -------------------------------------------

    def processar_chamado(self, ticket_id: int) -> None:
        """Executa o pipeline completo (Extract → Transform → Load) para um ticket."""
        # 1. Extract — leitura do conteúdo bruto do chamado
        try:
            response = requests.get(
                f"{VERDANADESK_URL}/Ticket/{ticket_id}",
                headers=self.headers,
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error("Falha ao obter conteúdo do Ticket #%s: %s", ticket_id, exc)
            return

        texto: str = response.json().get("content", "")
        if not texto:
            logger.warning("Ticket #%s sem conteúdo. Ignorado.", ticket_id)
            return

        try:
            # 2. Transform — extração via LLM + aplicação de regras de negócio
            dados_estruturados: DadosColaborador = self.extrator_chain.invoke({"texto": texto})
            template_final: str = GeradorDeChamado(dados_estruturados).gerar_template()

            # 3. Load — acompanhamento privado + atualização de status
            payload = {
                "input": {
                    "items_id": ticket_id,
                    "itemtype": "Ticket",
                    "content": template_final,
                    "is_private": 1,
                }
            }
            resp_followup = requests.post(
                f"{VERDANADESK_URL}/Ticket/{ticket_id}/ITILFollowup",
                headers=self.headers,
                json=payload,
                timeout=HTTP_TIMEOUT,
            )
            resp_followup.raise_for_status()

            resp_status = requests.put(
                f"{VERDANADESK_URL}/Ticket/{ticket_id}",
                headers=self.headers,
                json={"input": {"id": ticket_id, "status": 2}},
                timeout=HTTP_TIMEOUT,
            )
            resp_status.raise_for_status()

            logger.info("Ticket #%s processado e atualizado com sucesso.", ticket_id)

        except Exception as exc:
            logger.error("Erro ao processar Ticket #%s: %s", ticket_id, exc)


# ---------------------------------------------------------------------------
# Loop de execução (Polling Worker)
# ---------------------------------------------------------------------------

INTERVALO_POLLING: int = 10


def main() -> None:
    """Ponto de entrada do worker. Executa polling contínuo das filas de chamados."""
    logger.info(
        "Worker iniciado. Polling a cada %d segundos (%d min).",
        INTERVALO_POLLING,
        INTERVALO_POLLING // 60,
    )
    automator = VerdanadeskAutomator()

    while True:
        try:
            logger.info("Buscando novos chamados...")
            chamados = automator.buscar_novos_chamados()
            if chamados:
                logger.info("%d chamado(s) novo(s) encontrado(s).", len(chamados))
            for chamado in chamados:
                ticket_id = chamado.get("2") or chamado.get("id")
                if ticket_id:
                    automator.processar_chamado(ticket_id)
                else:
                    logger.error("Não foi possível extrair o ID do chamado. Retorno bruto: %s", chamado)
        except requests.exceptions.RequestException as exc:
            logger.error("Erro de rede no ciclo de polling: %s", exc)
        except Exception as exc:
            logger.critical("Erro inesperado no ciclo de polling: %s", exc, exc_info=True)

        time.sleep(INTERVALO_POLLING)


if __name__ == "__main__":
    main()