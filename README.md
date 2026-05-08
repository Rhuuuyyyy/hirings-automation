<div align="center">

# Hub de Automações TI — Dexian

**Plataforma centralizada de monitoramento e automação de processos operacionais de TI**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square&logo=fastapi&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-CDN-38BDF8?style=flat-square&logo=tailwindcss&logoColor=white)
![GLPI](https://img.shields.io/badge/GLPI-REST%20API-FF7A1A?style=flat-square)
![License](https://img.shields.io/badge/uso-interno%20Dexian-6366F1?style=flat-square)

</div>

---

## Visão Geral

O Hub de Automações nasceu com um objetivo específico: eliminar o trabalho manual de acompanhar chamados de contratação abertos no GLPI. O que começou como um script de sincronização para planilha Excel evoluiu para uma plataforma web de alta fidelidade com backend Python e dashboard em tempo real.

A arquitetura foi desenhada desde o início para ser **modular e escalável**. O módulo de Contratações é apenas o primeiro. A estrutura de rotas, workers e frontend permite que qualquer membro da equipe de TI contribua com um novo módulo — seja para auditoria de ativos, inventário ou dashboards de SLA — sem precisar reescrever a base da aplicação.

```
Hoje:   GLPI Contratações  →  Dashboard  →  Export (XLSX / PDF / CSV)
Amanhã: + Módulo Ativos    →  + Módulo Onboarding  →  + Módulo Auditoria
```

---

## Módulo Ativo — Contratações GLPI

### Sincronização em Tempo Real
O worker `glpi_sync.py` roda em background como uma thread daemon. A cada ciclo (configurável via `.env`, padrão **5 minutos**) ele:

1. Autentica na API REST do GLPI e gerencia o `session_token` com auto-renewal em `401/403`.
2. Consulta todas as categorias de contratação configuradas via busca paginada (200 chamados/página).
3. Filtra apenas chamados com status ativo (Novo, Em Atendimento, Pendente).
4. Para cada chamado da categoria com controle de ativo, verifica — **somente leitura** — se existe uma tarefa de "Termo de Responsabilidade" associada ao ticket.
5. Persiste o snapshot em `database/contratacoes.json` via escrita atômica (`write .tmp → os.replace`), garantindo que o arquivo nunca fique corrompido mesmo com reinicializações.

O dashboard consome esse snapshot via polling leve a cada **10 segundos**, sem WebSocket, sem overhead.

### Dashboard

Interface de operações construída com HTML5 + Tailwind CSS + JavaScript Vanilla — sem frameworks pesados, sem bundler.

| Funcionalidade | Detalhe |
|---|---|
| **Dark / Light Mode** | Toggle persistido em `localStorage`, transição sem flash |
| **Filtros de Status** | Chips: Todos, Novo, Em Atendimento, Pendente, Termos |
| **Busca Global** | Filtra por ID, Título e Requerente em tempo real |
| **Ordenação** | Qualquer coluna, asc/desc, com ícone de direção |
| **Densidade de Tabela** | Modo Confortável e Modo Denso |
| **SLA Visual** | Barra de progresso colorida (verde / amarelo / vermelho) baseada em dias restantes |
| **Drawer de Detalhe** | Painel lateral com timeline, alerta de SLA e atributos do chamado |
| **KPI Sparklines** | Minisérie histórica de 14 dias (Total, Em Atendimento, Pendentes, Termos OK) |
| **Atalhos de Teclado** | `/` = foco na busca, `R` = forçar sync, `Esc` = fechar drawer |

### Gestão de Termos de Responsabilidade

Para chamados da categoria configurada em `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS`, o sistema verifica automaticamente se o ticket possui uma tarefa com o texto `"termo de responsabilidade"`. O status retornado é um de quatro valores:

| Status | Significado |
|---|---|
| `Termo OK` | Tarefa encontrada e marcada como concluída (`state = 2`) |
| `Pendente` | Tarefa encontrada, mas ainda em aberto |
| `Sem tarefa` | Nenhuma tarefa de termo localizada no ticket |
| `Erro ao verificar` | Falha de comunicação com a API do GLPI |

### Exportação de Dados

| Formato | Característica |
|---|---|
| **XLSX** | 3 linhas de header (banner laranja, metadados, colunas); células de Status e Termo coloridas; SLA em vermelho/âmbar; configuração de impressão A4 paisagem |
| **PDF** | Layout A4 paisagem via `reportlab`; título em laranja da marca; cores condicionais por célula; rodapé com timestamp e número de página |
| **CSV** | Plain text UTF-8, compatível com qualquer planilha |

---

## Stack Tecnológica

### Backend
| Componente | Tecnologia |
|---|---|
| Servidor Web | FastAPI + Uvicorn |
| Worker de Sync | Python threading (daemon thread) |
| Integração GLPI | `requests` — REST API com sessão gerenciada |
| Exportação Excel | `openpyxl` |
| Exportação PDF | `reportlab` (Platypus) |
| Configuração | `python-dotenv` (`.env`) |

### Frontend
| Componente | Tecnologia |
|---|---|
| Estilo | Tailwind CSS (via CDN — zero build step) |
| Tipografia | Geist + Geist Mono (Vercel) |
| Lógica | JavaScript Vanilla (ES2022) |
| Design System | CSS Custom Properties (`--accent`, `--ok`, `--warn`, `--err`) |

### Infraestrutura de Dados
```
database/
  contratacoes.json   ← snapshot atual, sobrescrito a cada ciclo pelo worker
  historico.json      ← série temporal diária (últimos 60 dias de KPIs)
```

---

## Arquitetura

```
python run.py
│
├── [thread principal] uvicorn → FastAPI (main.py)
│     GET /                       → frontend/index.html
│     GET /api/contratacoes       → database/contratacoes.json
│     GET /api/historico          → database/historico.json
│     GET /api/contratacoes/export?formato=xlsx|pdf|csv
│
└── [daemon thread] glpi_sync.py
      loop (POLLING_INTERVAL segundos)
        │
        ├─ ClienteGLPI.buscar_chamados_ativos()
        │     GET /search/Ticket?criteria[cat=X] × N categorias
        │
        ├─ SincronizadorDB._chamado_para_dict()
        │     ├─ buscar_nome_usuario()           (cache em memória)
        │     ├─ buscar_data_inicio_do_conteudo() (fallback regex no HTML)
        │     └─ verificar_tarefa_termo()         (somente leitura)
        │
        └─ escrita atômica → database/contratacoes.json
                           → database/historico.json
```

### Princípios de Design

- **Escrita atômica** — `write .json.tmp → os.replace()`. O dashboard nunca lê um arquivo pela metade.
- **Auto-healing de sessão** — `401/403` dispara `_renovar_sessao()` transparentemente. O worker nunca cai por expiração de token.
- **Separação de responsabilidades** — o worker só escreve JSON; a API só lê JSON; o frontend só consome a API.
- **Strictamente read-only no GLPI** — o worker nunca cria, edita ou deleta dados no GLPI. Toda escrita na plataforma GLPI é exclusivamente humana.

---

## Configuração

Copie `.env.example` para `.env` e preencha as variáveis:

```bash
cp .env.example .env
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GLPI_URL` | ✅ | URL base da API REST (ex: `http://glpi.empresa.com/apirest.php`) |
| `GLPI_USER_TOKEN` | ✅ | User-Token do usuário de integração (Perfil → API) |
| `GLPI_APP_TOKEN` | ✅ | App-Token da aplicação (Config → Geral → API) |
| `CATEGORIA_CONTRATACAO_IDS` | ✅ | IDs das categorias monitoradas, separados por vírgula (ex: `152,153`) |
| `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS` | ❌ | ID da categoria com controle de Termo de Responsabilidade |
| `POLLING_INTERVAL` | ❌ | Intervalo de sync em segundos (padrão: `300`) |

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
# edite o .env com suas credenciais GLPI

# 4. Inicie a aplicação
python run.py
```

O comando `run.py` instala dependências automaticamente, sobe o worker GLPI em background e inicia o servidor web. O dashboard fica disponível em:

```
http://localhost:8000
```

A documentação interativa da API (Swagger UI) fica em:

```
http://localhost:8000/docs
```

---

## Estrutura do Repositório

```
hirings-automation/
│
├── run.py                          ← Ponto de entrada único
├── main.py                         ← Aplicação FastAPI
├── requirements.txt
├── .env.example                    ← Template de configuração
│
├── automations/
│   └── contratacoes/
│       └── glpi_sync.py            ← Worker de sincronização GLPI
│
├── backend/
│   └── api.py                      ← Rotas REST (contratacoes, historico, export)
│
├── frontend/
│   └── index.html                  ← Dashboard SPA
│
├── database/                       ← Gerado em runtime (ignorado pelo git)
│   ├── contratacoes.json
│   └── historico.json
│
└── .brain/                         ← Documentação interna e decisões de arquitetura
    ├── architecture.md
    ├── roadmap.md
    └── glpi_api_quirks.md
```

---

## Roadmap

### Em Desenvolvimento
- [ ] Exportação PDF com `reportlab` (Platypus)
- [ ] Filtro por intervalo de datas no dashboard

### Próximas Funcionalidades
- [ ] **Módulo de Ativos** — inventário e auditoria de equipamentos vinculados a chamados
- [ ] **Notificações** — alertas por e-mail ou Microsoft Teams quando SLA estiver crítico
- [ ] **Pré-carregamento de usuários** — bulk GET `/User` para eliminar round-trips N+1 na inicialização
- [ ] **Módulo de Onboarding** — acompanhamento de checklist de entrada para novos funcionários
- [ ] **Testes automatizados** — suite com mock da API GLPI para validar o worker sem dependência de rede

### Histórico de Versões

| Versão | Arquitetura | Status |
|---|---|---|
| v1 | LangChain + Google Gemini (LLM) | Arquivado em `.archive/` |
| v2 | ETL local → arquivo `.xlsx` | Substituído |
| v3 | GLPI → JSON → FastAPI → Dashboard | **Atual** |

---

## Contribuindo

O projeto é de **uso interno da equipe de TI da Dexian**. Para propor melhorias:

1. Crie uma branch com o padrão `feat/nome-da-funcionalidade` ou `fix/descricao-do-bug`.
2. Faça suas alterações com commits descritivos em português.
3. Abra um Pull Request descrevendo o que foi alterado e por quê.

Para adicionar um novo módulo ao Hub, siga o padrão existente:
- Crie `automations/<modulo>/` com o worker de sincronização.
- Adicione as rotas em `backend/api.py` ou em um novo router.
- Adicione a entrada na sidebar do `frontend/index.html` com `id="nav-<modulo>"`.

---

<div align="center">

Feito pela equipe de TI da **Dexian** · Interno · Não distribuir externamente

</div>
