"""
glpi_to_excel_sync.py — Worker de sincronização GLPI → Excel.

Polling contínuo da fila de chamados do GLPI. Mantém o arquivo
chamados_acompanhamento.xlsx com o backlog ativo (Novo, Em Atendimento, Pendente).
Chamados Solucionados ou Fechados são removidos da planilha automaticamente.

Variáveis de ambiente (.env):
    GLPI_URL          — URL base da API REST, incluindo /apirest.php
                        Ex: http://glpi.empresa.com/apirest.php
    GLPI_USER_TOKEN   — User-Token do usuário de integração
    GLPI_APP_TOKEN    — App-Token da aplicação cadastrada no GLPI
    POLLING_INTERVAL  — Segundos entre varreduras (padrão: 300 = 5 min)
    EXCEL_PATH        — Caminho do arquivo de saída (padrão: chamados_acompanhamento.xlsx)

Nomes legados aceitos: VERDANADESK_URL, USER_TOKEN, APP_TOKEN.
"""

# ============================================================================
# Bootstrap — executa ANTES de qualquer import de terceiros.
# Garante que as dependências estão instaladas no Python que está rodando
# este script, independente de qual venv ou pip está no PATH do sistema.
# ============================================================================
import subprocess
import sys

def _bootstrap() -> None:
    _DEPS = {
        "requests":  "requests>=2.31.0",
        "pandas":    "pandas>=2.0.0",
        "openpyxl":  "openpyxl>=3.1.0",
        "dotenv":    "python-dotenv>=1.0.0",
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


def _modulo_ausente(nome: str) -> bool:
    try:
        __import__(nome)
        return False
    except ImportError:
        return True


_bootstrap()

# ============================================================================
# Imports (seguros após o bootstrap)
# ============================================================================
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
import re

import pandas as pd
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

HTTP_TIMEOUT = 30  # segundos

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

# Apenas estes status ficam na planilha; ausência = ticket foi resolvido/fechado
STATUSES_ATIVOS = frozenset({1, 2, 3, 4})

COLUNAS_EXCEL = [
    "ID do Chamado",
    "Título",
    "Status",
    "Tempo para Solução",
    "Data de Abertura",
    "Requerente",
]



# ============================================================================
# Configuração
# ============================================================================

def carregar_configuracoes() -> dict[str, Any]:
    """Lê .env, valida obrigatórias e retorna config normalizada."""
    load_dotenv()

    glpi_url = os.getenv("GLPI_URL") or os.getenv("VERDANADESK_URL")
    user_token = os.getenv("GLPI_USER_TOKEN") or os.getenv("USER_TOKEN")
    app_token = os.getenv("GLPI_APP_TOKEN") or os.getenv("APP_TOKEN")

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

    cat_raw = os.getenv("CATEGORIA_CONTRATACAO_IDS") or os.getenv("CATEGORIA_CONTRATACAO_IDS", "")
    categoria_ids = [c.strip() for c in cat_raw.split(",") if c.strip()]
    if not categoria_ids:
        logger.critical(
            "CATEGORIA_CONTRATACAO_IDS não definida no .env. "
            "Informe os IDs de categoria separados por vírgula (ex: 152,153)."
        )
        sys.exit(1)

    logger.info("Categorias de contratação configuradas: %s", categoria_ids)

    return {
        "GLPI_URL": glpi_url.rstrip("/"),
        "GLPI_USER_TOKEN": user_token,
        "GLPI_APP_TOKEN": app_token,
        "POLLING_INTERVAL": os.getenv("POLLING_INTERVAL", "300"),
        "EXCEL_PATH": os.getenv("EXCEL_PATH", "chamados_acompanhamento.xlsx"),
        "CATEGORIA_IDS": categoria_ids,
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
        self, base_url: str, app_token: str, user_token: str, categoria_ids: list[str]
    ) -> None:
        self.base_url = base_url
        self.app_token = app_token
        self.user_token = user_token
        self.categoria_ids = categoria_ids
        self.session_token: str | None = None
        self._session = requests.Session()
        self._cache_usuarios: dict[int, str] = {}
        self._iniciar_sessao()

    # --- Gerenciamento de sessão -------------------------------------------

    def _atualizar_headers(self) -> None:
        self._session.headers.clear()
        self._session.headers.update({
            "App-Token": self.app_token,
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

    # --- Endpoints de negócio -----------------------------------------------

    def buscar_chamados_ativos(self) -> list[dict[str, Any]]:
        """Busca chamados de contratação ativos, filtrando por categoria e status no servidor.

        Replica a lógica do código legado: itera sobre cada categoria configurada
        em CATEGORIA_CONTRATACAO_IDS e faz uma busca por categoria, excluindo os
        status Solucionado (5) e Fechado (6).

        forcedisplay garante que os campos de ID, título, status, prazo, data e
        requerente sejam sempre retornados, independente da view padrão do usuário.
        """
        PAGE_SIZE = 200
        # dict para deduplicar por ID caso um ticket apareça em duas categorias
        todos: dict[int, dict] = {}

        for cat_id in self.categoria_ids:
            offset = 0
            while True:
                partes = [
                    # Filtro de categoria no servidor (field 7 = Categoria do chamado)
                    # Filtro de status é feito em Python após receber os dados,
                    # pois o searchtype=notequals causa body vazio nesta versão do GLPI.
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
                        logger.info("Categoria %s: sem chamados ativos.", cat_id)
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

        A Search API às vezes não retorna o field 17 (time_to_resolve). Nesse caso,
        buscamos o conteúdo bruto do ticket via GET /Ticket/{id} e aplicamos regex
        para encontrar o padrão visual 'Data de inicio: DD-MM-YYYY' que o solicitante
        preenche no formulário do chamado.
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

    def buscar_nome_usuario(self, user_id: int) -> str:
        """Retorna nome completo do usuário GLPI, com cache em memória."""
        if user_id in self._cache_usuarios:
            return self._cache_usuarios[user_id]

        try:
            dados = self._get(f"{self.base_url}/User/{user_id}")
            firstname = dados.get("firstname", "")
            realname = dados.get("realname", "")
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
# Sincronizador Excel
# ============================================================================

class SincronizadorExcel:
    """
    Mantém chamados_acompanhamento.xlsx como fotografia do backlog ativo.

    Estratégia de sincronização:
    - Upsert: substitui linhas existentes, insere linhas novas.
    - Delete: remove IDs que não estão mais na resposta da API
      (foram resolvidos, fechados ou excluídos no GLPI).
    """

    def __init__(self, caminho: Path, glpi: ClienteGLPI) -> None:
        self.caminho = caminho
        self.glpi = glpi

    def _carregar_df(self) -> pd.DataFrame:
        if self.caminho.exists():
            try:
                return pd.read_excel(self.caminho, dtype={"ID do Chamado": int})
            except Exception as exc:
                logger.warning(
                    "Não foi possível ler a planilha existente (%s). Iniciando do zero.", exc
                )
        return pd.DataFrame(columns=COLUNAS_EXCEL)

    def _salvar_df(self, df: pd.DataFrame) -> bool:
        try:
            df.to_excel(self.caminho, index=False)
            return True
        except PermissionError:
            logger.warning(
                "Arquivo '%s' está aberto por outro processo. "
                "Atualização será refeita na próxima varredura.",
                self.caminho,
            )
            return False
        except Exception as exc:
            logger.error("Erro inesperado ao salvar planilha: %s", exc)
            return False

    def _chamado_para_linha(self, chamado: dict) -> dict | None:
        """Converte um ticket da API em linha do DataFrame.

        Aceita tanto o formato da Search API (chaves numéricas: "2", "1", "12"…)
        quanto o da API direta (chaves nomeadas: "id", "name", "status"…).
        """
        # ID: chave "2" na Search API, "id" na API direta
        id_raw = chamado.get("2") or chamado.get("id")
        if id_raw is None:
            return None
        try:
            ticket_id = int(id_raw)
        except (ValueError, TypeError):
            logger.debug("ID inválido: %s", id_raw)
            return None

        # Status
        try:
            status_id = int(chamado.get("12") or chamado.get("status") or 0)
        except (ValueError, TypeError):
            status_id = 0

        # Requerente: "4" na Search API, "_users_id_requester"/"users_id_requester" na direta
        requerente = ""
        req_raw = chamado.get("4") or chamado.get("_users_id_requester") or chamado.get("users_id_requester")
        if req_raw:
            try:
                uid = int(req_raw)
                if uid > 0:
                    requerente = self.glpi.buscar_nome_usuario(uid)
            except (ValueError, TypeError):
                requerente = str(req_raw)

        # Tempo para Solução: tenta o field 17 da Search API primeiro.
        # Se vier vazio, faz GET /Ticket/{id} e extrai "Data de início" do HTML do corpo.
        tempo_solucao = _formatar_datetime(chamado.get("17") or chamado.get("time_to_resolve"))
        if not tempo_solucao:
            tempo_solucao = self.glpi.buscar_data_inicio_do_conteudo(ticket_id)
            if tempo_solucao:
                logger.debug("Ticket #%d: 'Tempo para Solução' extraído do corpo.", ticket_id)

        return {
            "ID do Chamado": ticket_id,
            "Título": chamado.get("1") or chamado.get("name") or "",
            "Status": STATUS_MAP.get(status_id, f"Status {status_id}"),
            "Tempo para Solução": tempo_solucao,
            "Data de Abertura": _formatar_datetime(
                chamado.get("15") or chamado.get("date_creation")
            ),
            "Requerente": requerente,
        }

    def sincronizar(self, chamados_api: list[dict]) -> None:
        """Aplica upsert + remoção para manter a planilha fiel ao backlog ativo."""
        df_atual = self._carregar_df()

        linhas = [self._chamado_para_linha(c) for c in chamados_api]
        linhas = [l for l in linhas if l is not None]
        ids_ativos_api = {l["ID do Chamado"] for l in linhas}

        ids_anteriores: set[int] = (
            set(df_atual["ID do Chamado"].tolist()) if not df_atual.empty else set()
        )
        ids_para_remover = ids_anteriores - ids_ativos_api
        if ids_para_remover:
            logger.info(
                "Removendo %d chamado(s) resolvido(s)/fechado(s): %s",
                len(ids_para_remover), sorted(ids_para_remover),
            )

        # Remove linhas que serão re-inseridas (upsert) ou deletadas
        df_base = (
            df_atual[~df_atual["ID do Chamado"].isin(ids_ativos_api | ids_para_remover)]
            if not df_atual.empty
            else df_atual
        )

        df_novos = pd.DataFrame(linhas, columns=COLUNAS_EXCEL)
        df_final = (
            pd.concat([df_base, df_novos], ignore_index=True)
            .sort_values("ID do Chamado")
            .reset_index(drop=True)
        )

        inseridos = len(ids_ativos_api - ids_anteriores)
        atualizados = len(ids_ativos_api & ids_anteriores)

        if self._salvar_df(df_final):
            logger.info(
                "Planilha sincronizada: %d ativo(s) | +%d inserido(s) | ~%d atualizado(s) | -%d removido(s)",
                len(df_final), inseridos, atualizados, len(ids_para_remover),
            )


# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    config = carregar_configuracoes()
    polling_interval = int(config["POLLING_INTERVAL"])
    excel_path = Path(config["EXCEL_PATH"])

    logger.info(
        "GLPI→Excel Sync iniciado. Saída: '%s' | Ciclo: %ds (%d min).",
        excel_path, polling_interval, polling_interval // 60,
    )

    glpi = ClienteGLPI(
        base_url=config["GLPI_URL"],
        app_token=config["GLPI_APP_TOKEN"],
        user_token=config["GLPI_USER_TOKEN"],
        categoria_ids=config["CATEGORIA_IDS"],
    )
    sync = SincronizadorExcel(excel_path, glpi)

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
