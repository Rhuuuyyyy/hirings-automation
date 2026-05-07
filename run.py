"""
run.py — Ponto de entrada único do Hub de Automações.

Instala dependências, sobe o worker GLPI em background e inicia o servidor web.

Uso:
    python run.py
"""

import subprocess
import sys

# ── 1. Garante dependências ───────────────────────────────────────────────────
print("[run] Verificando dependências...")
try:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
    )
except subprocess.CalledProcessError:
    print("[run] ERRO: falha ao instalar dependências. Verifique sua conexão.")
    sys.exit(1)

# ── 2. Imports (seguros após pip install) ────────────────────────────────────
import threading
import uvicorn
from automations.contratacoes.glpi_sync import main as glpi_main
from main import app

# ── 3. Worker GLPI em thread daemon ──────────────────────────────────────────
def _run_sync() -> None:
    glpi_main()

sync_thread = threading.Thread(target=_run_sync, daemon=True, name="glpi-sync")
sync_thread.start()
print("[run] Worker GLPI iniciado em background.")

# ── 4. Servidor web (bloqueia até Ctrl+C) ────────────────────────────────────
print("[run] Dashboard disponível em → http://localhost:8000")
print("[run] Pressione Ctrl+C para encerrar.\n")
uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
