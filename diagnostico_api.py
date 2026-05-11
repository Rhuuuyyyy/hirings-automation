"""
diagnostico_api.py — fase 5: entender /{req} e /session da v2.3.
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

API_ROOT  = "https://dexian.verdanadesk.com/api.php"
V23       = f"{API_ROOT}/v2.3"
V1        = f"{API_ROOT}/v1"
TOKEN_URL = f"{API_ROOT}/token"

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
        body = json.dumps(resp.json(), ensure_ascii=False, indent=2)
    except Exception:
        body = resp.text
    print(f"[{resp.status_code}] {label}")
    print(body[:3000]); print()

# ── 1. doc.json completo — ver definição de /{req} e /session ─────────────────
print("=== 1. doc.json completo (paths e definição de /{req}) ===")
r2 = requests.get(f"{V23}/doc.json", headers=H, timeout=15)
if r2.ok:
    spec = r2.json()
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        print(f"\n  PATH: {path}")
        for method, details in methods.items():
            print(f"    {method.upper()}: {details.get('summary','')}")
            params = details.get("parameters", [])
            for p in params:
                print(f"      param: {p.get('name')} ({p.get('in')}) required={p.get('required')}")
            resp_codes = list(details.get("responses", {}).keys())
            print(f"      responses: {resp_codes}")
else:
    print(f"  {r2.status_code}: {r2.text[:200]}")
print()

# ── 2. GET /v2.3/session ───────────────────────────────────────────────────────
print("=== 2. GET /v2.3/session ===")
show("GET /session", requests.get(f"{V23}/session", headers=H, timeout=10))

# ── 3. POST /v2.3/session ─────────────────────────────────────────────────────
print("=== 3. POST /v2.3/session ===")
show("POST /session", requests.post(f"{V23}/session", headers=H, timeout=10))

# ── 4. /{req} com valor real — será que é um proxy para v1? ──────────────────
print("=== 4. /{req} como proxy v1 — testar paths que funcionariam no v1 ===")
for path in ["Ticket", "search/Ticket", "getMyProfiles", "User/2"]:
    show(f"GET /{path}", requests.get(f"{V23}/{path}", headers=H, timeout=10))

# ── 5. Status scope separado ──────────────────────────────────────────────────
print("=== 5. scope=status ===")
rt = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET, "username": USERNAME,
    "password": PASSWORD, "scope": "status",
}, timeout=15)
if rt.ok:
    tok2 = rt.json().get("access_token", "")
    H2 = {"Authorization": f"Bearer {tok2}"}
    show("GET /status (scope=status)", requests.get(f"{V23}/status", headers=H2, timeout=10))
else:
    print(f"  scope=status falhou: {rt.status_code}")

# ── 6. v1 com Bearer como user_token (não como App-Token) ────────────────────
print("=== 6. v1 initSession: App-Token=client_id + user_token=Bearer ===")
show("initSession user_token=bearer",
     requests.get(f"{V1}/initSession",
                  headers={"App-Token": CLIENT_ID,
                           "Authorization": f"user_token {bearer}"},
                  timeout=10))
