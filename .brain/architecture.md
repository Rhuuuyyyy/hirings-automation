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
│   ├── __init__(base_url, app_token, user_token, categoria_ids, cat_id_com_ativo)
│   │   └── _iniciar_sessao() — autentica e armazena session_token
│   ├── _atualizar_headers()              — reconstrói headers da session
│   ├── _renovar_sessao()                 — auto-healing em 401/403
│   ├── _get(url)                         — GET resiliente com retry de sessão
│   ├── _post(url, payload)               — POST resiliente com retry de sessão
│   ├── buscar_chamados_ativos() → list[dict]
│   │   └── Search API por categoria + forcedisplay dos 6 campos; injeta _cat_id
│   ├── buscar_data_inicio_do_conteudo(id) → str  — fallback regex no HTML do ticket
│   ├── verificar_ou_criar_tarefa_termo(id) → str — controle de ativo com cache
│   └── buscar_nome_usuario(id)           → str   (com cache em memória)
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
       └─ por categoria: GET /search/Ticket?criteria[cat=X]&forcedisplay[6 campos]
            └─ injeta _cat_id em cada item retornado
  └─ sincronizar(chamados)
       ├─ _carregar_df()  — lê estado atual do xlsx
       ├─ para cada chamado:
       │    └─ _chamado_para_linha()
       │         ├─ buscar_nome_usuario() se requerente_id é número
       │         ├─ buscar_data_inicio_do_conteudo() se field 17 vazio
       │         └─ verificar_ou_criar_tarefa_termo() se cat == CAT_ID_COM_ATIVO
       │              ├─ GET /Ticket/{id}/TicketTask
       │              ├─ POST /Ticket/{id}/TicketTask  (se tarefa não existe)
       │              └─ retorna "Termo enviado" | "Pendente de envio" | "Erro ao criar tarefa"
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

| Variável                               | Obrigatória | Padrão                          | Legado aceito      |
|----------------------------------------|-------------|----------------------------------|--------------------|
| `GLPI_URL`                             | ✅          | —                                | `VERDANADESK_URL`  |
| `GLPI_USER_TOKEN`                      | ✅          | —                                | `USER_TOKEN`       |
| `GLPI_APP_TOKEN`                       | ✅          | —                                | `APP_TOKEN`        |
| `CATEGORIA_CONTRATACAO_IDS`            | ✅          | —                                | —                  |
| `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS` | ❌          | desativado                       | —                  |
| `POLLING_INTERVAL`                     | ❌          | `300` (5 min)                    | —                  |
| `EXCEL_PATH`                           | ❌          | `chamados_acompanhamento.xlsx`   | —                  |

---

## Arquivos Arquivados

Os arquivos legados (com LLM) foram movidos para `.archive/`:
- `.archive/automation.py` — worker original com LangChain/Gemini
- `.archive/boilerplate.py` — template universal com Pydantic/LLM
- `.archive/run.py`         — bootstrap launcher antigo

Eles servem como referência para a lógica de autenticação GLPI.
