<div align="center">

# Hub de Automações TI — Dexian

**Plataforma centralizada de monitoramento e automação de processos operacionais de TI**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square&logo=fastapi&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-CDN-38BDF8?style=flat-square&logo=tailwindcss&logoColor=white)
![Verdanadesk](https://img.shields.io/badge/Verdanadesk-REST%20API%20v2.3-FF7A1A?style=flat-square)
![Uso Interno](https://img.shields.io/badge/uso-interno%20Dexian-6366F1?style=flat-square)

</div>

---

## Visão Geral

O Hub de Automações centraliza o acompanhamento de processos operacionais de TI que antes dependiam de trabalho manual. O núcleo do sistema é um worker de sincronização que conversa com a API REST do Verdanadesk (GLPI), persiste os dados localmente e os expõe via uma API FastAPI para um dashboard web em tempo real.

A arquitetura é modular por design. O módulo de Contratações foi o ponto de partida; o módulo de Análise de Usuários veio na sequência. Adicionar um novo módulo significa criar um worker em `automations/`, registrar rotas em `backend/api.py` e incluir a entrada no menu lateral do `frontend/index.html` — sem tocar na base da aplicação.

```
Hoje:   Contratações GLPI  ·  Análise de Usuários/Máquinas
Amanhã: + Termos de Responsabilidade  ·  + Onboarding  ·  + Alertas de SLA
```

---

## Módulos

### Contratações GLPI

Monitora chamados de contratação abertos no Verdanadesk. O worker roda continuamente em background e a cada ciclo:

1. Autentica via OAuth2 Password Grant e gerencia o token com auto-renewal transparente.
2. Consulta as categorias configuradas com busca paginada.
3. Filtra chamados com status ativo (Novo, Em Atendimento, Pendente).
4. Para chamados da categoria com controle de ativo, verifica — em **somente leitura** — se existe uma tarefa de Termo de Responsabilidade associada.
5. Persiste o snapshot via escrita atômica (`arquivo.tmp → os.replace`).

O dashboard consome esse snapshot via polling, sem WebSocket.

#### Gestão de Termos de Responsabilidade

Para chamados da categoria configurada em `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS`, o sistema inspeciona automaticamente as tarefas vinculadas ao ticket:

| `Termo_Status`      | Condição                                                    |
|---------------------|-------------------------------------------------------------|
| `Termo OK`          | Tarefa de termo encontrada e concluída (`state = 2`)        |
| `Pendente`          | Tarefa encontrada, mas ainda em aberto                      |
| `Sem tarefa`        | Nenhuma tarefa de termo localizada no ticket                |
| `Erro ao verificar` | Falha de comunicação com a API durante a verificação        |

---

### Análise de Usuários

Varredura periódica do inventário para identificar anomalias entre usuários e máquinas cadastradas no Verdanadesk. Produz três relatórios:

| Análise                    | Descrição                                                                                      |
|----------------------------|------------------------------------------------------------------------------------------------|
| **Inativos com Máquinas**  | Usuários com `is_active = false` que ainda possuem computadores vinculados                     |
| **CC Divergente**          | Usuário e máquina com centros de custo diferentes — compara `default_entity` do usuário com `entity` do computador |
| **Múltiplos Responsáveis** | Computadores com mais de um usuário atribuído (`user` e `user_tech` distintos)                 |

A análise é disparada manualmente via botão no dashboard ou via `POST /api/analise-usuarios/sync`. Os resultados ficam disponíveis em `GET /api/analise-usuarios`.

---

## Dashboard

Interface de operações construída com HTML5 + Tailwind CSS + JavaScript Vanilla. Sem frameworks pesados, sem build step.

| Funcionalidade           | Detalhe                                                                             |
|--------------------------|-------------------------------------------------------------------------------------|
| **Dark / Light Mode**    | Toggle persistido em `localStorage`, sem flash ao carregar                          |
| **Filtros de Status**    | Chips clicáveis: Todos · Novo · Em Atendimento · Pendente · Termos                  |
| **Busca Global**         | Filtra por ID, Título e Requerente em tempo real                                    |
| **Ordenação**            | Qualquer coluna, asc/desc                                                           |
| **Densidade da Tabela**  | Modo Confortável e Modo Denso                                                       |
| **SLA Visual**           | Barra de progresso colorida (verde → amarelo → vermelho) proporcional ao prazo      |
| **Drawer de Detalhe**    | Painel lateral com timeline completa e atributos do chamado                         |
| **KPI Sparklines**       | Miniséries históricas de 14 dias: Total, Em Atendimento, Pendentes, Termos OK       |
| **Intervalo de Sync**    | Dropdown configurável: 10 s · 30 s · 1 min · 2 min · 5 min (persistido no browser) |
| **Atalhos de Teclado**   | `/` = foco na busca · `R` = forçar sync · `Esc` = fechar painel                    |

---

## Exportação de Dados

Disponível em `GET /api/contratacoes/export?formato=xlsx|pdf|csv` com filtro opcional por `termo`.

| Formato  | Características                                                                                                           |
|----------|---------------------------------------------------------------------------------------------------------------------------|
| **XLSX** | Banner laranja da marca, linha de metadados, cabeçalhos formatados; Status e Termo com cores condicionais; SLA em vermelho/âmbar; impressão A4 paisagem configurada |
| **PDF**  | Layout A4 paisagem via `reportlab` (Platypus); título em laranja; cores condicionais por célula; rodapé com timestamp e número de página |
| **CSV**  | UTF-8 plain text, compatível com Excel, LibreOffice e qualquer ferramenta de dados                                        |

---

## Stack Tecnológica

### Backend

| Componente        | Tecnologia                                           |
|-------------------|------------------------------------------------------|
| Servidor web      | FastAPI + Uvicorn                                    |
| Worker de sync    | Python `threading` (daemon thread)                   |
| Integração API    | `requests` — Verdanadesk REST v2.3 com OAuth2        |
| Exportação Excel  | `openpyxl`                                           |
| Exportação PDF    | `reportlab` (Platypus)                               |
| Configuração      | `python-dotenv` (`.env`)                             |

### Frontend

| Componente    | Tecnologia                                                          |
|---------------|---------------------------------------------------------------------|
| Estilo        | Tailwind CSS via CDN (zero build step)                              |
| Tipografia    | Geist + Geist Mono (Vercel)                                         |
| Lógica        | JavaScript Vanilla (ES2022)                                         |
| Design System | CSS Custom Properties (`--accent`, `--ok`, `--warn`, `--err`, etc.) |

### Persistência

```
database/                       ← gerado em runtime, ignorado pelo git
  contratacoes.json             ← snapshot atual dos chamados ativos
  historico.json                ← série temporal diária (últimos 60 dias de KPIs)
  usuarios_analise.json         ← resultado da última análise de usuários/máquinas
```

---

## Arquitetura

```
python run.py
│
├── [thread principal] Uvicorn → FastAPI (main.py)
│     GET  /                              → frontend/index.html
│     GET  /api/contratacoes              → database/contratacoes.json
│     GET  /api/contratacoes/export       → XLSX / PDF / CSV
│     GET  /api/historico                 → database/historico.json
│     GET  /api/analise-usuarios          → database/usuarios_analise.json
│     POST /api/analise-usuarios/sync     → dispara varredura em background
│     GET  /api/analise-usuarios/status   → flag de sync em andamento
│     GET  /docs                          → Swagger UI (automático)
│
└── [daemon thread] glpi_sync.py
      loop (POLLING_INTERVAL segundos)
        │
        ├─ ClienteGLPI — OAuth2 Password Grant com auto-renewal
        │     POST /api.php/token              → access_token
        │     GET  /Administration/User/{id}   → lookup com cache em memória
        │     GET  /search/Ticket?...          → chamados paginados por categoria
        │     GET  /Ticket/{id}/TicketTask     → verificação de termo (read-only)
        │
        ├─ SincronizadorDB._chamado_para_dict()
        │     ├─ buscar_nome_usuario()          (cache em memória, lazy)
        │     ├─ buscar_data_inicio_conteudo()  (fallback regex no HTML do ticket)
        │     └─ verificar_tarefa_termo()       (somente leitura)
        │
        └─ escrita atômica → database/contratacoes.json
                           → database/historico.json
```

### Princípios de Design

| Princípio                       | Implementação                                                                        |
|---------------------------------|--------------------------------------------------------------------------------------|
| **Escrita atômica**             | `write .tmp → os.replace()` — JSON nunca fica corrompido, mesmo com reinicialização no meio da escrita |
| **Auto-healing de sessão**      | `401/403` dispara `_renovar_sessao()` transparentemente — o worker nunca cai por token expirado |
| **Separação de responsabilidades** | Worker só escreve JSON · API só lê JSON · Frontend só consome a API              |
| **Read-only no Verdanadesk**    | O worker nunca cria, edita ou deleta dados na plataforma. Toda escrita é exclusivamente humana |
| **Cache lazy de usuários**      | Lookup on-demand com `dict` em memória — evita N+1 sem bulk load inicial             |

---

## Configuração

Copie o arquivo de exemplo e preencha com as credenciais reais:

```bash
cp .env.example .env
```

| Variável                               | Obrigatória |  Padrão   | Descrição                                                                                        |
|----------------------------------------|:-----------:|:---------:|--------------------------------------------------------------------------------------------------|
| `API_URL`                              | ✅          | —         | URL base da API versionada (ex: `https://servidor.verdanadesk.com/api.php/v2.3`)                |
| `OAUTH_CLIENT_ID`                      | ✅          | —         | Client ID registrado na plataforma Verdanadesk                                                   |
| `OAUTH_CLIENT_SECRET`                  | ✅          | —         | Client Secret do app de integração                                                               |
| `OAUTH_USERNAME`                       | ✅          | —         | Usuário de integração (email ou login)                                                           |
| `OAUTH_PASSWORD`                       | ✅          | —         | Senha do usuário de integração                                                                   |
| `CATEGORIA_CONTRATACAO_IDS`            | ✅          | —         | IDs das categorias monitoradas, separados por vírgula (ex: `152,153`)                           |
| `OAUTH_TOKEN_URL`                      | ❌          | derivado  | Endpoint OAuth2. Se omitido, derivado de `API_URL` substituindo `/vX.Y` por `/token`            |
| `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS` | ❌          | desativado | ID único da categoria com controle de Termo de Responsabilidade                                 |
| `POLLING_INTERVAL`                     | ❌          | `300`     | Intervalo entre varreduras do worker, em segundos                                                |
| `WEB_PORT`                             | ❌          | `8000`    | Porta do servidor web                                                                            |

> **Segurança:** `.env` está no `.gitignore` e **nunca deve ser commitado**. Use `.env.example` como referência para outros membros da equipe.

---

## Como Executar

**Pré-requisito:** Python 3.10 ou superior.

```bash
# 1. Clone o repositório
git clone https://github.com/Rhuuuyyyy/hirings-automation.git
cd hirings-automation

# 2. Crie e ative o ambiente virtual
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# 3. Configure as variáveis de ambiente
cp .env.example .env
# edite o .env com suas credenciais

# 4. Inicie a aplicação
python run.py
```

O `run.py` instala dependências automaticamente, sobe o worker GLPI em background e inicia o servidor. Nenhum `pip install` manual é necessário.

| Endereço                     | Conteúdo                          |
|------------------------------|-----------------------------------|
| `http://localhost:8000`      | Dashboard principal               |
| `http://localhost:8000/docs` | Swagger UI com todos os endpoints |

Para encerrar: `Ctrl+C`.

---

## Estrutura do Repositório

```
hirings-automation/
│
├── run.py                          ← Ponto de entrada único
├── main.py                         ← Aplicação FastAPI (rotas + montagem)
├── requirements.txt
├── .env.example                    ← Template de configuração (commitar; não commitar .env)
│
├── automations/
│   ├── contratacoes/
│   │   └── glpi_sync.py            ← Worker de sincronização de chamados
│   └── usuarios/
│       ├── __init__.py
│       └── usuarios_sync.py        ← Worker de análise de usuários × máquinas
│
├── backend/
│   └── api.py                      ← Rotas REST (contratacoes, historico, export, analise-usuarios)
│
├── frontend/
│   └── index.html                  ← Dashboard SPA (HTML + Tailwind + JS Vanilla)
│
├── database/                       ← Gerado em runtime (ignorado pelo git)
│   ├── contratacoes.json
│   ├── historico.json
│   └── usuarios_analise.json
│
├── .brain/                         ← Documentação interna e decisões de arquitetura
│   ├── architecture.md
│   ├── roadmap.md
│   ├── glpi_api_quirks.md
│   ├── task_automation.md
│   └── sharepoint_graph_api.md
│
└── .archive/                       ← Versões anteriores (referência histórica)
    ├── automation.py               ← v1: LangChain + Google Gemini
    ├── boilerplate.py
    └── run.py
```

---

## Autenticação com o Verdanadesk

A versão atual usa **OAuth2 Password Grant** (API v2.3), substituindo o esquema legado de `App-Token` + `User-Token` + `Session-Token` das versões anteriores.

```
POST /api.php/token
Content-Type: application/x-www-form-urlencoded

grant_type=password&client_id=...&client_secret=...&username=...&password=...

Resposta: {"access_token": "...", "token_type": "Bearer", "expires_in": 3600}
```

O `ClienteGLPI` em `glpi_sync.py` gerencia o ciclo de vida do token automaticamente: qualquer `401` dispara `_renovar_sessao()` de forma transparente antes de retentar a requisição original.

---

## Adicionando um Novo Módulo

1. **Worker:** crie `automations/<nome>/` com `__init__.py` e `<nome>_sync.py`. Implemente `executar(glpi)` e `is_running()` seguindo o padrão de `usuarios_sync.py`.
2. **API:** adicione as rotas em `backend/api.py` — `GET /<nome>`, `POST /<nome>/sync` e `GET /<nome>/status`.
3. **Frontend:** adicione a entrada no menu lateral de `frontend/index.html` com `id="nav-<nome>"` e implemente `fetch<Nome>()` no padrão das funções existentes.
4. **Banco:** a persistência vai em `database/<nome>.json` — já coberto pelo `.gitignore` com o padrão `database/*.json`.

---

## Histórico de Versões

| Versão | Arquitetura                                    | Status                   |
|--------|------------------------------------------------|--------------------------|
| v1     | LangChain + Google Gemini (extração via LLM)   | Arquivado em `.archive/` |
| v2     | ETL local → arquivo `.xlsx` via Power Automate | Substituído              |
| v3     | Verdanadesk API → JSON → FastAPI → Dashboard   | **Atual**                |

---

## Roadmap

### Em Desenvolvimento
- [ ] Automação de Termos de Responsabilidade (criação automática da tarefa no GLPI ao abrir chamado com ativo)
- [ ] Notificações por Teams quando SLA estiver crítico

### Backlog
- [ ] Filtro por intervalo de datas no dashboard de contratações
- [ ] Pré-carregamento em bulk de usuários (`GET /Administration/User?limit=9999`) para eliminar round-trips N+1 na inicialização
- [ ] Testes automatizados com mock da API Verdanadesk
- [ ] Módulo de Onboarding — checklist de entrada para novos funcionários
- [ ] Suporte a múltiplas instâncias Verdanadesk

---

<div align="center">

Feito pela equipe de TI da **Dexian** · Uso interno · Não distribuir externamente

</div>
