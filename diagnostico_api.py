"""
diagnostico_api.py — Script de diagnóstico da API Verdanadesk v2.3.
Execute: python diagnostico_api.py
"""
import os, json, sys
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

API_URL       = os.getenv("API_URL", "").rstrip("/")
CLIENT_ID     = os.getenv("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
USERNAME      = os.getenv("OAUTH_USERNAME", "")
PASSWORD      = os.getenv("OAUTH_PASSWORD", "")

import re
TOKEN_URL = re.sub(r"/v[\d.]+$", "/token", API_URL)
BASE       = re.sub(r"/api\.php.*$", "", API_URL)   # https://dexian.verdanadesk.com
API_ROOT   = re.sub(r"/v[\d.]+$", "", API_URL)      # https://dexian.verdanadesk.com/api.php

print(f"API_URL  : {API_URL}")
print(f"BASE     : {BASE}")
print(f"API_ROOT : {API_ROOT}")
print(f"TOKEN_URL: {TOKEN_URL}")
print()

# ── 1. Autenticar ─────────────────────────────────────────────────────────────
print("=== 1. OAuth2 ===")
r = requests.post(TOKEN_URL, data={
    "grant_type":    "password",
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "username":      USERNAME,
    "password":      PASSWORD,
    "scope":         "api",
}, timeout=15)
print(f"Status: {r.status_code}")
if not r.ok:
    print("ERRO:", r.text); sys.exit(1)
token = r.json().get("access_token")
print(f"Token: {token[:20]}...")
print()

H = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def test(label, url, params=None, method="GET"):
    print(f"--- {label}")
    try:
        if method == "GET":
            resp = requests.get(url, headers=H, params=params, timeout=10)
        else:
            resp = requests.options(url, headers=H, timeout=10)
        body = resp.text[:600]
        try:
            body = json.dumps(resp.json(), ensure_ascii=False)[:600]
        except Exception:
            pass
        print(f"    {resp.status_code} | {url}" + (f"?{params}" if params else ""))
        print(f"    {body}")
    except Exception as e:
        print(f"    ERRO: {e}")
    print()

# ── 2. Explorar base URL sem versão ───────────────────────────────────────────
print("=== 2. Variações de base URL ===")
test("api.php raiz",             f"{API_ROOT}/")
test("api.php sem versão /Ticket", f"{API_ROOT}/Ticket")
test("api.php /v2/Ticket",       f"{API_ROOT}/v2/Ticket")
test("api.php /v2.3/Ticket",     f"{API_ROOT}/v2.3/Ticket")

# ── 3. Variações de nome de recurso ───────────────────────────────────────────
print("=== 3. Variações de nome de recurso ===")
test("ticket (minúsculo)",       f"{API_URL}/ticket")
test("tickets (plural)",         f"{API_URL}/tickets")
test("helpdesk",                 f"{API_URL}/helpdesk")
test("Ticket",                   f"{API_URL}/Ticket")
test("ITILCategory",             f"{API_URL}/ITILCategory")

# ── 4. Sem o bearer — ver se muda o erro ─────────────────────────────────────
print("=== 4. Sem Authorization header ===")
r2 = requests.get(f"{API_URL}/Ticket", timeout=10)
print(f"    {r2.status_code} | {r2.text[:300]}")
print()

# ── 5. OPTIONS para ver métodos permitidos ────────────────────────────────────
print("=== 5. OPTIONS /Ticket ===")
r3 = requests.options(f"{API_URL}/Ticket", headers=H, timeout=10)
print(f"    Status: {r3.status_code}")
print(f"    Allow: {r3.headers.get('Allow', '(vazio)')}")
print(f"    Body: {r3.text[:300]}")
print()

# ── 6. Tentar endpoint de usuário atual (me / User) ──────────────────────────
print("=== 6. Endpoints de usuário (para confirmar auth funciona) ===")
test("User (minha conta)",  f"{API_URL}/User/me")
test("User sem ID",         f"{API_URL}/User")
test("getMyProfiles",       f"{API_URL}/getMyProfiles")
test("getActiveProfile",    f"{API_URL}/getActiveProfile")

# ── 7. Token info ─────────────────────────────────────────────────────────────
print("=== 7. Tentar obter info do token ===")
test("token info", f"{BASE}/api.php/token/info")
test("introspect",  f"{BASE}/api.php/token/introspect")
