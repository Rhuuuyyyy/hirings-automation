"""
usuarios_sync.py — Análise de inventário: usuários × máquinas no Verdanadesk.

Três análises produzidas:
    1. inativos-maquinas   — usuários inativos (is_active=0) com computadores atrelados
    2. cc-divergente       — usuário e computador com locations_id diferentes
    3. multi-responsaveis  — computadores com users_id E users_id_tech distintos

Reutiliza ClienteGLPI (OAuth2) de glpi_sync para não duplicar autenticação.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DB_USUARIOS   = Path("database/usuarios_analise.json")
_PAGE_SIZE     = 500
_HTTP_TIMEOUT  = 30
_SYNC_RUNNING  = False   # flag simples para evitar duplo clique


# ── URL helpers ───────────────────────────────────────────────────────────────

def _verdana_base() -> str:
    """Deriva o base URL do Verdanadesk a partir de API_URL (antes de /api.php)."""
    api_url = os.getenv("API_URL", "")
    idx = api_url.find("/api.php")
    return api_url[:idx] if idx != -1 else api_url.rstrip("/")

def _user_url(uid: int) -> str:
    return f"{_verdana_base()}/front/user.form.php?id={uid}"

def _computer_url(cid: int) -> str:
    return f"{_verdana_base()}/front/computer.form.php?id={cid}"


# ── Field helpers ─────────────────────────────────────────────────────────────

def _user_name(u: dict) -> str:
    fn = (u.get("firstname") or "").strip()
    ln = (u.get("realname")  or "").strip()
    return f"{fn} {ln}".strip() or u.get("name") or u.get("login") or f"#{u.get('id','?')}"

def _is_inactive(u: dict) -> bool:
    """Retorna True se o usuário está inativo (is_active == 0 / 'Não' / False)."""
    val = u.get("is_active", u.get("active"))
    if val is None:
        return False
    if isinstance(val, bool):
        return not val
    if isinstance(val, int):
        return val == 0
    return str(val).lower() in ("0", "não", "nao", "false", "no", "inativo")

def _extract_id(obj_or_id: Any) -> int | None:
    """Extrai ID de um campo que pode ser int ou {'id': N, 'name': '...'}."""
    if obj_or_id is None:
        return None
    if isinstance(obj_or_id, dict):
        v = obj_or_id.get("id")
        return int(v) if v else None
    try:
        v = int(obj_or_id)
        return v if v else None
    except (ValueError, TypeError):
        return None

def _extract_cc(obj: dict) -> tuple[str | None, str | None]:
    """
    Retorna (cc_id, cc_name) do campo de localização/centro de custo.
    Tenta: locations_id, location_id, location.
    """
    for field in ("locations_id", "location_id", "location"):
        raw = obj.get(field)
        if raw is None:
            continue
        if isinstance(raw, dict):
            fid = raw.get("id")
            fname = raw.get("completename") or raw.get("name") or ""
            if fid:
                return str(fid), fname
        else:
            try:
                v = int(raw)
                if v:
                    return str(v), ""
            except (ValueError, TypeError):
                pass
    return None, None


# ── Paginação ─────────────────────────────────────────────────────────────────

def _paginar(session: requests.Session, base_url: str, path: str, renovar_cb) -> list[dict]:
    """
    Faz GET paginado com retry de auth (401 → renovar → repetir).
    `renovar_cb` é a função _renovar_sessao() do ClienteGLPI.
    """
    items: list[dict] = []
    start = 0
    url = f"{base_url}/{path.lstrip('/')}"

    while True:
        params = {"start": start, "limit": _PAGE_SIZE}
        resp = session.get(url, params=params, timeout=_HTTP_TIMEOUT)

        if resp.status_code == 401:
            renovar_cb()
            resp = session.get(url, params=params, timeout=_HTTP_TIMEOUT)

        if not resp.ok:
            logger.error("GET falhou [%s] %s — %s", url, resp.status_code, resp.text[:200])
            break

        if not resp.text.strip():
            break

        batch = resp.json()
        if isinstance(batch, dict):
            batch = batch.get("items", [])
        if not isinstance(batch, list) or not batch:
            break

        items.extend(batch)

        content_range = resp.headers.get("Content-Range", "")
        total = int(content_range.split("/")[-1]) if "/" in content_range else 0

        if total > 0 and start + len(batch) >= total:
            break
        if len(batch) < _PAGE_SIZE:
            break

        start += len(batch)

    return items


# ── Analisador ────────────────────────────────────────────────────────────────

class AnalisadorUsuarios:
    def __init__(self, glpi) -> None:
        """glpi: instância de ClienteGLPI (de glpi_sync.py)."""
        self._session    = glpi._session
        self._base_url   = glpi.base_url
        self._renovar    = glpi._renovar_sessao

    def _get_all(self, path: str) -> list[dict]:
        return _paginar(self._session, self._base_url, path, self._renovar)

    def analisar(self) -> dict:
        logger.info("Análise de usuários: iniciando varredura…")

        usuarios_raw    = self._get_all("Administration/User")
        computadores_raw = self._get_all("Assets/Computer")

        logger.info("Usuários obtidos: %d | Computadores: %d",
                    len(usuarios_raw), len(computadores_raw))

        # Log field keys once (for debugging unknown environments)
        if usuarios_raw:
            logger.debug("User[0] keys: %s", sorted(usuarios_raw[0].keys()))
        if computadores_raw:
            logger.debug("Computer[0] keys: %s", sorted(computadores_raw[0].keys()))

        # Mapas em memória
        user_map: dict[int, dict] = {}
        for u in usuarios_raw:
            uid = _extract_id(u.get("id"))
            if uid:
                user_map[uid] = u

        comp_map: dict[int, dict] = {}
        for c in computadores_raw:
            cid = _extract_id(c.get("id"))
            if cid:
                comp_map[cid] = c

        # Relacionamentos: user_id → [comp_ids] e comp_id → [user_ids]
        user_to_comps: dict[int, list[int]] = {}
        comp_to_users: dict[int, list[int]] = {}

        for cid, comp in comp_map.items():
            for field in ("users_id", "users_id_tech"):
                uid = _extract_id(comp.get(field))
                if uid and uid in user_map:
                    user_to_comps.setdefault(uid, [])
                    comp_to_users.setdefault(cid, [])
                    if cid not in user_to_comps[uid]:
                        user_to_comps[uid].append(cid)
                    if uid not in comp_to_users[cid]:
                        comp_to_users[cid].append(uid)

        # ── 1. Inativos com máquinas ──────────────────────────────────────────
        inativos: list[dict] = []
        for uid, comp_ids in user_to_comps.items():
            u = user_map.get(uid)
            if not u or not _is_inactive(u):
                continue
            for cid in comp_ids:
                comp = comp_map.get(cid)
                if not comp:
                    continue
                _, cc_name = _extract_cc(u)
                inativos.append({
                    "user":       _user_name(u),
                    "userId":     str(uid),
                    "userUrl":    _user_url(uid),
                    "machine":    comp.get("name") or f"Computer #{cid}",
                    "machineId":  str(cid),
                    "machineUrl": _computer_url(cid),
                    "dept":       cc_name or "",
                })

        # ── 2. Centro de custo divergente ─────────────────────────────────────
        cc_div: list[dict] = []
        for uid, comp_ids in user_to_comps.items():
            u = user_map.get(uid)
            if not u:
                continue
            ucc_id, ucc_name = _extract_cc(u)
            if not ucc_id:
                continue
            for cid in comp_ids:
                comp = comp_map.get(cid)
                if not comp:
                    continue
                mcc_id, mcc_name = _extract_cc(comp)
                if not mcc_id or mcc_id == ucc_id:
                    continue
                cc_div.append({
                    "user":        _user_name(u),
                    "userId":      str(uid),
                    "userUrl":     _user_url(uid),
                    "userCC":      ucc_id,
                    "userCCName":  ucc_name,
                    "machine":     comp.get("name") or f"Computer #{cid}",
                    "machineId":   str(cid),
                    "machineUrl":  _computer_url(cid),
                    "machineCC":   mcc_id,
                    "machineCCName": mcc_name,
                })

        # ── 3. Múltiplos responsáveis ──────────────────────────────────────────
        multi: list[dict] = []
        for cid, uids in comp_to_users.items():
            if len(uids) < 2:
                continue
            comp = comp_map.get(cid)
            if not comp:
                continue
            owners = [
                {"name": _user_name(user_map[uid]), "userId": str(uid), "userUrl": _user_url(uid)}
                for uid in uids
                if uid in user_map
            ]
            if len(owners) >= 2:
                multi.append({
                    "machine":    comp.get("name") or f"Computer #{cid}",
                    "machineId":  str(cid),
                    "machineUrl": _computer_url(cid),
                    "owners":     owners,
                })

        logger.info("Resultados — inativos: %d | cc_div: %d | multi_resp: %d",
                    len(inativos), len(cc_div), len(multi))

        return {
            "ultima_atualizacao":  datetime.now().isoformat(),
            "inativos-maquinas":   inativos,
            "cc-divergente":       cc_div,
            "multi-responsaveis":  multi,
        }


# ── Persistência ──────────────────────────────────────────────────────────────

def salvar(dados: dict) -> None:
    _DB_USUARIOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DB_USUARIOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_DB_USUARIOS)


def executar(glpi) -> dict:
    """Roda a análise completa e persiste. Retorna os dados."""
    global _SYNC_RUNNING
    if _SYNC_RUNNING:
        logger.warning("Análise já em execução, ignorando chamada duplicada.")
        return {}
    _SYNC_RUNNING = True
    try:
        dados = AnalisadorUsuarios(glpi).analisar()
        salvar(dados)
        return dados
    finally:
        _SYNC_RUNNING = False


def is_running() -> bool:
    return _SYNC_RUNNING
