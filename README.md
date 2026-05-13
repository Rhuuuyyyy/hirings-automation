<div align="center">

<br>

# Hub de Automações TI

### Plataforma interna de monitoramento e automação de processos de TI

<br>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Verdanadesk](https://img.shields.io/badge/Verdanadesk-API%20v2.3-FF7A1A?style=flat-square)](https://verdanadesk.com)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-CDN-38BDF8?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Licença](https://img.shields.io/badge/uso-interno%20Dexian-6366F1?style=flat-square)]()

<br>

</div>

---

## Sumário

- [Visão Geral](#visão-geral)
- [Módulos](#módulos)
- [Dashboard](#dashboard)
- [Exportação](#exportação)
- [Stack](#stack)
- [Arquitetura](#arquitetura)
- [Configuração](#configuração)
- [Como Executar](#como-executar)
- [Estrutura do Repositório](#estrutura-do-repositório)
- [Adicionando um Módulo](#adicionando-um-módulo)
- [Histórico de Versões](#histórico-de-versões)
- [Roadmap](#roadmap)

---

## Visão Geral

O Hub de Automações centraliza o acompanhamento de processos operacionais de TI que antes dependiam inteiramente de trabalho manual. O núcleo do sistema é um worker de sincronização que consome a API REST do Verdanadesk, persiste os dados localmente em JSON e os expõe para um dashboard web em tempo real via FastAPI.

A arquitetura é modular por design: adicionar um novo módulo significa criar um worker em `automations/`, registrar rotas em `backend/api.py` e incluir a entrada no menu lateral do frontend — sem tocar na base da aplicação.

```
Hoje:   Contratações GLPI  ·  Análise de Usuários e Máquinas
Amanhã: Termos de Responsabilidade  ·  Onboarding  ·  Alertas de SLA
```

---

## Módulos

### Contratações GLPI

Monitora chamados de contratação abertos no Verdanadesk. O worker executa continuamente em background e a cada ciclo:

1. Autentica via OAuth2 Password Grant com auto-renewal transparente de token
2. Consulta as categorias configuradas com paginação automática
3. Filtra chamados com status ativo — Novo, Em Atendimento, Pendente
4. Para chamados da categoria com controle de ativo, verifica em **somente leitura** se existe uma tarefa de Termo de Responsabilidade associada
5. Persiste o snapshot via escrita atômica (`arquivo.tmp` → `os.replace`)

O dashboard consome esse snapshot via polling leve, sem WebSocket.

#### Status do Termo de Responsabilidade

| `Termo_Status` | Condição |
|---|---|
| `Termo OK` | Tarefa de termo encontrada e concluída (`state = 2`) |
| `Pendente` | Tarefa encontrada, mas ainda em aberto |
| `Sem tarefa` | Nenhuma tarefa de termo localizada no ticket |
| `Erro ao verificar` | Falha de comunicação com a API durante a verificação |

---

### Análise de Usuários

Varredura do inventário para identificar anomalias entre usuários e máquinas cadastradas. Produz três relatórios:

| Análise | Descrição |
|---|---|
| **Inativos com Máquinas** | Usuários com `is_active = false` que ainda possuem computadores vinculados |
| **CC Divergente** | Usuário e máquina em centros de custo diferentes — compara `default_entity` do usuário com `entity` do computador |
| **Múltiplos Responsáveis** | Computadores com mais de um usuário atribuído simultaneamente (`user` e `user_tech` distintos) |

A análise é disparada manualmente via botão no dashboard ou via `POST /api/analise-usuarios/sync`. Os resultados ficam disponíveis em `GET /api/analise-usuarios`.

---

## Dashboard

Interface de operações construída com HTML5, Tailwind CSS e JavaScript Vanilla. Sem frameworks, sem build step, sem dependências de runtime no frontend.

| Funcionalidade | Detalhe |
|---|---|
| Dark / Light Mode | Toggle persistido em `localStorage`, sem flash ao carregar |
| Filtros de Status | Chips clicáveis: Todos · Novo · Em Atendimento · Pendente · Termos |
| Busca Global | Filtra por ID, Título e Requerente em tempo real |
| Ordenação | Qualquer coluna, crescente ou decrescente |
| Densidade da Tabela | Modo Confortável e Modo Denso |
| SLA Visual | Barra de progresso colorida proporcional ao prazo restante |
| Drawer de Detalhe | Painel lateral com timeline completa do chamado |
| KPI Sparklines | Miniséries históricas de 14 dias para as principais métricas |
| Intervalo de Sync | Dropdown configurável: 10 s · 30 s · 1 min · 2 min · 5 min, persistido no browser |
| Atalhos de Teclado | `/` foca a busca · `R` força sync · `Esc` fecha o painel |

---

## Exportação

Disponível via `GET /api/contratacoes/export?formato=xlsx|pdf|csv` com filtro opcional por `termo`.

| Formato | Características |
|---|---|
| **XLSX** | Banner de identidade visual, linha de metadados, cabeçalhos formatados; células de Status e Termo com cores condicionais; SLA em vermelho/âmbar; layout de impressão A4 paisagem configurado |
| **PDF** | Layout A4 paisagem via `reportlab` (Platypus); paleta de cores consistente com o dashboard; rodapé com timestamp e número de página |
| **CSV** | UTF-8 plain text, compatível com Excel, LibreOffice e qualquer ferramenta de análise de dados |

---

## Stack

### Backend

| Componente | Tecnologia |
|---|---|
| Servidor web | FastAPI + Uvicorn |
| Worker de sync | Python `threading` (daemon thread) |
| Integração API | `requests` — Verdanadesk REST v2.3 com OAuth2 Password Grant |
| Exportação Excel | `openpyxl` |
| Exportação PDF | `reportlab` (Platypus) |
| Configuração | `python-dotenv` |

### Frontend

| Componente | Tecnologia |
|---|---|
| Estilo | Tailwind CSS via CDN |
| Tipografia | Geist + Geist Mono (Vercel) |
| Lógica | JavaScript Vanilla (ES2022) |
| Design System | CSS Custom Properties — `--accent`, `--ok`, `--warn`, `--err`, `--surface` |

### Persistência

```
database/
  contratacoes.json        snapshot atual dos chamados ativos
  historico.json           série temporal diária (últimos 60 dias de KPIs)
  usuarios_analise.json    resultado da última análise de usuários × máquinas
```

> A pasta `database/` é gerada em runtime e ignorada pelo git.

---

## Arquitetura

```
python run.py
│
├── [thread principal]  Uvicorn → FastAPI
│     GET  /                            dashboard (frontend/index.html)
│     GET  /api/config                  URL base do Verdanadesk (via env)
│     GET  /api/contratacoes            snapshot de chamados ativos
│     GET  /api/contratacoes/export     XLSX / PDF / CSV
│     GET  /api/historico               série temporal de KPIs
│     GET  /api/analise-usuarios        resultado da análise de inventário
│     POST /api/analise-usuarios/sync   dispara varredura em background
│     GET  /api/analise-usuarios/status flag de sync em andamento
│     GET  /docs                        Swagger UI (gerado automaticamente)
│
└── [daemon thread]  glpi_sync.py
      loop a cada POLLING_INTERVAL segundos
        │
        ├─ ClienteGLPI  OAuth2 Password Grant + auto-renewal em 401
        │     POST /api.php/token
        │     GET  /Administration/User/{id}   lookup com cache em memória
        │     GET  /search/Ticket              paginado por categoria
        │     GET  /Ticket/{id}/TicketTask      verificação de termo (read-only)
        │
        ├─ SincronizadorDB
        │     buscar_nome_usuario()            cache lazy em memória
        │     buscar_data_inicio_conteudo()    fallback regex no HTML do ticket
        │     verificar_tarefa_termo()         somente leitura
        │
        └─ escrita atômica
              database/contratacoes.json
              database/historico.json
```

### Princípios de Design

**Escrita atômica** — `write .tmp` → `os.replace()`. O JSON nunca fica em estado corrompido, mesmo que a aplicação seja encerrada no meio de uma escrita.

**Auto-healing de sessão** — respostas `401` disparam `_renovar_sessao()` de forma transparente antes de retentar a requisição original. O worker nunca cai por expiração de token.

**Separação de responsabilidades** — o worker só escreve JSON; a API só lê JSON; o frontend só consome a API. Nenhuma camada conhece os detalhes de implementação da anterior.

**Read-only no Verdanadesk** — o worker nunca cria, edita ou deleta dados na plataforma. Toda escrita é exclusivamente humana.

**Cache lazy** — lookup de usuários on-demand com `dict` em memória, evitando N+1 sem bulk load inicial.

---

## Configuração

```bash
cp .env.example .env
# edite o .env com suas credenciais
```

| Variável | Obrigatória | Padrão | Descrição |
|---|:---:|:---:|---|
| `API_URL` | sim | — | URL base da API versionada |
| `OAUTH_CLIENT_ID` | sim | — | Client ID registrado no Verdanadesk |
| `OAUTH_CLIENT_SECRET` | sim | — | Client Secret do app de integração |
| `OAUTH_USERNAME` | sim | — | Usuário de integração |
| `OAUTH_PASSWORD` | sim | — | Senha do usuário de integração |
| `CATEGORIA_CONTRATACAO_IDS` | sim | — | IDs das categorias monitoradas, separados por vírgula |
| `OAUTH_TOKEN_URL` | não | derivado de `API_URL` | Endpoint OAuth2; se omitido, substituí `/vX.Y` por `/token` automaticamente |
| `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS` | não | desativado | ID da categoria com controle de Termo de Responsabilidade |
| `POLLING_INTERVAL` | não | `300` | Intervalo entre varreduras do worker, em segundos |
| `WEB_PORT` | não | `8000` | Porta do servidor web |

> O arquivo `.env` está no `.gitignore` e nunca deve ser commitado. Use `.env.example` como referência.

---

## Como Executar

**Pré-requisito:** Python 3.10 ou superior.

```bash
# Clone o repositório
git clone https://github.com/Rhuuuyyyy/hub-automation.git
cd hub-automation

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows

# Configure as variáveis de ambiente
cp .env.example .env
# edite o .env

# Inicie a aplicação
python run.py
```

O `run.py` instala as dependências automaticamente, sobe o worker em background e inicia o servidor. Nenhum `pip install` manual é necessário.

| Endereço | Conteúdo |
|---|---|
| `http://localhost:8000` | Dashboard principal |
| `http://localhost:8000/docs` | Swagger UI com todos os endpoints |

Para encerrar: `Ctrl+C`.

---

## Estrutura do Repositório

```
hub-automation/
│
├── run.py                          ponto de entrada único
├── main.py                         aplicação FastAPI
├── requirements.txt
├── .env.example                    template de configuração
│
├── automations/
│   ├── contratacoes/
│   │   └── glpi_sync.py            worker de sincronização de chamados
│   └── usuarios/
│       ├── __init__.py
│       └── usuarios_sync.py        worker de análise de usuários × máquinas
│
├── backend/
│   └── api.py                      rotas REST
│
├── frontend/
│   └── index.html                  dashboard SPA
│
├── database/                       gerado em runtime — ignorado pelo git
│
├── .brain/                         documentação interna e decisões de arquitetura
│   ├── architecture.md
│   ├── roadmap.md
│   ├── glpi_api_quirks.md
│   ├── task_automation.md
│   └── sharepoint_graph_api.md
│
└── .archive/                       versões anteriores para referência histórica
    ├── automation.py               v1 — LangChain + Google Gemini
    └── boilerplate.py
```

---

## Adicionando um Módulo

O padrão de extensão do Hub:

```
1. Worker      automations/<nome>/<nome>_sync.py
               implemente executar(glpi) e is_running()

2. API         backend/api.py
               GET  /api/<nome>
               POST /api/<nome>/sync
               GET  /api/<nome>/status

3. Frontend    frontend/index.html
               entrada no menu lateral  id="nav-<nome>"
               função fetch<Nome>() seguindo o padrão existente

4. Banco       database/<nome>.json
               já coberto pelo .gitignore via database/*.json
```

---

## Histórico de Versões

| Versão | Arquitetura | Status |
|---|---|---|
| v1 | LangChain + Google Gemini — extração de dados via LLM | Arquivado em `.archive/` |
| v2 | ETL local para arquivo `.xlsx` via Power Automate | Substituído |
| v3 | Verdanadesk REST API → JSON → FastAPI → Dashboard | **Atual** |

---

## Roadmap

**Em desenvolvimento**

- Automação de criação do Termo de Responsabilidade — tarefa criada automaticamente no GLPI ao abrir chamado com ativo vinculado
- Notificações por Teams quando SLA estiver crítico

**Backlog**

- Filtro por intervalo de datas no dashboard
- Pré-carregamento em bulk de usuários para eliminar round-trips N+1 na inicialização
- Testes automatizados com mock da API Verdanadesk
- Módulo de Onboarding — checklist de entrada para novos funcionários

---

<div align="center">

<br>

Desenvolvido pela equipe de TI da **Dexian** &nbsp;·&nbsp; Uso interno &nbsp;·&nbsp; 

<br>

</div>
