"""
run.py — Entrypoint automatizado e seguro para o hirings-automation.

Este script atua como um 'Bootstrap' completo. Ele configura o ambiente
virtual (.venv), instala as dependências automaticamente caso não existam,
valida as configurações (.env) e executa o worker principal (automation.py).
Ideal para rodar em um computador novo com o mínimo de esforço.
"""

import logging
import os
import sys
import subprocess
import venv
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

# Dependências obrigatórias do projeto (Atualizado para o ecossistema Google Gemini)
DEPENDENCIAS = [
    "requests",
    "pydantic",
    "langchain-core",
    "langchain-google-genai",
    "python-dotenv"
]

VENV_DIR = ".venv"


def _em_ambiente_virtual() -> bool:
    """Verifica se o script está rodando dentro de um ambiente virtual."""
    return sys.prefix != sys.base_prefix


def _dependencias_instaladas() -> bool:
    """Tenta importar as bibliotecas essenciais para verificar se já estão instaladas."""
    try:
        import requests
        import pydantic
        import dotenv
        import langchain_google_genai  # <-- Adicione esta linha!
        return True
    except ImportError:
        return False


def _configurar_e_reiniciar() -> None:
    """Cria o ambiente virtual (se necessário), instala dependências e reinicia."""
    em_venv = _em_ambiente_virtual()
    
    if not em_venv:
        logger.info("Ambiente virtual não detectado. Iniciando configuração automática...")
        # 1. Criar o .venv se não existir
        if not os.path.exists(VENV_DIR):
            logger.info("Criando a pasta do ambiente virtual (%s)...", VENV_DIR)
            venv.create(VENV_DIR, with_pip=True)

        # 2. Descobrir o caminho do Python dentro do .venv (Windows vs Linux/Mac)
        if os.name == "nt":
            python_exe = os.path.join(VENV_DIR, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(VENV_DIR, "bin", "python")
    else:
        logger.info("Ambiente virtual detectado, mas faltam bibliotecas. Baixando...")
        python_exe = sys.executable

    # 3. Atualizar pip e instalar dependências
    logger.info("Instalando dependências necessárias. Isso pode levar alguns segundos...")
    try:
        subprocess.check_call([python_exe, "-m", "pip", "install", "--upgrade", "pip", "-q"])
        subprocess.check_call([python_exe, "-m", "pip", "install", "-q"] + DEPENDENCIAS)
    except subprocess.CalledProcessError:
        logger.critical("Erro ao instalar dependências. Verifique sua conexão com a internet.")
        sys.exit(1)

    logger.info("Configuração concluída! Reiniciando a automação...\n")
    logger.info("-" * 60)

    # 4. Reiniciar o próprio script usando o Python correto
    sys.exit(subprocess.run([python_exe] + sys.argv).returncode)


def _auditar_configuracoes() -> None:
    """Verifica versão do Python e cria arquivo .env se estiver faltando."""
    if sys.version_info < (3, 10):
        logger.critical(
            "Versão incompatível. O Python 3.10 ou superior é estritamente necessário. "
            "Versão detectada: %s",
            sys.version.split()[0],
        )
        sys.exit(1)

    env_path = Path(".env")
    if not env_path.is_file():
        logger.warning("Arquivo '.env' não encontrado. Criando um modelo padrão para você...")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("VERDANADESK_URL=https://sua-empresa.verdanadesk.com/apirest.php\n")
            f.write("USER_TOKEN=seu_user_token_aqui\n")
            f.write("APP_TOKEN=seu_app_token_aqui\n")
            # Chave alocada de forma segura no arquivo de configuração local
            f.write("GOOGLE_API_KEY=AIzaSyDAKI9N7YsY0M6aLneZRyYW3XtZyuQFO0I\n")
            f.write("CATEGORIA_CONTRATACAO_IDS=152,153\n")
        logger.critical("O arquivo '.env' foi criado com credenciais de base.")
        logger.critical("Por favor, valide as configurações no arquivo '.env' e rode este script novamente.")
        sys.exit(1)


def main() -> None:
    """Ponto de entrada principal."""
    # Passo 1: Autoconfiguração (Se as dependências não existem, instala e reinicia)
    if not _dependencias_instaladas():
        _configurar_e_reiniciar()
        return  # O script para aqui na primeira vez, pois o subprocesso assume

    # Passo 2: Auditoria de segurança (Ocorre com dependências prontas)
    _auditar_configuracoes()
    
    # Passo 3: Importação e Execução Segura
    try:
        logger.info("Ambiente validado. Carregando automação principal...")
        import automation
        logger.info("Delegando execução para o motor (automation.py)...")
        logger.info("-" * 60)
        automation.main()
        
    except ModuleNotFoundError as exc:
        logger.critical("Falha ao encontrar módulos da automação: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print("") # Quebra de linha limpa
        logger.info("Sinal de interrupção (Ctrl+C) recebido. Encerrando de forma segura.")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Falha catastrófica não tratada: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()