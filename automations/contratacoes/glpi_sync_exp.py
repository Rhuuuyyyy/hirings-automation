"""
automations/contratacoes/glpi_sync.py — Worker de sincronização GLPI → database.

Polling contínuo da fila de chamados do GLPI. A cada ciclo, sobrescreve
database/contratacoes.json com o snapshot atual dos chamados ativos.
O dashboard web lê esse arquivo via API REST (backend/api.py).

Variáveis de ambiente (.env na raiz do repositório):
    GLPI_URL                             — URL base da API REST, incluindo /apirest.php
    GLPI_USER_TOKEN                      — User-Token do usuário de integração
    GLPI_APP_TOKEN                       — App-Token da aplicação no GLPI
    CATEGORIA_CONTRATACAO_IDS            — IDs de categoria (vírgula) a monitorar
    CATEGORIA_CONTRATACAO_ID_WITH_ASSETS — ID da categoria com envio de equipamento
    POLLING_INTERVAL                     — Segundos entre varreduras (padrão: 300)
"""

# ============================================================================
# Bootstrap — executa ANTES de qualquer import de terceiros.
# ============================================================================
import subprocess
import sys

# [O QUÊ] Verifica se um módulo específico está instalado no ambiente atual.
# [COMO] Usa a função built-in `__import__`. Se falhar, lança ImportError.
def _modulo_ausente(nome: str) -> bool:
    try:
        __import__(nome)
        return False
    except ImportError:
        return True

# [O QUÊ] Instala automaticamente bibliotecas externas caso elas faltem.
# [POR QUÊ] Scripts de automação muitas vezes rodam em servidores crus, cronjobs ou
# containers. Esse bootstrap garante que o script "se conserte" sozinho, instalando
# requests e dotenv sem precisar de intervenção manual do sysadmin.
def _bootstrap() -> None:
    _DEPS = {
        "requests": "requests>=2.31.0",
        "dotenv":   "python-dotenv>=1.0.0",
    }
    ausentes = [pkg for mod, pkg in _DEPS.items() if _modulo_ausente(mod)]
    if not ausentes:
        return
    print(f"[bootstrap] Instalando dependências ausentes: {', '.join(ausentes)}")
    try:
        # [COMO] `sys.executable` aponta para o binário do Python rodando este script.
        # Usa subprocess para rodar `python -m pip install...` de forma segura no SO.
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + ausentes
        )
    except subprocess.CalledProcessError:
        print("[bootstrap] ERRO: falha ao instalar dependências.")
        sys.exit(1)
    
    print("[bootstrap] Instalação concluída. Reiniciando script...\n")
    # [POR QUÊ] Se instalamos algo novo, o interpretador Python em execução pode não
    # reconhecer imediatamente. Subimos um novo processo do script e encerramos este.
    resultado = subprocess.run([sys.executable] + sys.argv)
    sys.exit(resultado.returncode)

_bootstrap()

# ============================================================================
# Imports
# ============================================================================
import html as _html_mod
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Importações de terceiros agora são seguras graças ao _bootstrap()
import requests
from dotenv import load_dotenv

# ============================================================================
# Paths — resolvidos relativos à raiz do repo, não ao cwd
# ============================================================================

# [O QUÊ] Descobre a raiz do projeto dinamicamente.
# [COMO] `__file__` é o caminho deste arquivo. `.resolve()` pega o caminho absoluto.
# `.parents[2]` sobe dois níveis de diretório: glpi_sync.py -> contratacoes -> automations -> raiz.
# [POR QUÊ] Se você rodar o script de dentro da pasta `automations` ou da raiz do repo,
# os caminhos não quebram. Depender de caminhos relativos puros ("./database") causa bugs.
_REPO_ROOT    = Path(__file__).resolve().parents[2]
DATABASE_PATH = _REPO_ROOT / "database" / "contratacoes.json"
HISTORICO_PATH = _REPO_ROOT / "database" / "historico.json"

# [CONTEXTO] Carrega as variáveis do .env para a memória. `main.py` e `run.py` também
# podem acessar essas variáveis agora.
load_dotenv(_REPO_ROOT / ".env")

# ============================================================================
# Logging
# ============================================================================

# [COMO] Configuração do logger padrão do Python. O formato inclui data, nível (INFO, ERROR) e a mensagem.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("glpi_sync")

HTTP_TIMEOUT = 30  # Segundos. Previne que a thread trave para sempre se o GLPI cair.

# ============================================================================
# Constantes de domínio
# ============================================================================

# [POR QUÊ] Mapeia os IDs numéricos obscuros do banco de dados do GLPI para strings 
# amigáveis. O Frontend (index.html) espera receber essas strings literais (ex: "Novo", "Pendente").
STATUS_MAP: dict[int, str] = {
    1: "Novo",
    2: "Em Atendimento",
    3: "Em Atendimento",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}

# Usamos um `frozenset` (lista imutável de busca rápida O(1)) para filtrar os IDs no loop depois.
STATUSES_ATIVOS = frozenset({1, 2, 3, 4})

# Substring de busca — intencionalmente curto para resistir a variações de
# maiúsculas, pontuação ou prefixos que o GLPI possa incluir no texto da tarefa.
_TEXTO_TAREFA_TERMO   = "termo de responsabilidade"
_GLPI_TASK_STATE_DONE = 2


# [O QUÊ] Limpa sujeira HTML que o GLPI retorna nos textos.
# [POR QUÊ] O GLPI usa campos de texto rico (TinyMCE). Para o nosso regex encontrar 
# "_TEXTO_TAREFA_TERMO" com segurança, precisamos converter "&amp;" para "&" e remover as tags <div>, <p>, etc.
def _limpar_html(texto: str) -> str:
    """Remove tags HTML, decodifica entidades e normaliza espaços."""
    texto = _html_mod.unescape(texto)           # &nbsp; &amp; &lt; etc → caracteres reais
    texto = re.sub(r"<[^>]+>", " ", texto)      # remove tags restantes
    texto = re.sub(r"\s+", " ", texto).strip()  # colapsa espaços/quebras de linha
    return texto

# ============================================================================
# Configuração
# ============================================================================

# [O QUÊ] Função de validação de ambiente.
# [COMO] Usa fallback (`or`) para garantir retrocompatibilidade caso as variáveis mudem de nome.
def carregar_configuracoes() -> dict[str, Any]:
    """Lê .env, valida obrigatórias e retorna config normalizada."""
    glpi_url   = os.getenv("GLPI_URL") or os.getenv("VERDANADESK_URL")
    user_token = os.getenv("GLPI_USER_TOKEN") or os.getenv("USER_TOKEN")
    app_token  = os.getenv("GLPI_APP_TOKEN") or os.getenv("APP_TOKEN")

    # Verifica se as 3 chaves vitais estão presentes. Se não, morre o script.
    ausentes = [
        nome for nome, val in [
            ("GLPI_URL", glpi_url),
            ("GLPI_USER_TOKEN", user_token),
            ("GLPI_APP_TOKEN", app_token),
        ] if not val
    ]
    if ausentes:
        logger.critical("Variáveis de ambiente obrigatórias ausentes: %s", ", ".join(ausentes))
        sys.exit(1)

    cat_raw = os.getenv("CATEGORIA_CONTRATACAO_IDS", "")
    categoria_ids = [c.strip() for c in cat_raw.split(",") if c.strip()]
    if not categoria_ids:
        logger.critical("CATEGORIA_CONTRATACAO_IDS não definida no .env.")
        sys.exit(1)

    logger.info("Categorias configuradas: %s", categoria_ids)

    cat_ativo_raw = os.getenv("CATEGORIA_CONTRATACAO_ID_WITH_ASSETS", "").strip()
    cat_id_com_ativo: int | None = None
    if cat_ativo_raw:
        try:
            cat_id_com_ativo = int(cat_ativo_raw)
            logger.info("Categoria com ativo: %d", cat_id_com_ativo)
        except ValueError:
            logger.warning(
                "CATEGORIA_CONTRATACAO_ID_WITH_ASSETS inválido ('%s'). Ignorando.", cat_ativo_raw
            )

    return {
        "GLPI_URL":         glpi_url.rstrip("/"), # rstrip("/") remove barras extras no final
        "GLPI_USER_TOKEN":  user_token,
        "GLPI_APP_TOKEN":   app_token,
        "POLLING_INTERVAL": os.getenv("POLLING_INTERVAL", "300"),
        "CATEGORIA_IDS":    categoria_ids,
        "CAT_ID_COM_ATIVO": cat_id_com_ativo,
    }

# ============================================================================
# Cliente GLPI 
# ============================================================================

class ClienteGLPI:
    """
    Cliente REST para o GLPI com gerenciamento automático de sessão.

    [POR QUÊ] A API do GLPI exige que você troque o `user_token` e `app_token`
    por um `session_token` temporário via endpoint `/initSession`. Essa sessão 
    expira. Esta classe encapsula a lógica de renovar a sessão automaticamente
    se o GLPI responder com 401 (Não Autorizado) ou 403 (Proibido).
    """

    def __init__(
        self,
        base_url: str,
        app_token: str,
        user_token: str,
        categoria_ids: list[str],
        cat_id_com_ativo: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.app_token = app_token
        self.user_token = user_token
        self.categoria_ids = categoria_ids
        self.cat_id_com_ativo = cat_id_com_ativo
        self.session_token: str | None = None
        
        # [COMO] `requests.Session()` é crucial em engenharia de backend.
        # Ele mantém as conexões TCP abertas (Keep-Alive) entre múltiplas requisições,
        # o que reduz brutalmente a latência em relação a fazer requests soltos.
        self._session = requests.Session()
        
        # [POR QUÊ] Chamados GLPI trazem o ID do requerente, não o nome. 
        # Fazer um GET para buscar o nome do mesmo gestor 50 vezes destruiria a performance.
        # Guardamos isso num dicionário em memória.
        self._cache_usuarios: dict[int, str] = {}
        self._termos_concluidos: set[int] = set()
        self._iniciar_sessao()

    # --- Gerenciamento de sessão -------------------------------------------

    def _atualizar_headers(self) -> None:
        self._session.headers.clear()
        self._session.headers.update({
            "App-Token":    self.app_token,
            "Content-Type": "application/json",
        })
        if self.session_token:
            self._session.headers["Session-Token"] = self.session_token

    def _iniciar_sessao(self) -> None:
        url = f"{self.base_url}/initSession"
        self._atualizar_headers()
        try:
            response = self._session.get(
                url,
                headers={"Authorization": f"user_token {self.user_token}"},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status() # Lança erro se o HTTP não for 200~299
            self.session_token = response.json().get("session_token")
            if not self.session_token:
                raise RuntimeError("initSession não retornou session_token.")
            self._atualizar_headers()
            logger.info("Sessão GLPI autenticada com sucesso.")
        except requests.exceptions.RequestException as exc:
            logger.critical("Falha crítica ao autenticar no GLPI: %s", exc)
            sys.exit(1)

    def _renovar_sessao(self) -> None:
        logger.warning("Token de sessão expirado. Renovando...")
        self.session_token = None
        self._iniciar_sessao()

    # --- Requisições (Wrappers para injeção de robustez) ----------------------

    def _get(self, url_completa: str) -> Any:
        response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)
        # [O QUÊ/POR QUÊ] O coração da auto-renovação de sessão. Bateu 401? Renova e tenta de novo.
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return {} if not response.text.strip() else response.json()

    def _post(self, url_completa: str, payload: dict) -> Any:
        body = {"input": payload}
        response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return {} if not response.text.strip() else response.json()

    # --- Endpoints de negócio -----------------------------------------------

    def buscar_chamados_ativos(self) -> list[dict[str, Any]]:
        """Busca chamados de contratação ativos por categoria, pagina 200/página."""
        # [O QUÊ] Motor de busca com paginação. O GLPI limita retornos para não sobrecarregar o DB deles.
        PAGE_SIZE = 200
        todos: dict[int, dict] = {}

        for cat_id in self.categoria_ids:
            offset = 0
            while True:
                # [POR QUÊ] Estes `criteria` e `forcedisplay` são a sintaxe exótica 
                # da API do GLPI para forçar a query a retornar campos específicos.
                # Exemplo: forcedisplay[0]=2 traz o ID. forcedisplay[1]=1 traz o Título.
                partes = [
                    "criteria[0][field]=7",
                    "criteria[0][searchtype]=equals",
                    f"criteria[0][value]={cat_id}",
                    "forcedisplay[0]=2",
                    "forcedisplay[1]=1",
                    "forcedisplay[2]=12",
                    "forcedisplay[3]=17",
                    "forcedisplay[4]=15",
                    "forcedisplay[5]=4",
                    f"range={offset}-{offset + PAGE_SIZE - 1}",
                ]
                url = f"{self.base_url}/search/Ticket?{'&'.join(partes)}"
                try:
                    response = self._session.get(url, timeout=HTTP_TIMEOUT)
                    if response.status_code in (401, 403):
                        self._renovar_sessao()
                        response = self._session.get(url, timeout=HTTP_TIMEOUT)
                    
                    if not response.ok or not response.text.strip():
                        break
                    
                    dados = response.json()
                    items: list[dict] = dados.get("data", [])
                    totalcount: int = dados.get("totalcount", 0)
                    
                    for item in items:
                        tid = item.get("2") or item.get("id")
                        try:
                            # 12 é o código do "Status" no search do GLPI
                            status_id = int(item.get("12") or item.get("status") or 0)
                        except (ValueError, TypeError):
                            status_id = 0
                        
                        # Apenas injetamos no dicionário se for um chamado que importa para o dashboard
                        if tid is not None and status_id in STATUSES_ATIVOS:
                            item["_cat_id"] = int(cat_id)
                            todos[int(tid)] = item
                    
                    # [COMO] Controle de laço de paginação. Se a lista `items` veio vazia
                    # ou o offset extrapolou o `totalcount`, sai do while e vai pra próxima categoria.
                    if not items or offset + len(items) >= totalcount:
                        break
                    offset += PAGE_SIZE
                except requests.exceptions.RequestException:
                    break
                except ValueError:
                    break

        return list(todos.values())

    def buscar_data_inicio_do_conteudo(self, ticket_id: int) -> str:
        """Fallback: extrai 'Data de início: DD-MM-YYYY' do HTML do corpo do ticket."""
        # [O QUÊ] Um salvador de vidas. Se o analista não preencheu o campo nativo de SLA do GLPI, 
        # a gente usa regex para caçar a string "Data de início" que possivelmente foi digitada no 
        # corpo de texto do chamado.
        _PADRAO = re.compile(
            r"Data de in[íi]cio:\s*(?:<[^>]+>|&nbsp;|\s)*(\d{2}[-/]\d{2}[-/]\d{4})",
            re.IGNORECASE,
        )
        try:
            dados = self._get(f"{self.base_url}/Ticket/{ticket_id}")
            match = _PADRAO.search(dados.get("content", "") or "")
            if match:
                return match.group(1).replace("-", "/")
        except Exception:
            pass
        return ""

    def verificar_tarefa_termo(self, ticket_id: int) -> str:
        """Verifica (SOMENTE LEITURA) se existe tarefa de termo e retorna seu status."""
        # [POR QUÊ] Memória cache para poupar rede. Se já validamos antes que o termo desse
        # chamado foi concluído, não há porque perguntar ao GLPI de novo. Termos assinados não "desassinam".
        if ticket_id in self._termos_concluidos:
            return "Termo OK"
        
        try:
            resp = self._get(f"{self.base_url}/Ticket/{ticket_id}/TicketTask")
            
            # Se vier um dict ao invés de lista, significa que não tem tarefas.
            if not isinstance(resp, list):
                return "Sem tarefa"

            tarefas: list[dict] = resp
            for i, tarefa in enumerate(tarefas):
                raw_content = tarefa.get("content", "") or ""
                raw_name    = tarefa.get("name", "")    or ""

                # Aplica a limpeza HTML que declaramos no início para procurar de forma limpa.
                texto_limpo = _limpar_html(raw_content + " " + raw_name)

                if _TEXTO_TAREFA_TERMO.lower() in texto_limpo.lower():
                    try:
                        state = int(tarefa.get("state", 0) or 0)
                    except (ValueError, TypeError):
                        state = 0

                    if state >= _GLPI_TASK_STATE_DONE:
                        self._termos_concluidos.add(ticket_id)
                        return "Termo OK"
                    return "Pendente"
            return "Sem tarefa"

        except Exception as exc:
            logger.error("Ticket #%d: erro ao verificar termo: %s", ticket_id, exc)
            return "Erro ao verificar"

    def buscar_nome_usuario(self, user_id: int) -> str:
        """Retorna nome completo do usuário GLPI, com cache em memória."""
        if user_id in self._cache_usuarios:
            return self._cache_usuarios[user_id]
        try:
            dados = self._get(f"{self.base_url}/User/{user_id}")
            firstname = dados.get("firstname", "")
            realname  = dados.get("realname", "")
            nome = f"{firstname} {realname}".strip() or dados.get("name", str(user_id))
        except requests.exceptions.RequestException:
            nome = str(user_id)
        
        # Guarda no dicionário na primeira vez que busca para reutilizar depois.
        self._cache_usuarios[user_id] = nome
        return nome


# ============================================================================
# Helpers
# ============================================================================

def _formatar_datetime(valor: Any) -> str:
    """Converte 'YYYY-MM-DD HH:MM:SS' → 'DD/MM/YYYY HH:MM'."""
    # [CONTEXTO] Padroniza as datas vindas do banco de dados (que costumam ser ISO)
    # para o formato brasileiro para exibição direta no frontend (index.html).
    if not valor:
        return ""
    try:
        return datetime.strptime(str(valor), "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(valor)

# ============================================================================
# Sincronizador → Database JSON
# ============================================================================

class SincronizadorDB:
    """
    Converte os chamados do GLPI para o schema do dashboard e persiste em JSON.

    [POR QUÊ] Essa classe cria a ponte que desmembra o backend pesado (GLPI) do nosso
    backend leve (FastAPI no main.py). Em vez da API do dashboard consultar o GLPI na hora
    em que o usuário abre a página (o que demoraria 15+ segundos e sobrecarregaria o servidor),
    este worker consulta e salva o snapshot em um arquivo JSON local. O FastAPI apenas lê esse JSON em milissegundos.
    """

    def __init__(self, db_path: Path, glpi: ClienteGLPI) -> None:
        self.db_path = db_path
        self.glpi = glpi
        # `mkdir(parents=True)` garante que a pasta `database/` exista antes de tentar salvar.
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _chamado_para_dict(self, chamado: dict) -> dict | None:
        # [O QUÊ] Mapeador de Schema (Data Transfer Object).
        # Extrai os dados bagunçados da resposta GLPI e empacota num dicionário limpo 
        # e tipado exatamente como o `index.html` precisa.
        id_raw = chamado.get("2") or chamado.get("id")
        if id_raw is None:
            return None
        ticket_id = int(id_raw)

        status_id = int(chamado.get("12") or chamado.get("status") or 0)

        # Trata o campo requerente (código 4 no GLPI) acionando o Client para pegar o Nome literal
        requerente = ""
        req_raw = chamado.get("4") or chamado.get("_users_id_requester") or chamado.get("users_id_requester")
        if req_raw:
            try:
                uid = int(req_raw)
                if uid > 0:
                    requerente = self.glpi.buscar_nome_usuario(uid)
            except (ValueError, TypeError):
                requerente = str(req_raw)

        tempo_solucao = _formatar_datetime(chamado.get("17") or chamado.get("time_to_resolve"))
        if not tempo_solucao:
            tempo_solucao = self.glpi.buscar_data_inicio_do_conteudo(ticket_id)

        cat_id = chamado.get("_cat_id") or chamado.get("itilcategories_id")
        
        # [REGRA DE NEGÓCIO] Só verifica Termo de Responsabilidade se a categoria do 
        # chamado estiver configurada para requerer envio de equipamento (ex: notebook).
        if self.glpi.cat_id_com_ativo is not None and cat_id == self.glpi.cat_id_com_ativo:
            termo_status = self.glpi.verificar_tarefa_termo(ticket_id)
        else:
            termo_status = "Sem tarefa"

        return {
            "ID_do_Chamado": ticket_id,
            "Titulo":        chamado.get("1") or chamado.get("name") or "",
            "Status":        STATUS_MAP.get(status_id, f"Status {status_id}"),
            "Tempo_Solucao": tempo_solucao,
            "Data_Abertura": _formatar_datetime(chamado.get("15") or chamado.get("date_creation")),
            "Requerente":    requerente,
            "Termo_Status":  termo_status,
        }

    def sincronizar(self, chamados_api: list[dict]) -> None:
        linhas = [self._chamado_para_dict(c) for c in chamados_api]
        linhas = [l for l in linhas if l is not None]
        linhas.sort(key=lambda x: x["ID_do_Chamado"])

        snapshot = {
            "ultima_atualizacao": datetime.now().isoformat(),
            "total":    len(linhas),
            "chamados": linhas,
        }

        # [O QUÊ / POR QUÊ] O Conceito de ESCRITA ATÔMICA.
        # Se escrevermos diretamente no `contratacoes.json` e o disco/servidor der problema
        # nos exatos milissegundos em que o Python está escrevendo as linhas de texto,
        # o arquivo ficará corrompido pela metade. O FastAPI iria ler um JSON quebrado e crachar a aplicação inteira.
        # Ao invés disso, escrevemos num arquivo temporário (.json.tmp) e fazemos `os.replace`. 
        # O sistema operacional garante que a substituição de arquivos no mesmo disco (rename) ocorra de uma só vez (atomicidade).
        tmp = self.db_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.db_path)
        
        logger.info("Database atualizada: %d chamado(s) em '%s'.", len(linhas), self.db_path)
        self._atualizar_historico(linhas)

    def _atualizar_historico(self, linhas: list[dict]) -> None:
        """Adiciona o retrato dos KPIs de hoje ao historico.json, mantendo os últimos 60 dias."""
        # [CONTEXTO] Prepara o terreno para gráficos futuros no Dashboard. Todo dia, soma
        # as estatísticas. Se já rodou hoje, substitui o slot de hoje.
        hoje = datetime.now().strftime("%Y-%m-%d")
        contagens: dict[str, int] = {}
        for l in linhas:
            ts = l.get("Termo_Status", "")
            contagens[ts] = contagens.get(ts, 0) + 1

        entrada = {
            "data":             hoje,
            "total":            len(linhas),
            "em_atendimento":   sum(1 for l in linhas if l.get("Status") == "Em Atendimento"),
            "pendente":         sum(1 for l in linhas if l.get("Status") == "Pendente"),
            "termo_ok":         contagens.get("Termo OK", 0),
            "termo_pendente":   contagens.get("Pendente", 0),
            "sem_tarefa":       contagens.get("Sem tarefa", 0),
            "erro_verificar":   contagens.get("Erro ao verificar", 0),
        }

        hist_path = HISTORICO_PATH
        hist: list[dict] = []
        if hist_path.exists():
            try:
                hist = json.loads(hist_path.read_text(encoding="utf-8"))
            except Exception:
                hist = []

        # Substitui a entrada de hoje se existir, senao appends. E fatia (`[-60:]`) para manter apenas os 60 ultimos.
        hist = [h for h in hist if h.get("data") != hoje]
        hist.append(entrada)
        hist = hist[-60:]  

        tmp = hist_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, hist_path)

# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    # [O QUÊ] A função orquestradora que une todas as peças e gera o loop infinito de execução.
    config = carregar_configuracoes()
    polling_interval = int(config["POLLING_INTERVAL"])

    glpi = ClienteGLPI(
        base_url=config["GLPI_URL"],
        app_token=config["GLPI_APP_TOKEN"],
        user_token=config["GLPI_USER_TOKEN"],
        categoria_ids=config["CATEGORIA_IDS"],
        cat_id_com_ativo=config["CAT_ID_COM_ATIVO"],
    )
    sync = SincronizadorDB(db_path=DATABASE_PATH, glpi=glpi)

    # O famigerado Polling (varredura contínua). Roda para sempre enquanto a thread principal viver (via run.py).
    while True:
        try:
            logger.info("--- Iniciando varredura ---")
            chamados = glpi.buscar_chamados_ativos()
            sync.sincronizar(chamados)
        except requests.exceptions.RequestException as exc:
            logger.error("Erro de rede no ciclo de varredura: %s", exc)
        except Exception as exc:
            # Qualquer erro bizarro é capturado aqui para a thread não morrer subitamente e parar de atualizar o painel.
            logger.critical("Erro não tratado no ciclo principal: %s", exc, exc_info=True)

        logger.info("Aguardando %ds para a próxima varredura...", polling_interval)
        time.sleep(polling_interval) # Pausa o processo para não "DDoSar" o servidor do GLPI.

if __name__ == "__main__":
    main()