# Arquitetura do Projeto

## Histórico de Pivots

| Versão | Arquitetura           | Status    |
|--------|-----------------------|-----------|
| v1     | LangChain + Gemini/OpenAI LLM | Arquivado em `.archive/` |
| v2     | ETL local → arquivo `.xlsx`   | Substituído |
| v3     | **GLPI → Webhook (Power Automate)** | **Ativa** |

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
│   └── buscar_nome_usuario(id)           → str   — lookup com cache em memória
│
├── _formatar_datetime(valor)  → str   — helper de formatação de data
│
├── _carregar_cache(caminho)   → dict  — lê cache_chamados.json (tolerante a falhas)
├── _salvar_cache_atomico(caminho, cache) — write to .tmp + os.replace()
│
├── SincronizadorWebhook
│   ├── __init__(webhook_url, glpi, cache_path)
│   │   └── carrega cache inicial do disco
│   ├── _chamado_para_payload(chamado) → dict|None  — normaliza dict da API
│   ├── _post_webhook(payload)         — POST isolado, nunca propaga exceção
│   └── sincronizar(chamados_api)      — diff com cache → UPSERT/DELETE → persiste cache
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
  └─ SincronizadorWebhook.__init__()
       └─ _carregar_cache()  [lê cache_chamados.json]

loop (a cada POLLING_INTERVAL segundos)
  └─ buscar_chamados_ativos()
       └─ por categoria: GET /search/Ticket?criteria[cat=X]&forcedisplay[6 campos]
            └─ injeta _cat_id em cada item; filtra status ativos em Python
  └─ sincronizar(chamados)
       ├─ para cada chamado → _chamado_para_payload()
       │    ├─ buscar_nome_usuario()             — se req_id é número (com cache)
       │    ├─ buscar_data_inicio_do_conteudo()  — se field 17 vazio
       │    └─ verificar_ou_criar_tarefa_termo() — se cat == CAT_ID_COM_ATIVO
       │
       ├─ UPSERT: chamado não está no cache OU algum campo mudou
       │    └─ _post_webhook({"Acao": "UPSERT", ...})
       │
       ├─ DELETE: ID existe no cache mas não veio na busca atual
       │    └─ _post_webhook({"Acao": "DELETE", "ID_do_Chamado": id})
       │
       └─ _salvar_cache_atomico()  — persiste novo estado
```

---

## Schemas de Webhook

### UPSERT
```json
{
  "Acao": "UPSERT",
  "ID_do_Chamado": 1234,
  "Titulo": "Contratação João Silva",
  "Status": "Em Atendimento",
  "Tempo_Solucao": "15/06/2026 09:00",
  "Data_Abertura": "01/05/2026 10:30",
  "Requerente": "Maria Souza",
  "Termo_Status": "Pendente de envio"
}
```

### DELETE
```json
{
  "Acao": "DELETE",
  "ID_do_Chamado": 1234
}
```

---

## Decisões de Arquitetura

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Saída de dados | Webhook (Power Automate) | Nuvem, sem PermissionError, colaborativo |
| Estado entre ciclos | `cache_chamados.json` | Evita POSTs repetidos para dados inalterados |
| Escrita do cache | `os.replace()` atômico | Sobrevive a reinicializações no meio da escrita |
| Webhook por chamado | `try/except` individual | Falha de rede não bloqueia demais chamados |
| Search API vs GET /Ticket | Search API com forcedisplay | Batch eficiente, 1 chamada para N tickets |
| Requester lookup | On-demand com cache em dict | Evita N+1, lazy loading |
| Status texto | Mapeamento manual PT-BR | Independente do idioma do GLPI |
| Polling interval | Env var, padrão 300s | Configurável sem tocar no código |

---

## Variáveis de Ambiente

| Variável                               | Obrigatória | Padrão          | Legado aceito     |
|----------------------------------------|-------------|-----------------|-------------------|
| `GLPI_URL`                             | ✅          | —               | `VERDANADESK_URL` |
| `GLPI_USER_TOKEN`                      | ✅          | —               | `USER_TOKEN`      |
| `GLPI_APP_TOKEN`                       | ✅          | —               | `APP_TOKEN`       |
| `CATEGORIA_CONTRATACAO_IDS`            | ✅          | —               | —                 |
| `POWER_AUTOMATE_WEBHOOK_URL`           | ✅          | —               | —                 |
| `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS` | ❌          | desativado      | —                 |
| `POLLING_INTERVAL`                     | ❌          | `300` (5 min)   | —                 |

---

## Arquivos de Estado e Arquivados

| Arquivo | Descrição |
|---------|-----------|
| `cache_chamados.json` | Estado do último ciclo (excluído do git) |
| `.archive/automation.py` | Worker original com LangChain/Gemini |
| `.archive/boilerplate.py` | Template universal com Pydantic/LLM |
| `.archive/run.py` | Bootstrap launcher antigo |
