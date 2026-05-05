# Arquitetura do Projeto

## Pivot de Produto (Maio 2026)

O projeto foi migrado de um pipeline LLM (LangChain + Gemini/OpenAI) para um **sincronizador ETL puro** GLPI → Excel. Sem IA, sem Pydantic, sem LangChain.

---

## Arquivo Principal

`glpi_to_excel_sync.py` — script único, auto-contido, sem dependências internas.

---

## Componentes

```
glpi_to_excel_sync.py
│
├── carregar_configuracoes() → dict
│   └── Lê .env, valida vars obrigatórias, suporta nomes legados
│
├── ClienteGLPI
│   ├── __init__(base_url, app_token, user_token)
│   │   └── _iniciar_sessao() — autentica e armazena session_token
│   ├── _atualizar_headers()     — reconstrói headers da session
│   ├── _renovar_sessao()        — auto-healing em 401/403
│   ├── _get(endpoint, params)   — GET resiliente com retry de sessão
│   ├── buscar_chamados_ativos() → list[dict]
│   │   └── Search API com OR de status 1,2,3,4 + forcedisplay dos 6 campos
│   └── buscar_nome_usuario(id)  → str  (com cache em memória)
│
├── SincronizadorExcel
│   ├── __init__(caminho, glpi)
│   ├── _carregar_df()           — lê xlsx existente ou cria DataFrame vazio
│   ├── _salvar_df(df)           — salva, captura PermissionError graciosamente
│   ├── _chamado_para_linha(d)   → dict|None  — normaliza dict da API
│   └── sincronizar(chamados)    — upsert + remoção de inativos
│
├── _formatar_datetime(valor)    → str  — helper de formatação de data
│
└── main()
    └── Loop infinito: buscar → sincronizar → sleep(POLLING_INTERVAL)
```

---

## Fluxo de Execução

```
startup
  └─ carregar_configuracoes()
  └─ ClienteGLPI.__init__()
       └─ _iniciar_sessao()  [GET /initSession]

loop (a cada POLLING_INTERVAL segundos)
  └─ buscar_chamados_ativos()
       └─ GET /search/Ticket?criteria[status IN 1,2,3,4]&forcedisplay[6 campos]
  └─ sincronizar(chamados)
       ├─ _carregar_df()  — lê estado atual do xlsx
       ├─ para cada chamado:
       │    └─ _chamado_para_linha()
       │         └─ buscar_nome_usuario() se requerente_id é número
       ├─ calcula: ids_para_remover = ids_na_planilha - ids_ativos_api
       ├─ monta novo DataFrame (base sem removidos/atualizados + novos)
       └─ _salvar_df()
```

---

## Decisões de Arquitetura

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Um arquivo vs. pacote | Um arquivo | Simplicidade, fácil de copiar/rodar |
| Search API vs. GET /Ticket | Search API com forcedisplay | Batch eficiente, 1 chamada para N tickets |
| Requester lookup | On-demand com cache em dict | Evita N+1, lazy loading |
| Status texto | Mapeamento manual PT-BR | Independente do idioma do GLPI |
| PermissionError | Try/except + skip cycle | Arquivo pode estar aberto pelo usuário |
| Pandas vs openpyxl puro | Pandas | API mais legível para upsert/concat |
| Polling interval | Env var, padrão 300s | Configurável sem tocar no código |

---

## Variáveis de Ambiente

| Variável           | Obrigatória | Padrão                          | Legado aceito      |
|--------------------|-------------|----------------------------------|--------------------|
| `GLPI_URL`         | ✅          | —                                | `VERDANADESK_URL`  |
| `GLPI_USER_TOKEN`  | ✅          | —                                | `USER_TOKEN`       |
| `GLPI_APP_TOKEN`   | ✅          | —                                | `APP_TOKEN`        |
| `POLLING_INTERVAL` | ❌          | `300` (5 min)                    | —                  |
| `EXCEL_PATH`       | ❌          | `chamados_acompanhamento.xlsx`   | —                  |

---

## Arquivos Arquivados

Os arquivos legados (com LLM) foram movidos para `.archive/`:
- `.archive/automation.py` — worker original com LangChain/Gemini
- `.archive/boilerplate.py` — template universal com Pydantic/LLM
- `.archive/run.py`         — bootstrap launcher antigo

Eles servem como referência para a lógica de autenticação GLPI.
