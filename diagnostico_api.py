"""
diagnostico_api.py — fase 4: descobrir paths reais do v2.3.
Execute: python diagnostico_api.py
"""
import os, json, sys
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CLIENT_ID     = os.getenv("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
USERNAME      = os.getenv("OAUTH_USERNAME", "")
PASSWORD      = os.getenv("OAUTH_PASSWORD", "")

API_ROOT = "https://dexian.verdanadesk.com/api.php"
V23      = f"{API_ROOT}/v2.3"
TOKEN_URL = f"{API_ROOT}/token"

# ── Bearer token ──────────────────────────────────────────────────────────────
r = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET, "username": USERNAME,
    "password": PASSWORD, "scope": "api",
}, timeout=15)
bearer = r.json().get("access_token", "")
print(f"Bearer: {'OK' if bearer else 'FALHOU'}\n")
H = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}

def show(label, resp):
    try:
        body = json.dumps(resp.json(), ensure_ascii=False, indent=2)[:2000]
    except Exception:
        body = resp.text[:2000]
    print(f"[{resp.status_code}] {label}")
    print(body); print()

def get(url, params=None, extra=None):
    return requests.get(url, headers={**H, **(extra or {})}, params=params, timeout=10)

# ── 1. Buscar spec OpenAPI com auth ───────────────────────────────────────────
print("=== 1. OpenAPI spec com Bearer ===")
for path in ["/doc.json", "/swagger.json", "/openapi.json", "/api.json", "/doc/openapi.json"]:
    r2 = get(f"{V23}{path}")
    paths_count = "N/A"
    if r2.ok:
        try:
            data = r2.json()
            paths_count = str(list(data.get("paths", {}).keys())[:10])
        except Exception:
            pass
    print(f"  {r2.status_code} | {V23}{path} | paths={paths_count}")
print()

# ── 2. Muitas variações de nome de recurso ────────────────────────────────────
print("=== 2. Variações de recurso em v2.3 ===")
resources = [
    "Ticket", "ticket", "tickets", "Tickets",
    "Helpdesk", "helpdesk", "HelpDesk",
    "Issue", "issues", "Request", "requests",
    "TicketRequest", "ItilTicket", "ITIL",
    "User", "user", "users",
    "Profile", "Entity", "Category",
    "ITILCategory", "Status", "status",
    "me", "whoami", "self",
]
for res in resources:
    r3 = get(f"{V23}/{res}")
    if r3.status_code != 404:
        print(f"  *** {r3.status_code} | /{res} *** ← diferente de 404!")
    else:
        print(f"  {r3.status_code} | /{res}")
print()

# ── 3. Accept: application/vnd.api+json (JSON:API spec) ───────────────────────
print("=== 3. JSON:API content-type ===")
jsonapi_h = {"Authorization": f"Bearer {bearer}",
             "Accept": "application/vnd.api+json",
             "Content-Type": "application/vnd.api+json"}
for path in ["/Ticket", "/tickets", "/helpdesk"]:
    r4 = requests.get(f"{V23}{path}", headers=jsonapi_h, timeout=10)
    print(f"  {r4.status_code} | {path} (JSON:API) | {r4.text[:200]}")
print()

# ── 4. v2.3 doc HTML — tentar extrair URL do spec ────────────────────────────
print("=== 4. v2.3/doc HTML (procurando URL do spec) ===")
r5 = requests.get(f"{V23}/doc", headers=H, timeout=10)
print(f"  {r5.status_code} | content-type: {r5.headers.get('content-type', '?')}")
text = r5.text
# Procurar URLs de spec no HTML
import re
urls = re.findall(r'["\']([^"\']*(?:swagger|openapi|api\.json|spec)[^"\']*)["\']', text, re.I)
print(f"  URLs encontradas no HTML: {urls[:10]}")
# Procurar src de JS também
srcs = re.findall(r'src=["\']([^"\']+)["\']', text)
print(f"  Scripts: {srcs[:5]}")
print()

# ── 5. Tentar sem versão path mas com query param ─────────────────────────────
print("=== 5. Outros padrões ===")
show("GET /v2.3/Ticket?range=0-0", get(f"{V23}/Ticket", {"range": "0-0"}))
show("GET /v2.3 (raiz da versão)", get(f"{V23}"))
show("GET /v2.3/ (com barra)", get(f"{V23}/"))
