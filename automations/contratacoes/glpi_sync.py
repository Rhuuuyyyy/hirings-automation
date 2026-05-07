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


def _modulo_ausente(nome: str) -> bool:
    try:
        __import__(nome)
        return False
    except ImportError:
        return True


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
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + ausentes
        )
    except subprocess.CalledProcessError:
        print("[bootstrap] ERRO: falha ao instalar dependências.")
        sys.exit(1)
    print("[bootstrap] Instalação concluída. Reiniciando script...\n")
    resultado = subprocess.run([sys.executable] + sys.argv)
    sys.exit(resultado.returncode)


_bootstrap()

# ============================================================================
# Imports
# ============================================================================
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# ============================================================================
# Paths — resolvidos relativos à raiz do repo, não ao cwd
# ============================================================================

# automations/contratacoes/glpi_sync.py → parents[2] = raiz do repo
_REPO_ROOT    = Path(__file__).resolve().parents[2]
DATABASE_PATH = _REPO_ROOT / "database" / "contratacoes.json"
HISTORICO_PATH = _REPO_ROOT / "database" / "historico.json"

load_dotenv(_REPO_ROOT / ".env")

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("glpi_sync")

HTTP_TIMEOUT = 30  # segundos

# ============================================================================
# Constantes de domínio
# ============================================================================

STATUS_MAP: dict[int, str] = {
    1: "Novo",
    2: "Em Atendimento",
    3: "Em Atendimento",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}

STATUSES_ATIVOS = frozenset({1, 2, 3, 4})

_TEXTO_TAREFA_TERMO   = "Envio do termo de responsabilidade"
_GLPI_TASK_STATE_DONE = 2

# ============================================================================
# Configuração
# ============================================================================


def carregar_configuracoes() -> dict[str, Any]:
    """Lê .env, valida obrigatórias e retorna config normalizada."""
    glpi_url   = os.getenv("GLPI_URL") or os.getenv("VERDANADESK_URL")
    user_token = os.getenv("GLPI_USER_TOKEN") or os.getenv("USER_TOKEN")
    app_token  = os.getenv("GLPI_APP_TOKEN") or os.getenv("APP_TOKEN")

    ausentes = [
        nome
        for nome, val in [
            ("GLPI_URL", glpi_url),
            ("GLPI_USER_TOKEN", user_token),
            ("GLPI_APP_TOKEN", app_token),
        ]
        if not val
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
        "GLPI_URL":         glpi_url.rstrip("/"),
        "GLPI_USER_TOKEN":  user_token,
        "GLPI_APP_TOKEN":   app_token,
        "POLLING_INTERVAL": os.getenv("POLLING_INTERVAL", "300"),
        "CATEGORIA_IDS":    categoria_ids,
        "CAT_ID_COM_ATIVO": cat_id_com_ativo,
    }


# ============================================================================
# Cliente GLPI  (não modificar — lógica de sessão e negócio estável)
# ============================================================================

class ClienteGLPI:
    """
    Cliente REST para o GLPI com gerenciamento automático de sessão.

    Renova o session_token de forma transparente ao receber 401 ou 403.
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
        self._session = requests.Session()
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
            if not response.ok:
                logger.error(
                    "Falha no login GLPI. Status %s: %s",
                    response.status_code, response.text[:200],
                )
            response.raise_for_status()
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

    # --- Requisições --------------------------------------------------------

    def _get(self, url_completa: str) -> Any:
        response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)
        if not response.ok:
            logger.error(
                "GET falhou [%s] %s: %s",
                url_completa, response.status_code, response.text[:300],
            )
        response.raise_for_status()
        return {} if not response.text.strip() else response.json()

    def _post(self, url_completa: str, payload: dict) -> Any:
        body = {"input": payload}
        response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)
        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)
        if not response.ok:
            logger.error(
                "POST falhou [%s] %s: %s",
                url_completa, response.status_code, response.text[:300],
            )
            response.raise_for_status()
        return {} if not response.text.strip() else response.json()

    # --- Endpoints de negócio -----------------------------------------------

    def buscar_chamados_ativos(self) -> list[dict[str, Any]]:
        """Busca chamados de contratação ativos por categoria, pagina 200/página."""
        PAGE_SIZE = 200
        todos: dict[int, dict] = {}

        for cat_id in self.categoria_ids:
            offset = 0
            while True:
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
                logger.info("Buscando categoria %s (offset=%d)", cat_id, offset)
                try:
                    response = self._session.get(url, timeout=HTTP_TIMEOUT)
                    if response.status_code in (401, 403):
                        self._renovar_sessao()
                        response = self._session.get(url, timeout=HTTP_TIMEOUT)
                    logger.info("HTTP %s | %d bytes", response.status_code, len(response.content))
                    if not response.ok:
                        logger.error("Erro (cat %s): %.300s", cat_id, response.text)
                        break
                    if not response.text.strip():
                        logger.info("Categoria %s: sem chamados.", cat_id)
                        break
                    dados = response.json()
                    items: list[dict] = dados.get("data", [])
                    totalcount: int = dados.get("totalcount", 0)
                    ativos_pagina = 0
                    for item in items:
                        tid = item.get("2") or item.get("id")
                        try:
                            status_id = int(item.get("12") or item.get("status") or 0)
                        except (ValueError, TypeError):
                            status_id = 0
                        if tid is not None and status_id in STATUSES_ATIVOS:
                            item["_cat_id"] = int(cat_id)
                            todos[int(tid)] = item
                            ativos_pagina += 1
                    logger.info(
                        "Categoria %s: %d/%d recebidos | %d ativos.",
                        cat_id, offset + len(items), totalcount, ativos_pagina,
                    )
                    if not items or offset + len(items) >= totalcount:
                        break
                    offset += PAGE_SIZE
                except requests.exceptions.RequestException as exc:
                    logger.error("Falha de rede (cat %s, offset %d): %s", cat_id, offset, exc)
                    break
                except ValueError as exc:
                    logger.error("JSON inválido (cat %s): %s", cat_id, exc)
                    break

        logger.info("Total de chamados ativos: %d", len(todos))
        return list(todos.values())

    def buscar_data_inicio_do_conteudo(self, ticket_id: int) -> str:
        """Fallback: extrai 'Data de início: DD-MM-YYYY' do HTML do corpo do ticket."""
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

    def verificar_ou_criar_tarefa_termo(self, ticket_id: int) -> str:
        """Lê/cria a tarefa de termo de responsabilidade e retorna seu status."""
        if ticket_id in self._termos_concluidos:
            return "Termo enviado"
        try:
            resp = self._get(f"{self.base_url}/Ticket/{ticket_id}/TicketTask")
            tarefas: list[dict] = resp if isinstance(resp, list) else []
            for tarefa in tarefas:
                content_texto = re.sub(r"<[^>]+>", " ", tarefa.get("content", "") or "")
                if _TEXTO_TAREFA_TERMO.lower() in content_texto.lower():
                    try:
                        state = int(tarefa.get("state", 0) or 0)
                    except (ValueError, TypeError):
                        state = 0
                    if state >= _GLPI_TASK_STATE_DONE:
                        self._termos_concluidos.add(ticket_id)
                        logger.debug("Ticket #%d: termo concluído.", ticket_id)
                        return "Termo enviado"
                    return "Pendente de envio"
            logger.info("Ticket #%d: criando tarefa de termo.", ticket_id)
            self._post(
                f"{self.base_url}/Ticket/{ticket_id}/TicketTask",
                {"tickets_id": ticket_id, "content": _TEXTO_TAREFA_TERMO, "state": 1},
            )
            return "Pendente de envio"
        except Exception as exc:
            logger.error("Ticket #%d: erro na tarefa de termo: %s", ticket_id, exc)
            return "Erro ao criar tarefa"

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
        self._cache_usuarios[user_id] = nome
        return nome


# ============================================================================
# Helpers
# ============================================================================

def _formatar_datetime(valor: Any) -> str:
    """Converte 'YYYY-MM-DD HH:MM:SS' → 'DD/MM/YYYY HH:MM'."""
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

    A cada ciclo sobrescreve database/contratacoes.json com o snapshot completo.
    Escrita atômica (write .tmp + os.replace) garante que o arquivo nunca fica corrompido
    mesmo que o script seja reiniciado no meio da escrita.
    """

    def __init__(self, db_path: Path, glpi: ClienteGLPI) -> None:
        self.db_path = db_path
        self.glpi = glpi
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _chamado_para_dict(self, chamado: dict) -> dict | None:
        id_raw = chamado.get("2") or chamado.get("id")
        if id_raw is None:
            return None
        try:
            ticket_id = int(id_raw)
        except (ValueError, TypeError):
            return None

        try:
            status_id = int(chamado.get("12") or chamado.get("status") or 0)
        except (ValueError, TypeError):
            status_id = 0

        requerente = ""
        req_raw = (
            chamado.get("4")
            or chamado.get("_users_id_requester")
            or chamado.get("users_id_requester")
        )
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
        if self.glpi.cat_id_com_ativo is not None and cat_id == self.glpi.cat_id_com_ativo:
            termo_status = self.glpi.verificar_ou_criar_tarefa_termo(ticket_id)
        else:
            termo_status = "Sem equipamento"

        return {
            "ID_do_Chamado": ticket_id,
            "Titulo":        chamado.get("1") or chamado.get("name") or "",
            "Status":        STATUS_MAP.get(status_id, f"Status {status_id}"),
            "Tempo_Solucao": tempo_solucao,
            "Data_Abertura": _formatar_datetime(
                chamado.get("15") or chamado.get("date_creation")
            ),
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

        tmp = self.db_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.db_path)
        logger.info("Database atualizada: %d chamado(s) em '%s'.", len(linhas), self.db_path)

        self._atualizar_historico(linhas)

    def _atualizar_historico(self, linhas: list[dict]) -> None:
        """Appends today's KPI snapshot to historico.json, keeping last 60 days."""
        hoje = datetime.now().strftime("%Y-%m-%d")
        contagens: dict[str, int] = {}
        for l in linhas:
            ts = l.get("Termo_Status", "")
            contagens[ts] = contagens.get(ts, 0) + 1

        entrada = {
            "data":            hoje,
            "total":           len(linhas),
            "termo_ok":        contagens.get("Termo OK", 0),
            "pendente":        contagens.get("Pendente", 0),
            "sem_tarefa":      contagens.get("Sem tarefa", 0),
            "erro_verificar":  contagens.get("Erro ao verificar", 0),
            "sem_equipamento": contagens.get("Sem equipamento", 0),
        }

        hist_path = HISTORICO_PATH
        hist: list[dict] = []
        if hist_path.exists():
            try:
                hist = json.loads(hist_path.read_text(encoding="utf-8"))
            except Exception:
                hist = []

        # replace today's entry if already exists, else append
        hist = [h for h in hist if h.get("data") != hoje]
        hist.append(entrada)
        hist = hist[-60:]  # keep last 60 days

        tmp = hist_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, hist_path)
        logger.info("Histórico atualizado: %d dia(s) registrado(s).", len(hist))


# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    config = carregar_configuracoes()
    polling_interval = int(config["POLLING_INTERVAL"])

    logger.info(
        "GLPI Sync iniciado. DB: '%s' | Ciclo: %ds (%d min).",
        DATABASE_PATH, polling_interval, polling_interval // 60,
    )

    glpi = ClienteGLPI(
        base_url=config["GLPI_URL"],
        app_token=config["GLPI_APP_TOKEN"],
        user_token=config["GLPI_USER_TOKEN"],
        categoria_ids=config["CATEGORIA_IDS"],
        cat_id_com_ativo=config["CAT_ID_COM_ATIVO"],
    )
    sync = SincronizadorDB(db_path=DATABASE_PATH, glpi=glpi)

    while True:
        try:
            logger.info("--- Iniciando varredura ---")
            chamados = glpi.buscar_chamados_ativos()
            logger.info("%d chamado(s) ativo(s) retornado(s) pela API.", len(chamados))
            sync.sincronizar(chamados)
        except requests.exceptions.RequestException as exc:
            logger.error("Erro de rede no ciclo de varredura: %s", exc)
        except Exception as exc:
            logger.critical("Erro não tratado no ciclo principal: %s", exc, exc_info=True)

        logger.info("Aguardando %ds para a próxima varredura...", polling_interval)
        time.sleep(polling_interval)


if __name__ == "__main__":
    main()
