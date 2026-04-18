import os
import time
import logging
import requests
from typing import Optional, Any
from dotenv import load_dotenv

# Dependências de IA / Extração
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# ============================================================================
# --- BLOCO 1: CONFIGURAÇÃO E INFRAESTRUTURA INICIAL ---
# ============================================================================

# Carrega as variáveis de ambiente
load_dotenv()

# Configuração de Logging robusta
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("GLPI_BotTemplate")

# Validação de variáveis críticas
REQUIRED_ENVS = ["GLPI_URL", "GLPI_APP_TOKEN", "GLPI_USER_TOKEN", "OPENAI_API_KEY"]
for env in REQUIRED_ENVS:
    if not os.getenv(env):
        logger.error(f"Variável de ambiente obrigatória não encontrada: {env}")
        exit(1)

GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", 60))


# ============================================================================
# --- BLOCO 2: CONTRATO DE DADOS E LLM (MODIFIQUE AQUI) ---
# ============================================================================

class DadosExtraidosTemplate(BaseModel):
    """
    TODO: INSIRA SUA LÓGICA DE EXTRAÇÃO AQUI
    Altere os campos abaixo para representar exatamente o que você espera que o
    LLM extraia do conteúdo do chamado.
    """
    categoria_identificada: str = Field(description="A categoria do problema relatado pelo usuário.")
    urgencia_sugerida: Optional[int] = Field(None, description="Nível de urgência de 1 a 5, se detectado.")
    resumo_problema: str = Field(description="Um resumo de 1 linha do problema para adicionar ao acompanhamento.")
    # ex: nome_colaborador: str = Field(description="Nome do colaborador que precisa de acesso")


# Prompt Genérico configurável
SYSTEM_PROMPT = """
Você é um assistente de triagem de TI (ITSM). 
Analise o conteúdo do chamado a seguir e extraia as informações essenciais
de acordo com a estrutura de dados solicitada.

Conteúdo do Chamado:
{conteudo_chamado}
"""


# ============================================================================
# --- BLOCO 3: REGRA DE NEGÓCIO (MODIFIQUE AQUI) ---
# ============================================================================

class ProcessadorDeChamado:
    """
    Classe responsável por aplicar as regras de negócio de cada automação específica.
    """
    def __init__(self, glpi_client: 'ClienteGLPI'):
        self.glpi = glpi_client
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0) # Altere o modelo se necessário
        self.extrator = self._criar_extrator_chain()

    def _criar_extrator_chain(self) -> Any:
        """Cria o pipeline do LangChain para extração estruturada."""
        prompt = ChatPromptTemplate.from_template(SYSTEM_PROMPT)
        # Associa o LLM ao Pydantic model (Contrato de Dados)
        extrator_estruturado = self.llm.with_structured_output(DadosExtraidosTemplate)
        return prompt | extrator_estruturado

    def processar(self, chamado: dict) -> None:
        """
        TODO: INSIRA SUA LÓGICA DE TRANSFORMAÇÃO AQUI
        Este método é orquestrador da sua regra de negócio para cada chamado.
        """
        ticket_id = chamado.get("id")
        conteudo_bruto = chamado.get("content", "")
        
        logger.info(f"Processando chamado #{ticket_id}...")

        try:
            # 1. Extração com LLM
            logger.info("Extraindo dados com LLM...")
            dados_extraidos: DadosExtraidosTemplate = self.extrator.invoke({"conteudo_chamado": conteudo_bruto})
            logger.info(f"Dados extraídos: {dados_extraidos.model_dump()}")

            # 2. Avaliação de Regra de Negócio (Exemplo)
            if dados_extraidos.categoria_identificada == "Ignorar":
                logger.info(f"Chamado #{ticket_id} ignorado pela regra de negócio.")
                return

            # 3. Ações no GLPI (Modularizado)
            # Exemplo: Adiciona um acompanhamento privado com os dados extraídos
            mensagem = f"Análise IA Concluída. Resumo: {dados_extraidos.resumo_problema}"
            self.glpi.adicionar_acompanhamento(ticket_id=ticket_id, conteudo=mensagem, privado=True)

            # Exemplo: Atualiza status para 'Em Atendimento' (2)
            self.glpi.atualizar_status(ticket_id=ticket_id, novo_status=2)
            
            logger.info(f"Chamado #{ticket_id} processado com sucesso!")

        except Exception as e:
            logger.error(f"Erro ao processar a regra de negócio do chamado #{ticket_id}: {str(e)}", exc_info=True)


# ============================================================================
# --- BLOCO 4: CORE DO GLPI (NÃO MEXA) ---
# ============================================================================

class ClienteGLPI:
    """
    Engine de comunicação com o GLPI. Resolve autenticação, renovação de sessão e chamadas REST.
    """
    def __init__(self, base_url: str, app_token: str, user_token: str):
        self.base_url = base_url
        self.app_token = app_token
        self.user_token = user_token
        self.session_token: Optional[str] = None
        self.session = requests.Session()
        
        self._iniciar_sessao()

    def _atualizar_headers(self) -> None:
        """Atualiza os cabeçalhos da requisição HTTP."""
        self.session.headers.update({
            "App-Token": self.app_token,
            "Content-Type": "application/json"
        })
        if self.session_token:
            self.session.headers.update({"Session-Token": self.session_token})

    def _iniciar_sessao(self) -> None:
        """Autentica na API do GLPI usando o User-Token."""
        url = f"{self.base_url}/apirest.php/initSession"
        self._atualizar_headers()
        headers_auth = {"Authorization": f"user_token {self.user_token}"}
        
        response = self.session.get(url, headers=headers_auth)
        response.raise_for_status()
        
        self.session_token = response.json().get("session_token")
        self._atualizar_headers()
        logger.info("Sessão do GLPI iniciada com sucesso.")

    def _renovar_sessao(self) -> None:
        """Renova a sessão caso o token tenha expirado."""
        logger.warning("Sessão expirada ou inválida. Tentando renovar...")
        self.session_token = None
        self._iniciar_sessao()

    def _fazer_requisicao(self, metodo: str, endpoint: str, **kwargs) -> requests.Response:
        """Wrapper interno para lidar com 401 e reconexão automática."""
        url = f"{self.base_url}/apirest.php/{endpoint}"
        
        response = self.session.request(metodo, url, **kwargs)
        
        # Se for 401 (Unauthorized), renova a sessão e tenta novamente UMA vez
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self.session.request(metodo, url, **kwargs)
            
        response.raise_for_status()
        return response

    def buscar_chamados_pendentes(self) -> list[dict]:
        """Busca chamados que aguardam triagem (ex: status 1 - Novo)."""
        # Exemplo de query para status=1 (Novo). Ajuste o searchCriteria conforme necessário.
        endpoint = "search/Ticket?criteria[0][field]=12&criteria[0][searchtype]=equals&criteria[0][value]=1"
        try:
            response = self._fazer_requisicao("GET", endpoint)
            dados = response.json()
            # Retorna a lista de dados. O GLPI Search retorna em 'data'
            return dados.get("data", [])
        except Exception as e:
            logger.error(f"Erro ao buscar chamados pendentes: {str(e)}")
            return []

    def adicionar_acompanhamento(self, ticket_id: int, conteudo: str, privado: bool = True) -> bool:
        """Adiciona um follow-up (tarefa/acompanhamento) a um chamado."""
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
            logger.debug(f"Acompanhamento adicionado ao ticket {ticket_id}.")
            return True
        except Exception as e:
            logger.error(f"Erro ao adicionar acompanhamento no ticket {ticket_id}: {str(e)}")
            return False

    def atualizar_status(self, ticket_id: int, novo_status: int) -> bool:
        """
        Atualiza o status de um chamado.
        Status comuns: 1 (Novo), 2 (Em Atendimento), 5 (Resolvido), 6 (Fechado).
        """
        endpoint = f"Ticket/{ticket_id}"
        payload = {
            "input": {
                "id": ticket_id,
                "status": novo_status
            }
        }
        try:
            # Requer HTTP PUT/PATCH para atualização de item
            self._fazer_requisicao("PUT", endpoint, json=payload)
            logger.info(f"Status do ticket {ticket_id} atualizado para {novo_status}.")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar status do ticket {ticket_id}: {str(e)}")
            return False


# ============================================================================
# --- BLOCO 5: WORKER POLLING (CORE) ---
# ============================================================================

def main():
    logger.info("Iniciando GLPI Automation Worker...")
    
    # Inicializa serviços Core
    glpi = ClienteGLPI(
        base_url=os.getenv("GLPI_URL"),
        app_token=os.getenv("GLPI_APP_TOKEN"),
        user_token=os.getenv("GLPI_USER_TOKEN")
    )
    
    # Inicializa Regras de Negócio
    processador = ProcessadorDeChamado(glpi_client=glpi)

    # Loop Infinito de Polling
    while True:
        try:
            chamados_pendentes = glpi.buscar_chamados_pendentes()
            
            if chamados_pendentes:
                logger.info(f"[{len(chamados_pendentes)}] chamados encontrados para processamento.")
                
                for chamado in chamados_pendentes:
                    processador.processar(chamado)
            else:
                logger.debug("Nenhum chamado pendente no momento.")

        except requests.exceptions.RequestException as req_err:
            logger.error(f"Erro de rede durante o ciclo: {str(req_err)}")
        except Exception as e:
            logger.critical(f"Erro inesperado no loop principal: {str(e)}", exc_info=True)
            
        logger.debug(f"Aguardando {POLLING_INTERVAL} segundos para o próximo ciclo...")
        time.sleep(POLLING_INTERVAL)

if __name__ == "__main__":
    main()
