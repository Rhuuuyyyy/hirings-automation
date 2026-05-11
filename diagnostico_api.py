"""
diagnostico_api.py — fase 7: campos, filtros e tasks de /Assistance/Ticket.
Execute: python diagnostico_api.py
"""
import os, json
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CLIENT_ID     = os.getenv("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
USERNAME      = os.getenv("OAUTH_USERNAME", "")
PASSWORD      = os.getenv("OAUTH_PASSWORD", "")

BASE      = "https://dexian.verdanadesk.com/api.php/v2.3"
TOKEN_URL = "https://dexian.verdanadesk.com/api.php/token"

r = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "username": USERNAME, "password": PASSWORD, "scope": "api",
}, timeout=15)
bearer = r.json().get("access_token", "")
H = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}

def get(url, params=None):
    resp = requests.get(url, headers=H, params=params, timeout=15)
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    return resp.status_code, body

# ── 1. Ticket único — ver TODOS os campos ─────────────────────────────────────
print("=== 1. Campos completos de um ticket ===")
status, tickets = get(f"{BASE}/Assistance/Ticket", {"limit": 1})
if isinstance(tickets, list) and tickets:
    ticket = tickets[0]
    print(f"Campos disponíveis ({len(ticket)} campos):")
    for k, v in ticket.items():
        val = str(v)[:80] if not isinstance(v, dict) else json.dumps(v)[:80]
        print(f"  {k}: {val}")
    first_id = ticket.get("id")
else:
    print(f"  {status}: {str(tickets)[:200]}")
    first_id = None
print()

# ── 2. Filtro por categoria ────────────────────────────────────────────────────
print("=== 2. Filtros por itilcategories_id ===")
cat_id = "166"
for f in [
    f"itilcategories_id=={cat_id}",
    f"itilcategories_id={cat_id}",
    f"category=={cat_id}",
]:
    s, b = get(f"{BASE}/Assistance/Ticket", {"filter": f, "limit": 2})
    count = len(b) if isinstance(b, list) else "?"
    print(f"  filter={f!r} → {s} | {count} resultado(s)")
    if isinstance(b, list) and b:
        print(f"    primeiro: id={b[0].get('id')} cat={b[0].get('itilcategories_id')}")
print()

# ── 3. Filtro por status ───────────────────────────────────────────────────────
print("=== 3. Filtro por status ativo (status != fechado) ===")
for f in ["status=in=(1,2,3,4)", "status!=6", "is_deleted==false"]:
    s, b = get(f"{BASE}/Assistance/Ticket", {"filter": f, "limit": 1})
    count = len(b) if isinstance(b, list) else "?"
    print(f"  filter={f!r} → {s} | {count} resultado(s)")
print()

# ── 4. Paginação ──────────────────────────────────────────────────────────────
print("=== 4. Paginação (start + limit) ===")
s, b = get(f"{BASE}/Assistance/Ticket", {"start": 0, "limit": 3})
print(f"  start=0 limit=3 → {s} | {len(b) if isinstance(b, list) else '?'} itens")

# Cabeçalhos de paginação
resp_full = requests.get(f"{BASE}/Assistance/Ticket", headers=H, params={"limit": 1}, timeout=15)
print(f"  Headers de paginação:")
for h in ["Content-Range", "X-Total-Count", "Accept-Ranges", "total-count"]:
    print(f"    {h}: {resp_full.headers.get(h, '(ausente)')}")
print()

# ── 5. Timeline/Task de um ticket ─────────────────────────────────────────────
if first_id:
    print(f"=== 5. Timeline/Task do ticket #{first_id} ===")
    s, b = get(f"{BASE}/Assistance/Ticket/{first_id}/Timeline/Task")
    print(f"  Status: {s} | tipo: {type(b).__name__}")
    if isinstance(b, list) and b:
        print(f"  Primeira tarefa:")
        for k, v in b[0].items():
            print(f"    {k}: {str(v)[:80]}")
    elif isinstance(b, list):
        print("  (lista vazia)")
    else:
        print(f"  {str(b)[:300]}")
    print()

    # Também testar o ticket diretamente pelo ID
    print(f"=== 6. GET /Assistance/Ticket/{first_id} ===")
    s, b = get(f"{BASE}/Assistance/Ticket/{first_id}")
    print(f"  Status: {s}")
    if isinstance(b, dict):
        for k, v in b.items():
            print(f"  {k}: {str(v)[:80]}")
    print()

# ── 7. User lookup ────────────────────────────────────────────────────────────
print("=== 7. Lookup de usuário via /Administration/User ===")
s, b = get(f"{BASE}/Administration/User/Me")
print(f"  /Administration/User/Me → {s}")
if isinstance(b, dict):
    print(f"  id={b.get('id')} name={b.get('name')} firstname={b.get('firstname')} realname={b.get('realname')}")
