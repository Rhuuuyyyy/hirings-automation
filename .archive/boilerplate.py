"""
Boilerplate Universal para Bots GLPI.

Este arquivo atua como um template estrutural para o desenvolvimento de
novas automacoes ETL (Extract, Transform, Load) integradas ao GLPI ITSM.
Ele isola a infraestrutura de rede e autenticacao, permitindo que o 
desenvolvedor foque exclusivamente na definicao do contrato de dados e 
na logica de negocio.
"""

import logging
import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

# Dependencias de IA / Extracao (Atualizado para o ecossistema Google Gemini)
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

# ============================================================================
# --- BLOCO 1: CONFIGURACAO E INFRAESTRUTURA INICIAL ---
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("GLPI_BotTemplate")

HTTP_TIMEOUT: int = 30  # Timeout global para evitar travamento de threads


def carregar_configuracoes() -> dict[str, str]:
    """
    Carrega e valida todas as variaveis de ambiente obrigatorias.
    Executa a validacao no momento da inicializacao (Fail-Fast).
    """
    load_dotenv()
    
    config = {}
    vars_obrigatorias = ["GLPI_URL", "GLPI_APP_TOKEN", "GLPI_USER_TOKEN", "GOOGLE_API_KEY"]
    vars_ausentes = []

    for var in vars_obrigatorias:
        valor = os.getenv(var)
        if not valor:
            vars_ausentes.append(var)
        else:
            config[var] = valor.rstrip("/") if var == "GLPI_URL" else valor

    if vars_ausentes:
        logger.critical(
            "Falha critica: Variaveis de ambiente obrigatorias nao encontradas: %s",
            ", ".join(vars_ausentes)
        )
        sys.exit(1)

    config["POLLING_INTERVAL"] = os.getenv("POLLING_INTERVAL", "60")
    return config


# ============================================================================
# --- BLOCO 2: CONTRATO DE DADOS E LLM (MODIFIQUE AQUI) ---
# ============================================================================

class DadosExtraidosTemplate(BaseModel):
    """
    [TODO]: INSIRA SUA LOGICA DE EXTRACAO AQUI.
    Defina os campos estritos que o LLM deve extrair do texto do chamado.
    Utilize o atributo 'description' do Field para instruir a IA.
    """
    categoria_identificada: str = Field(
        description="A categoria do problema relatado pelo usuario."
    )
    urgencia_sugerida: int | None = Field(
        default=None, 
        description="Nivel de urgencia de 1 a 5, se detectado explicitamente."
    )
    resumo_problema: str = Field(
        description="Um resumo de 1 linha do problema para adicionar ao acompanhamento."
    )


SYSTEM_PROMPT = """
Voce e um assistente de triagem de TI (ITSM) focado e analitico.
Analise o conteudo do chamado a seguir e extraia as informacoes essenciais
obedecendo estritamente a estrutura de dados solicitada.

Conteudo do Chamado:
{conteudo_chamado}
"""


# ============================================================================
# --- BLOCO 3: REGRA DE NEGOCIO (MODIFIQUE AQUI) ---
# ============================================================================

class ProcessadorDeChamado:
    """
    Classe de Dominio responsavel por aplicar as regras de negocio 
    especificas desta automacao apos a extracao dos dados.
    """
    def __init__(self, glpi_client: 'ClienteGLPI') -> None:
        self.glpi = glpi_client
        self.extrator = self._criar_extrator_chain()

    @staticmethod
    def _criar_extrator_chain() -> Any:
        """Configura e retorna o pipeline do LangChain para extracao estruturada via Gemini."""
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)
        prompt = ChatPromptTemplate.from_template(SYSTEM_PROMPT)
        return prompt | llm.with_structured_output(DadosExtraidosTemplate)

    def processar(self, chamado: dict[str, Any]) -> None:
        """
        [TODO]: INSIRA SUA LOGICA DE TRANSFORMACAO AQUI.
        Metodo orquestrador que une os dados extraidos com as acoes na API.
        """
        ticket_id = chamado.get("id")
        conteudo_bruto = chamado.get("content", "")
        
        if not ticket_id or not conteudo_bruto:
            logger.warning("Chamado invalido ou sem conteudo recebido. Ignorando.")
            return

        logger.info("Iniciando processamento do chamado #%s", ticket_id)

        try:
            # 1. Extracao
            logger.debug("Extraindo dados estruturados via LLM...")
            dados: DadosExtraidosTemplate = self.extrator.invoke({"conteudo_chamado": conteudo_bruto})
            
            # 2. Avaliacao de Regras
            if dados.categoria_identificada.lower() == "ignorar":
                logger.info("Chamado #%s classificado para ser ignorado.", ticket_id)
                return

            # 3. Carga (Load) / Acoes
            mensagem = f"Analise IA Concluida. Resumo: {dados.resumo_problema}"
            self.glpi.adicionar_acompanhamento(ticket_id=ticket_id, conteudo=mensagem, privado=True)
            self.glpi.atualizar_status(ticket_id=ticket_id, novo_status=2)
            
            logger.info("Chamado #%s processado e finalizado com sucesso.", ticket_id)

        except Exception as exc:
            logger.error("Falha na regra de negocio do chamado #%s: %s", ticket_id, exc, exc_info=True)


# ============================================================================
# --- BLOCO 4: CORE DO GLPI (NAO MODIFIQUE) ---
# ============================================================================

class ClienteGLPI:
    """
    Cliente REST robusto para comunicacao com o GLPI.
    Gerencia automaticamente sessoes, tokens, cabecalhos e retentativas em caso de 401.
    """
    def __init__(self, base_url: str, app_token: str, user_token: str) -> None:
        self.base_url = base_url
        self.app_token = app_token
        self.user_token = user_token
        self.session_token: str | None = None
        
        self.session = requests.Session()
        self._iniciar_sessao()

    def _atualizar_headers(self) -> None:
        """Garante a higienizacao e injecao dos cabecalhos corretos."""
        self.session.headers.clear()
        self.session.headers.update({
            "App-Token": self.app_token,
            "Content-Type": "application/json"
        })
        if self.session_token:
            self.session.headers.update({"Session-Token": self.session_token})

    def _iniciar_sessao(self) -> None:
        """Executa a autenticacao primaria via User-Token."""
        url = f"{self.base_url}/apirest.php/initSession"
        self._atualizar_headers()
        
        # O User-Token so e enviado no header de Authorization durante o initSession
        headers_auth = {"Authorization": f"user_token {self.user_token}"}
        
        try:
            response = self.session.get(url, headers=headers_auth, timeout=HTTP_TIMEOUT)
            
            if not response.ok:
                logger.error("Falha no login. Status: %s | Resposta: %s", response.status_code, response.text)
                
            response.raise_for_status()
            
            self.session_token = response.json().get("session_token")
            self._atualizar_headers()
            logger.info("Sessao autenticada com o GLPI estabelecida com sucesso.")
            
        except requests.exceptions.RequestException as exc:
            logger.critical("Erro critico ao contatar o endpoint de autenticacao: %s", exc)
            sys.exit(1)

    def _renovar_sessao(self) -> None:
        """Invalida o token atual e forca uma nova autenticacao."""
        logger.warning("Token de sessao expirado ou invalido. Iniciando ciclo de renovacao...")
        self.session_token = None
        self._iniciar_sessao()

    def _fazer_requisicao(self, metodo: str, endpoint: str, **kwargs) -> requests.Response:
        """Wrapper resiliente que trata expiracao de sessao (401/403) automaticamente."""
        url = f"{self.base_url}/apirest.php/{endpoint}"
        kwargs.setdefault("timeout", HTTP_TIMEOUT)
        
        response = self.session.request(metodo, url, **kwargs)
        
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self.session.request(metodo, url, **kwargs)
            
        if not response.ok:
            logger.error("Requisicao falhou [%s %s]. Status: %s | Corpo: %s", 
                         metodo, endpoint, response.status_code, response.text)
            
        response.raise_for_status()
        return response

    def buscar_chamados_pendentes(self) -> list[dict[str, Any]]:
        """
        Retorna a lista de chamados que atendem aos criterios da fila de trabalho.
        Por padrao, busca chamados no status 1 (Novo). Ajuste os criterios conforme necessario.
        """
        endpoint = "search/Ticket?criteria[0][field]=12&criteria[0][searchtype]=equals&criteria[0][value]=1"
        try:
            response = self._fazer_requisicao("GET", endpoint)
            dados = response.json()
            return dados.get("data", [])
        except requests.exceptions.RequestException as exc:
            logger.error("Falha na varredura da fila de chamados: %s", exc)
            return []

    def adicionar_acompanhamento(self, ticket_id: int, conteudo: str, privado: bool = True) -> bool:
        """Injeta uma anotacao (follow-up) no chamado especificado."""
        endpoint = f"Ticket/{ticket_id}/ITILFollowup"
        payload = {
            "input": {
                "items_id": ticket_id,
                "itemtype": "Ticket",
                "content": conteudo,
                "is_private": 1 if privado else 0
            }
        }
        try:
            self._fazer_requisicao("POST", endpoint, json=payload)
            logger.debug("Acompanhamento gravado no ticket #%s.", ticket_id)
            return True
        except requests.exceptions.RequestException as exc:
            logger.error("Falha ao injetar acompanhamento no ticket #%s: %s", ticket_id, exc)
            return False

    def atualizar_status(self, ticket_id: int, novo_status: int) -> bool:
        """Muta o estado do chamado (ex: 2 = Em Atendimento, 5 = Resolvido)."""
        endpoint = f"Ticket/{ticket_id}"
        payload = {
            "input": {
                "id": ticket_id,
                "status": novo_status
            }
        }
        try:
            self._fazer_requisicao("PUT", endpoint, json=payload)
            logger.info("Status do ticket #%s mutado para o estado %s.", ticket_id, novo_status)
            return True
        except requests.exceptions.RequestException as exc:
            logger.error("Falha ao mutar status do ticket #%s: %s", ticket_id, exc)
            return False


# ============================================================================
# --- BLOCO 5: WORKER POLLING (ENTRYPOINT) ---
# ============================================================================

def main() -> None:
    """Ponto de entrada do Worker. Executa o laco de repeticao infinito."""
    config = carregar_configuracoes()
    polling_interval = int(config["POLLING_INTERVAL"])
    
    logger.info("Inicializando Worker GLPI com ciclo de varredura de %s segundos.", polling_interval)
    
    glpi_client = ClienteGLPI(
        base_url=config["GLPI_URL"],
        app_token=config["GLPI_APP_TOKEN"],
        user_token=config["GLPI_USER_TOKEN"]
    )
    
    processador = ProcessadorDeChamado(glpi_client=glpi_client)

    while True:
        try:
            chamados_pendentes = glpi_client.buscar_chamados_pendentes()
            
            if chamados_pendentes:
                logger.info("Fila contem %d chamado(s) aguardando processamento.", len(chamados_pendentes))
                for chamado in chamados_pendentes:
                    processador.processar(chamado)
            else:
                logger.debug("Fila de trabalho vazia.")

        except requests.exceptions.RequestException as exc:
            logger.error("Anomalia de rede durante o ciclo de varredura: %s", exc)
        except Exception as exc:
            logger.critical("Excecao nao tratada no laco principal: %s", exc, exc_info=True)
            
        time.sleep(polling_interval)


if __name__ == "__main__":
    main()