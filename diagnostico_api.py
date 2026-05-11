"""
diagnostico_api.py — Script de diagnóstico da API Verdanadesk.
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
API_ROOT  = re.sub(r"/v[\d.]+$", "", API_URL)   # https://.../api.php

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
if not r.ok:
    print("ERRO:", r.text); sys.exit(1)
token = r.json().get("access_token")
print(f"Token OK: {token[:20]}...")
print()

H = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def get(label, url, params=None, extra_headers=None):
    hdrs = {**H, **(extra_headers or {})}
    resp = requests.get(url, headers=hdrs, params=params, timeout=10)
    try:
        body = json.dumps(resp.json(), ensure_ascii=False, indent=2)
    except Exception:
        body = resp.text
    print(f"--- {label}")
    print(f"    {resp.status_code} | {url}")
    if params:
        print(f"    params: {params}")
    print(body[:3000])
    print()

# ── 2. Raiz completa ──────────────────────────────────────────────────────────
print("=== 2. Raiz completa da API (ver todas as versões) ===")
get("GET /api.php/", f"{API_ROOT}/")

# ── 3. Testar v1 com Bearer token ─────────────────────────────────────────────
print("=== 3. API v1 com Bearer token ===")
get("GET /api.php/v1/",          f"{API_ROOT}/v1/")
get("GET /api.php/v1/Ticket",    f"{API_ROOT}/v1/Ticket")
get("GET /api.php/v1/search/Ticket (5 primeiros)",
    f"{API_ROOT}/v1/search/Ticket",
    {"criteria[0][field]": "2", "criteria[0][searchtype]": "contains",
     "criteria[0][value]": "", "range": "0-4"})

# ── 4. API v1 sem Bearer — testar se exige initSession ───────────────────────
print("=== 4. v1 sem auth ===")
r2 = requests.get(f"{API_ROOT}/v1/Ticket", timeout=10)
print(f"    {r2.status_code} | {r2.text[:400]}")
print()

# ── 5. Versão disponível da API v2.x ─────────────────────────────────────────
print("=== 5. Testar versões alternativas ===")
for ver in ["v2.0", "v2.1", "v2.2", "v2.3", "v2.4"]:
    resp = requests.get(f"{API_ROOT}/{ver}/Ticket", headers=H, timeout=8)
    print(f"    /api.php/{ver}/Ticket → {resp.status_code}")
print()

# ── 6. GraphQL ────────────────────────────────────────────────────────────────
print("=== 6. GraphQL ===")
gql_url = f"{API_URL}/graphql"
payload = {"query": "{ Ticket(limit: 3) { id name status } }"}
rg = requests.post(gql_url, headers={**H, "Content-Type": "application/json"},
                   json=payload, timeout=10)
print(f"    POST {gql_url} → {rg.status_code}")
print(f"    {rg.text[:600]}")
print()

# ── 7. v1 com initSession (para confirmar se v1 precisa de outro auth) ────────
print("=== 7. v1 initSession com Bearer ===")
get("initSession via Bearer",
    f"{API_ROOT}/v1/initSession",
    extra_headers={"Authorization": f"Bearer {token}"})
