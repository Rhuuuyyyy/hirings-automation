# Roadmap e Estado do Projeto

## Estado Atual (Maio 2026) — v2.0 ESTÁVEL

- [x] Autenticação GLPI com auto-healing de sessão
- [x] Polling de chamados ativos (status 1, 2, 3, 4)
- [x] Sincronização Excel: insert + upsert + delete
- [x] Tradução de status IDs → PT-BR
- [x] Lookup de nome do requerente com cache
- [x] Tratamento gracioso de PermissionError (Excel aberto)
- [x] Configuração 100% via `.env`
- [x] Segundo cérebro em `.brain/`

---

## Histórico de Versões

### v1.0 (legado, arquivado)
- Pipeline ETL com LangChain + Google Gemini
- Extração de dados de contratação via LLM (structured output)
- Geração de templates de e-mail para onboarding
- Dependências: `langchain-core`, `langchain-google-genai`, `pydantic`

### v2.0 (atual)
- **Pivot**: sem LLM, sem NLP
- Sincronizador GLPI → Excel simples e robusto
- Script único: `glpi_to_excel_sync.py`
- Dependências mínimas: `requests`, `pandas`, `openpyxl`, `python-dotenv`

---

## Melhorias Futuras (Backlog)

### Prioridade Alta
- [ ] Notificação por e-mail/Teams quando um novo chamado crítico entra na fila
- [ ] Filtro por categoria GLPI (para focar em categorias específicas, como contratações)
- [ ] Formatação condicional no Excel (ex: linha vermelha se SLA estiver vencendo)

### Prioridade Média
- [ ] Suporte a múltiplas planilhas (abas) por status
- [ ] Log de histórico de mudanças (ex: "chamado #123 mudou de Pendente para Em Atendimento às 14h")
- [ ] Dashboard HTML gerado como alternativa ao Excel
- [ ] Pré-carregamento em bulk de usuários (`GET /User?range=0-9999`) para evitar round-trips

### Prioridade Baixa
- [ ] Modo de execução agendado via `schedule` ou `cron` em vez de `while True + sleep`
- [ ] Suporte a múltiplas instâncias GLPI
- [ ] Testes unitários com mock da API GLPI

---

## Notas de Campo

- A instância GLPI usa URL interna `http://10.172.8.48/apirest.php` (sem HTTPS).
- O campo `User-Agent` pode ser necessário em algumas versões do GLPI para evitar bloqueio (ver `automation.py` legado).
- Field IDs da Search API devem ser validados com `GET /listSearchOptions/Ticket` se houver retornos inesperados.
