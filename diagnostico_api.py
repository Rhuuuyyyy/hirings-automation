"""
diagnostico_api.py — fase 6: listar TODOS os paths e testar Helpdesk/Ticket.
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
TOKEN_URL = f"{API_ROOT}/token"

r = requests.post(TOKEN_URL, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET, "username": USERNAME,
    "password": PASSWORD, "scope": "api",
}, timeout=15)
bearer = r.json().get("access_token", "")
H = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}

# ── 1. TODOS os paths do doc.json ─────────────────────────────────────────────
print("=== 1. TODOS os paths disponíveis na v2.3 ===")
spec = requests.get(f"{V23}/doc.json", headers=H, timeout=15).json()
all_paths = list(spec.get("paths", {}).keys())
print(f"Total de paths: {len(all_paths)}\n")

# Filtrar paths com palavras-chave relevantes
keywords = ["ticket", "helpdesk", "assistance", "itil", "support", "chamado", "request", "incident"]
print("--- Paths que contêm palavras-chave relevantes:")
for p in all_paths:
    if any(k in p.lower() for k in keywords):
        print(f"  {p}")

print("\n--- Todos os paths (agrupados por prefixo):")
prefixes = {}
for p in all_paths:
    parts = p.strip("/").split("/")
    prefix = parts[0] if parts else "/"
    prefixes.setdefault(prefix, []).append(p)
for prefix, paths in sorted(prefixes.items()):
    print(f"\n  [{prefix}]")
    for p in paths[:5]:  # primeiros 5 de cada grupo
        print(f"    {p}")
    if len(paths) > 5:
        print(f"    ... (+{len(paths)-5} mais)")

print()

# ── 2. Testar os paths mais prováveis para Ticket ─────────────────────────────
print("=== 2. Testar endpoints de Ticket ===")
candidates = [
    "/Helpdesk/Ticket",
    "/Helpdesk/Tickets",
    "/Helpdesk/ticket",
    "/Assistance/Ticket",
    "/Assistance/ticket",
    "/ITIL/Ticket",
    "/itil/ticket",
    "/Support/Ticket",
    "/helpdesk/Ticket",
]
# Adicionar qualquer path do spec que contenha "ticket"
for p in all_paths:
    if "ticket" in p.lower() and p not in candidates:
        candidates.append(p)

for path in candidates:
    resp = requests.get(f"{V23}{path}", headers=H, timeout=8)
    marker = "  *** FUNCIONOU! ***" if resp.ok else ""
    try:
        body = resp.json()
        detail = str(body)[:120]
    except Exception:
        detail = resp.text[:120]
    print(f"  {resp.status_code} | {path}{marker}")
    if resp.ok:
        print(f"    {detail}")
print()

# ── 3. Testar com os headers GLPI-Profile e GLPI-Entity ───────────────────────
print("=== 3. Testar /Helpdesk/Ticket com GLPI-Profile e GLPI-Entity ===")
# Profile 10 = Atendimento - TI, Entity 0 = Dexian Brasil
H_with_profile = {**H, "GLPI-Profile": "10", "GLPI-Entity": "0"}
for path in ["/Helpdesk/Ticket", "/Ticket", "/helpdesk/ticket"]:
    resp = requests.get(f"{V23}{path}", headers=H_with_profile, timeout=8)
    try:
        body = str(resp.json())[:200]
    except Exception:
        body = resp.text[:200]
    print(f"  {resp.status_code} | {path} (com GLPI-Profile=10)")
    if resp.ok:
        print(f"    {body}")
print()

# ── 4. Mostrar prefixos únicos de top-level para referência ──────────────────
print("=== 4. Top-level prefixos disponíveis na API ===")
for prefix in sorted(prefixes.keys()):
    count = len(prefixes[prefix])
    print(f"  /{prefix}  ({count} endpoint{'s' if count>1 else ''})")
