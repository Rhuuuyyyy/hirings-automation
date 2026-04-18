"""
run.py — Entrypoint seguro para o hirings-automation.

Este script atua como um 'Bootstrap'. Ele valida as condições do ambiente de
execução (versão do Python, dependências e configurações) de forma antecipada
(Fail-Fast) antes de delegar a execução para o worker principal (automation.py).
"""

import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuração de Logging do Launcher
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | LAUNCHER | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Launcher")


def _auditar_ambiente_execucao() -> None:
    """
    Executa verificações de segurança e sanidade do ambiente.
    Encerra o programa (sys.exit) caso encontre condições impeditivas.
    """
    # 1. Validação da versão do Python (Exige 3.10+ devido aos Type Hints)
    if sys.version_info < (3, 10):
        logger.critical(
            "Versão incompatível. O Python 3.10 ou superior é estritamente necessário. "
            "Versão detectada: %s",
            sys.version.split()[0],
        )
        sys.exit(1)

    # 2. Validação da existência do arquivo de configuração
    env_path = Path(".env")
    if not env_path.is_file():
        logger.critical(
            "Arquivo '.env' não localizado. Ele é vital para as credenciais da automação. "
            "Crie um arquivo .env na raiz do projeto conforme a documentação."
        )
        sys.exit(1)


def main() -> None:
    """Ponto de entrada principal."""
    logger.info("Iniciando auditoria de pré-requisitos do ambiente...")
    _auditar_ambiente_execucao()
    logger.info("Ambiente validado com sucesso. Carregando dependências de automação...")

    # 3. Validação de Dependências / VENV
    try:
        import automation
    except ModuleNotFoundError as exc:
        logger.critical("Falha ao importar as dependências de negócio: %s", exc)
        logger.info("DICA: Verifique se o seu Ambiente Virtual (.venv) está ativo e as bibliotecas instaladas.")
        sys.exit(1)
    except Exception as exc:
        logger.critical("Erro inesperado ao inicializar os módulos da automação: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("Delegando execução para o motor principal (automation.py)...")
    logger.info("-" * 60)

    # 4. Execução protegida do Worker Principal
    try:
        automation.main()
    except KeyboardInterrupt:
        # Tratamento gracioso para quando o usuário apertar Ctrl+C
        print("") # Quebra de linha limpa no terminal
        logger.info("Sinal de interrupção (Ctrl+C) recebido. Encerrando worker de forma segura e imediata.")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Falha catastrófica não tratada pelo worker principal: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
