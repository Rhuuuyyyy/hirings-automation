"""
glpi_to_excel_sync.py — Worker de sincronização GLPI → Power Automate (Webhook).

Polling contínuo da fila de chamados do GLPI. Detecta alterações comparando com
o estado do ciclo anterior (cache_chamados.json) e dispara POSTs para um webhook
do Power Automate apenas quando há novidade: novo chamado, atualização ou resolução.

Variáveis de ambiente (.env):
    GLPI_URL                             — URL base da API REST, incluindo /apirest.php
    GLPI_USER_TOKEN                      — User-Token do usuário de integração
    GLPI_APP_TOKEN                       — App-Token da aplicação no GLPI
    CATEGORIA_CONTRATACAO_IDS            — IDs de categoria (vírgula) a monitorar
    CATEGORIA_CONTRATACAO_ID_WITH_ASSETS — ID da categoria com envio de equipamento
    POWER_AUTOMATE_WEBHOOK_URL           — URL do webhook do Power Automate
    POLLING_INTERVAL                     — Segundos entre varreduras (padrão: 300)
"""

# ============================================================================
# Bootstrap — executa ANTES de qualquer import de terceiros.
# Garante que as dependências estão instaladas no Python que está rodando
# este script, independente de qual venv ou pip está no PATH do sistema.
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
        print("[bootstrap] ERRO: falha ao instalar dependências. Verifique sua conexão.")
        sys.exit(1)

    print("[bootstrap] Instalação concluída. Reiniciando script...\n")
    resultado = subprocess.run([sys.executable] + sys.argv)
    sys.exit(resultado.returncode)


_bootstrap()

# ============================================================================
# Imports (seguros após o bootstrap)
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
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("glpi_sync")

HTTP_TIMEOUT = 30      # segundos — chamadas GLPI
WEBHOOK_TIMEOUT = 30   # segundos — Power Automate pode ser lento na primeira invocação

# ============================================================================
# Constantes de domínio
# ============================================================================

# IDs de status GLPI → texto PT-BR (ver .brain/glpi_api_quirks.md)
STATUS_MAP: dict[int, str] = {
    1: "Novo",
    2: "Em Atendimento",
    3: "Em Atendimento",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}

# Apenas estes status ficam no cache ativo; ausência = ticket foi resolvido/fechado
STATUSES_ATIVOS = frozenset({1, 2, 3, 4})

# Texto canônico da tarefa de controle de ativo; busca é case-insensitive
_TEXTO_TAREFA_TERMO = "Envio do termo de responsabilidade"

# Estado GLPI de TicketTask: 1 = To do, 2 = Done (Planning::TODO / Planning::DONE)
_GLPI_TASK_STATE_DONE = 2

# ============================================================================
# Configuração
# ============================================================================


def carregar_configuracoes() -> dict[str, Any]:
    """Lê .env, valida obrigatórias e retorna config normalizada."""
    load_dotenv()

    glpi_url    = os.getenv("GLPI_URL") or os.getenv("VERDANADESK_URL")
    user_token  = os.getenv("GLPI_USER_TOKEN") or os.getenv("USER_TOKEN")
    app_token   = os.getenv("GLPI_APP_TOKEN") or os.getenv("APP_TOKEN")
    webhook_url = os.getenv("POWER_AUTOMATE_WEBHOOK_URL")

    ausentes = [
        nome
        for nome, val in [
            ("GLPI_URL", glpi_url),
            ("GLPI_USER_TOKEN", user_token),
            ("GLPI_APP_TOKEN", app_token),
            ("POWER_AUTOMATE_WEBHOOK_URL", webhook_url),
        ]
        if not val
    ]
    if ausentes:
        logger.critical("Variáveis de ambiente obrigatórias ausentes: %s", ", ".join(ausentes))
        sys.exit(1)

    cat_raw = os.getenv("CATEGORIA_CONTRATACAO_IDS", "")
    categoria_ids = [c.strip() for c in cat_raw.split(",") if c.strip()]
    if not categoria_ids:
        logger.critical(
            "CATEGORIA_CONTRATACAO_IDS não definida no .env. "
            "Informe os IDs de categoria separados por vírgula (ex: 152,153)."
        )
        sys.exit(1)

    logger.info("Categorias de contratação configuradas: %s", categoria_ids)

    cat_ativo_raw = os.getenv("CATEGORIA_CONTRATACAO_ID_WITH_ASSETS", "").strip()
    cat_id_com_ativo: int | None = None
    if cat_ativo_raw:
        try:
            cat_id_com_ativo = int(cat_ativo_raw)
            logger.info("Categoria com ativo configurada: %d", cat_id_com_ativo)
        except ValueError:
            logger.warning(
                "CATEGORIA_CONTRATACAO_ID_WITH_ASSETS inválido ('%s'). "
                "Ignorando — nenhum chamado receberá controle de termo.",
                cat_ativo_raw,
            )

    return {
        "GLPI_URL":         glpi_url.rstrip("/"),
        "GLPI_USER_TOKEN":  user_token,
        "GLPI_APP_TOKEN":   app_token,
        "WEBHOOK_URL":      webhook_url,
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

    Renova o session_token de forma transparente ao receber 401 ou 403,
    replicando o padrão de auto-healing do boilerplate legado.
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
        # Tickets cujo termo já foi confirmado como concluído não precisam de nova chamada API.
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
                # Authorization só é enviado no initSession, não nas demais chamadas
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
        logger.warning("Token de sessão expirado. Iniciando renovação automática...")
        self.session_token = None
        self._iniciar_sessao()

    # --- Requisições --------------------------------------------------------

    def _get(self, url_completa: str) -> Any:
        """GET resiliente: renova sessão e retenta uma vez em caso de 401/403."""
        response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)

        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.get(url_completa, timeout=HTTP_TIMEOUT)

        if not response.ok:
            logger.error(
                "Requisição falhou [GET %s]. Status %s: %s",
                url_completa, response.status_code, response.text[:300],
            )
        response.raise_for_status()

        if not response.text.strip():
            return {}

        return response.json()

    def _post(self, url_completa: str, payload: dict) -> Any:
        """POST resiliente: renova sessão e retenta uma vez em caso de 401/403."""
        body = {"input": payload}
        response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)

        if response.status_code in (401, 403):
            self._renovar_sessao()
            response = self._session.post(url_completa, json=body, timeout=HTTP_TIMEOUT)

        if not response.ok:
            logger.error(
                "POST falhou [%s]. Status %s: %s",
                url_completa, response.status_code, response.text[:300],
            )
            response.raise_for_status()

        if not response.text.strip():
            return {}

        return response.json()

    # --- Endpoints de negócio -----------------------------------------------

    def buscar_chamados_ativos(self) -> list[dict[str, Any]]:
        """Busca chamados de contratação ativos, filtrando por categoria no servidor.

        Itera sobre cada categoria em CATEGORIA_CONTRATACAO_IDS, pagina a 200/página
        e filtra status ativos em Python (notequals causa body vazio nesta versão do GLPI).
        forcedisplay garante que os 6 campos sempre aparecem na resposta.
        """
        PAGE_SIZE = 200
        # dict para deduplicar por ID caso um ticket apareça em duas categorias
        todos: dict[int, dict] = {}

        for cat_id in self.categoria_ids:
            offset = 0
            while True:
                partes = [
                    # Filtro de categoria no servidor (field 7 = Categoria do chamado)
                    "criteria[0][field]=7",
                    "criteria[0][searchtype]=equals",
                    f"criteria[0][value]={cat_id}",
                    # Campos obrigatórios na resposta
                    "forcedisplay[0]=2",   # ID do chamado
                    "forcedisplay[1]=1",   # Título
                    "forcedisplay[2]=12",  # Status
                    "forcedisplay[3]=17",  # Tempo para Solução (prazo)
                    "forcedisplay[4]=15",  # Data de abertura
                    "forcedisplay[5]=4",   # Requerente (user ID)
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
                            # Injeta o ID de categoria para uso em _chamado_para_payload
                            item["_cat_id"] = int(cat_id)
                            todos[int(tid)] = item
                            ativos_pagina += 1

                    logger.info(
                        "Categoria %s: %d/%d recebidos | %d ativos nesta página.",
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

        logger.info("Total de chamados ativos de contratação: %d", len(todos))
        return list(todos.values())

    def buscar_data_inicio_do_conteudo(self, ticket_id: int) -> str:
        """Extrai 'Data de início' do HTML do corpo do chamado quando o campo SLA vem vazio.

        Fallback: quando field 17 está vazio na Search API, faz GET /Ticket/{id} e aplica
        regex no campo content (HTML bruto) para extrair o padrão 'Data de inicio: DD-MM-YYYY'.
        """
        _PADRAO_DATA_INICIO = re.compile(
            r"Data de in[íi]cio:\s*(?:<[^>]+>|&nbsp;|\s)*(\d{2}[-/]\d{2}[-/]\d{4})",
            re.IGNORECASE,
        )
        try:
            dados = self._get(f"{self.base_url}/Ticket/{ticket_id}")
            content = dados.get("content", "") or ""
            match = _PADRAO_DATA_INICIO.search(content)
            if match:
                return match.group(1).replace("-", "/")
        except Exception:
            pass
        return ""

    def verificar_ou_criar_tarefa_termo(self, ticket_id: int) -> str:
        """Garante que a tarefa de termo de responsabilidade existe no chamado.

        Fluxo:
        1. Tickets já confirmados como concluídos são respondidos do cache.
        2. Lê todas as TicketTasks via GET /Ticket/{id}/TicketTask.
        3. Procura a tarefa pelo texto (case-insensitive, ignorando HTML).
        4. Se encontrada e concluída → armazena no cache e retorna 'Termo enviado'.
        5. Se encontrada e pendente → retorna 'Pendente de envio'.
        6. Se não encontrada → cria via POST e retorna 'Pendente de envio'.
        7. Em caso de erro → loga e retorna 'Erro ao criar tarefa'.
        """
        if ticket_id in self._termos_concluidos:
            return "Termo enviado"

        try:
            resp = self._get(f"{self.base_url}/Ticket/{ticket_id}/TicketTask")
            tarefas: list[dict] = resp if isinstance(resp, list) else []

            for tarefa in tarefas:
                content_html = tarefa.get("content", "") or ""
                # Remove tags HTML para comparação limpa
                content_texto = re.sub(r"<[^>]+>", " ", content_html)
                if _TEXTO_TAREFA_TERMO.lower() in content_texto.lower():
                    try:
                        state = int(tarefa.get("state", 0) or 0)
                    except (ValueError, TypeError):
                        state = 0
                    if state >= _GLPI_TASK_STATE_DONE:
                        self._termos_concluidos.add(ticket_id)
                        logger.debug("Ticket #%d: termo concluído (state=%d).", ticket_id, state)
                        return "Termo enviado"
                    return "Pendente de envio"

            # Tarefa não existe — criar
            logger.info(
                "Ticket #%d: tarefa '%s' não encontrada. Criando.",
                ticket_id, _TEXTO_TAREFA_TERMO,
            )
            self._post(
                f"{self.base_url}/Ticket/{ticket_id}/TicketTask",
                {"tickets_id": ticket_id, "content": _TEXTO_TAREFA_TERMO, "state": 1},
            )
            logger.info("Ticket #%d: tarefa de termo criada com sucesso.", ticket_id)
            return "Pendente de envio"

        except Exception as exc:
            logger.error(
                "Ticket #%d: erro ao verificar/criar tarefa de termo: %s", ticket_id, exc
            )
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
    """Converte 'YYYY-MM-DD HH:MM:SS' → 'DD/MM/YYYY HH:MM'. Retorna str vazia se ausente."""
    if not valor:
        return ""
    try:
        return datetime.strptime(str(valor), "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(valor)


# ============================================================================
# Cache de estado entre ciclos
# ============================================================================

CACHE_PATH = Path("cache_chamados.json")


def _carregar_cache(caminho: Path) -> dict[str, dict]:
    """Lê o cache do disco. Retorna dict vazio se o arquivo não existir ou estiver corrompido."""
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Cache corrompido ou ilegível (%s). Iniciando do zero.", exc)
        return {}


def _salvar_cache_atomico(caminho: Path, cache: dict[str, dict]) -> None:
    """Grava o cache em arquivo temporário e então faz rename atômico.

    os.replace() é atômico em POSIX e Windows (mesmo filesystem): garante que
    uma reinicialização no meio da escrita nunca deixa um JSON truncado no disco.
    """
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


# ============================================================================
# Sincronizador via Webhook
# ============================================================================

class SincronizadorWebhook:
    """
    Compara o estado atual do GLPI com o cache local e dispara o webhook apenas para diferenças.

    Regras:
    - UPSERT: chamado novo (não está no cache) ou com qualquer campo alterado.
    - DELETE: chamado presente no cache mas ausente da busca atual (foi resolvido/fechado).

    Cada POST ao webhook é isolado em try/except próprio: uma falha de rede ou timeout
    no Power Automate não interrompe o processamento dos demais chamados.
    O cache é gravado atomicamente ao final de cada ciclo completo.
    """

    def __init__(
        self, webhook_url: str, glpi: ClienteGLPI, cache_path: Path
    ) -> None:
        self.webhook_url = webhook_url
        self.glpi = glpi
        self.cache_path = cache_path
        self._cache: dict[str, dict] = _carregar_cache(cache_path)
        logger.info("Cache carregado: %d chamado(s) do ciclo anterior.", len(self._cache))

    def _chamado_para_payload(self, chamado: dict) -> dict | None:
        """Extrai e normaliza um chamado da API para o schema do webhook (sem 'Acao')."""
        id_raw = chamado.get("2") or chamado.get("id")
        if id_raw is None:
            return None
        try:
            ticket_id = int(id_raw)
        except (ValueError, TypeError):
            logger.debug("ID inválido descartado: %s", id_raw)
            return None

        try:
            status_id = int(chamado.get("12") or chamado.get("status") or 0)
        except (ValueError, TypeError):
            status_id = 0

        # Requerente: "4" na Search API, nomes alternativos na API direta
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

        # Tempo para Solução: tenta field 17 da Search API; se vazio, extrai do HTML do corpo
        tempo_solucao = _formatar_datetime(chamado.get("17") or chamado.get("time_to_resolve"))
        if not tempo_solucao:
            tempo_solucao = self.glpi.buscar_data_inicio_do_conteudo(ticket_id)
            if tempo_solucao:
                logger.debug("Ticket #%d: 'Tempo_Solucao' extraído do corpo.", ticket_id)

        # Termo Status: depende da categoria do chamado
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

    def _post_webhook(self, payload: dict) -> None:
        """Dispara um único POST ao webhook de forma isolada.

        Nunca propaga exceções: erros são logados e o ciclo continua.
        """
        acao = payload.get("Acao", "?")
        tid  = payload.get("ID_do_Chamado", "?")
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT)
            resp.raise_for_status()
            logger.debug("Webhook OK [%s #%s] → HTTP %s", acao, tid, resp.status_code)
        except requests.exceptions.Timeout:
            logger.error(
                "Webhook timeout [%s #%s]: Power Automate não respondeu em %ds.",
                acao, tid, WEBHOOK_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            logger.error("Webhook falhou [%s #%s]: %s", acao, tid, exc)
        except Exception as exc:
            logger.error("Erro inesperado no webhook [%s #%s]: %s", acao, tid, exc)

    def sincronizar(self, chamados_api: list[dict]) -> None:
        """Compara com o cache, dispara webhooks para diferenças e persiste o novo estado."""
        novo_cache: dict[str, dict] = {}
        inseridos = atualizados = erros = 0

        for chamado in chamados_api:
            payload = self._chamado_para_payload(chamado)
            if payload is None:
                erros += 1
                continue

            tid = str(payload["ID_do_Chamado"])
            # entrada_cache: payload sem "Acao" — exatamente o que comparamos e persistimos
            entrada_cache = dict(payload)

            if tid not in self._cache:
                self._post_webhook({"Acao": "UPSERT", **entrada_cache})
                inseridos += 1
            elif self._cache[tid] != entrada_cache:
                self._post_webhook({"Acao": "UPSERT", **entrada_cache})
                atualizados += 1
            # sem mudança → nenhum POST disparado

            novo_cache[tid] = entrada_cache

        # DELETE: IDs que existiam no cache mas não vieram na busca atual
        deletados = 0
        for tid, dados in self._cache.items():
            if tid not in novo_cache:
                self._post_webhook({"Acao": "DELETE", "ID_do_Chamado": dados["ID_do_Chamado"]})
                deletados += 1

        # Atualiza estado em memória e persiste atomicamente
        self._cache = novo_cache
        _salvar_cache_atomico(self.cache_path, self._cache)

        logger.info(
            "Ciclo concluído: +%d novo(s) | ~%d atualizado(s) | -%d removido(s) | %d erro(s) de mapeamento.",
            inseridos, atualizados, deletados, erros,
        )


# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    config = carregar_configuracoes()
    polling_interval = int(config["POLLING_INTERVAL"])

    logger.info(
        "GLPI→Webhook Sync iniciado. Cache: '%s' | Ciclo: %ds (%d min).",
        CACHE_PATH, polling_interval, polling_interval // 60,
    )

    glpi = ClienteGLPI(
        base_url=config["GLPI_URL"],
        app_token=config["GLPI_APP_TOKEN"],
        user_token=config["GLPI_USER_TOKEN"],
        categoria_ids=config["CATEGORIA_IDS"],
        cat_id_com_ativo=config["CAT_ID_COM_ATIVO"],
    )
    sync = SincronizadorWebhook(
        webhook_url=config["WEBHOOK_URL"],
        glpi=glpi,
        cache_path=CACHE_PATH,
    )

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
