"""
diagnostico_api.py — Script temporário para descobrir o formato correto
da API Verdanadesk v2.3.

Execute: python diagnostico_api.py
Requer o .env configurado com API_URL, OAUTH_* etc.
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

print(f"API_URL   : {API_URL}")
print(f"TOKEN_URL : {TOKEN_URL}")
print()

# ── 1. Autenticar ─────────────────────────────────────────────────────────────
print("=== 1. Obtendo token OAuth2 ===")
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
print(f"Token obtido: {token[:20]}...{token[-10:]}")
print()

headers = {"Authorization": f"Bearer {token}"}

def get(path, params=None):
    url = f"{API_URL}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    print(f"  GET {url}")
    if params:
        print(f"  Params: {params}")
    print(f"  Status: {resp.status_code} | {len(resp.content)} bytes")
    try:
        data = resp.json()
        print(f"  Body (primeiras chaves): {list(data.keys()) if isinstance(data, dict) else f'lista com {len(data)} items'}")
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
            print(f"  data[0] chaves: {list(items[0].keys()) if items else '(vazio)'}")
        elif isinstance(data, list) and data:
            print(f"  item[0] chaves: {list(data[0].keys())}")
        print(f"  Resposta completa:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1500]}")
    except Exception:
        print(f"  Texto: {resp.text[:500]}")
    print()
    return resp

# ── 2. Testar endpoints de Ticket ─────────────────────────────────────────────
print("=== 2. GET /Ticket (sem filtro, primeiros 5) ===")
get("/Ticket", {"range": "0-4"})

print("=== 3. GET /Ticket com filter RSQL itilcategories_id==166 ===")
get("/Ticket", {"filter": "itilcategories_id==166", "range": "0-4"})

print("=== 4. GET /Ticket com query param direto ===")
get("/Ticket", {"itilcategories_id": "166", "range": "0-4"})

print("=== 5. GET /search/Ticket (formato v1 — esperado 404) ===")
get("/search/Ticket", {"criteria[0][field]": "7", "criteria[0][searchtype]": "equals", "criteria[0][value]": "166"})

print("=== 6. GET /Ticket/166 (ticket específico, se existir) ===")
get("/Ticket/166")

print("=== 7. Listar endpoints disponíveis na raiz ===")
get("/")
