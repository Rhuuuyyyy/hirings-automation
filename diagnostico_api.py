"""
diagnostico_api.py — Script de diagnóstico da API Verdanadesk (fase 3).
Execute: python diagnostico_api.py
"""
import os, json, sys, base64
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CLIENT_ID     = os.getenv("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
USERNAME      = os.getenv("OAUTH_USERNAME", "")
PASSWORD      = os.getenv("OAUTH_PASSWORD", "")

API_ROOT = "https://dexian.verdanadesk.com/api.php"
V1       = f"{API_ROOT}/v1"
TOKEN_URL = f"{API_ROOT}/token"

# ── Helpers ───────────────────────────────────────────────────────────────────
def show(label, resp):
    try:
        body = json.dumps(resp.json(), ensure_ascii=False, indent=2)[:1500]
    except Exception:
        body = resp.text[:1500]
    print(f"  [{resp.status_code}] {label}")
    print(body)
    print()

def get(url, headers, params=None):
    return requests.get(url, headers=headers, params=params, timeout=10)

# ── 1. Obter Bearer token OAuth2 ─────────────────────────────────────────────
print("=== 1. Bearer token OAuth2 ===")
r = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET, "username": USERNAME,
    "password": PASSWORD, "scope": "api",
}, timeout=15)
bearer = r.json().get("access_token", "") if r.ok else ""
print(f"  Status: {r.status_code} | bearer obtido: {'SIM' if bearer else 'NÃO'}")
print()

# ── 2. v1 + App-Token = client_id + initSession com Basic auth ────────────────
print("=== 2. v1 — App-Token = client_id + Basic auth (username:password) ===")
b64 = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
h = {"App-Token": CLIENT_ID, "Authorization": f"Basic {b64}"}
show("GET /v1/initSession (Basic)", get(f"{V1}/initSession", h))

# ── 3. v1 + App-Token = client_secret + Basic auth ───────────────────────────
print("=== 3. v1 — App-Token = client_secret + Basic auth ===")
h = {"App-Token": CLIENT_SECRET, "Authorization": f"Basic {b64}"}
show("GET /v1/initSession (client_secret como App-Token)", get(f"{V1}/initSession", h))

# ── 4. v1 + App-Token = bearer como App-Token + Basic auth ───────────────────
print("=== 4. v1 — App-Token = Bearer JWT + Basic auth ===")
h = {"App-Token": bearer, "Authorization": f"Basic {b64}"}
show("GET /v1/initSession (Bearer como App-Token)", get(f"{V1}/initSession", h))

# ── 5. v1 + somente Bearer como header Authorization ─────────────────────────
print("=== 5. v1 — só Authorization: Bearer (sem App-Token) ===")
h = {"Authorization": f"Bearer {bearer}"}
show("GET /v1/Ticket (só Bearer)", get(f"{V1}/Ticket", h))

# ── 6. v1 + App-Token = client_id + Bearer (sem initSession) ─────────────────
print("=== 6. v1 — App-Token = client_id + Authorization: Bearer ===")
h = {"App-Token": CLIENT_ID, "Authorization": f"Bearer {bearer}"}
show("GET /v1/Ticket (client_id + Bearer)", get(f"{V1}/Ticket", h))

# ── 7. v1 + App-Token = client_secret + Bearer ───────────────────────────────
print("=== 7. v1 — App-Token = client_secret + Authorization: Bearer ===")
h = {"App-Token": CLIENT_SECRET, "Authorization": f"Bearer {bearer}"}
show("GET /v1/Ticket (client_secret + Bearer)", get(f"{V1}/Ticket", h))

# ── 8. Se algum initSession funcionou → usar o session_token em /v1/Ticket ───
print("=== 8. Fluxo completo: initSession com client_id como App-Token ===")
for app_tok_name, app_tok_val in [("client_id", CLIENT_ID), ("client_secret", CLIENT_SECRET)]:
    h_init = {"App-Token": app_tok_val, "Authorization": f"Basic {b64}"}
    ri = get(f"{V1}/initSession", h_init)
    if ri.ok:
        sess = ri.json().get("session_token")
        if sess:
            print(f"  initSession OK com App-Token={app_tok_name}, session_token={sess[:20]}...")
            h_api = {"App-Token": app_tok_val, "Session-Token": sess}
            show("GET /v1/Ticket (com session_token)",
                 get(f"{V1}/Ticket", h_api, params={"range": "0-4"}))
            show("GET /v1/search/Ticket",
                 get(f"{V1}/search/Ticket", h_api,
                     params={"criteria[0][field]": "2",
                             "criteria[0][searchtype]": "contains",
                             "criteria[0][value]": "",
                             "range": "0-4"}))
            break
    else:
        print(f"  initSession com App-Token={app_tok_name} → {ri.status_code}")
print()

# ── 9. v2.3 com scope api+user ────────────────────────────────────────────────
print("=== 9. OAuth2 scope=api+user e tentar /v2.3/Ticket ===")
r2 = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET, "username": USERNAME,
    "password": PASSWORD, "scope": "api user",
}, timeout=15)
if r2.ok:
    t2 = r2.json().get("access_token", "")
    show("GET /v2.3/Ticket (scope=api user)",
         get(f"{API_ROOT}/v2.3/Ticket",
             {"Authorization": f"Bearer {t2}", "Accept": "application/json"}))
else:
    print(f"  scope=api user falhou: {r2.status_code} {r2.text[:200]}")
