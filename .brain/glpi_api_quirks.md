# GLPI API — Peculiaridades e Referências

## Endpoint Base

A variável `GLPI_URL` no `.env` **já inclui** `/apirest.php`.  
Exemplo: `http://10.172.8.48/apirest.php`

Todos os endpoints são construídos como `{GLPI_URL}/{recurso}`:
- `http://10.172.8.48/apirest.php/initSession`
- `http://10.172.8.48/apirest.php/search/Ticket`
- `http://10.172.8.48/apirest.php/User/42`

---

## Autenticação (Fluxo de 3 Tokens)

1. **App-Token** — Header fixo `App-Token: <valor>`. Sempre presente.
2. **User-Token** — Enviado **somente** no `initSession` via `Authorization: user_token <valor>`.
3. **Session-Token** — Retornado pelo `initSession`. Enviado em todas as chamadas subsequentes via `Session-Token: <valor>`.

### initSession
```
GET /initSession
Headers:
  App-Token: <APP_TOKEN>
  Authorization: user_token <USER_TOKEN>
  Content-Type: application/json

Resposta: {"session_token": "abc123..."}
```

### Auto-healing de Sessão
Se qualquer endpoint retornar `401` ou `403`, a estratégia é:
1. Limpar o `session_token` atual.
2. Chamar `_iniciar_sessao()` novamente.
3. Retentar a requisição original **uma vez**.

Isso está implementado em `ClienteGLPI._get()`.

---

## Search API — Field IDs para Ticket

Para usar `GET /search/Ticket` com `forcedisplay` e `criteria`, os IDs dos campos são:

| Field ID | Nome no GLPI    | Observação                                  |
|----------|-----------------|---------------------------------------------|
| `1`      | Título (name)   |                                             |
| `2`      | ID do Chamado   | Confirmado pelo código legado (`chamado.get("2")`) |
| `4`      | Requerente      | Pode retornar user_id numérico ou nome texto |
| `7`      | Categoria       |                                             |
| `12`     | Status          | Ver tabela de status abaixo                 |
| `15`     | Data de Criação | Formato: `YYYY-MM-DD HH:MM:SS`              |
| `17`     | Tempo p/ Solução (SLA) | Deadline SLA, formato datetime       |

> **IMPORTANTE**: Para verificar todos os field IDs disponíveis na sua instância:
> ```
> GET /listSearchOptions/Ticket
> ```

### Parâmetro `expand_dropdowns`
- Com `expand_dropdowns=1`: status retorna texto ("Nouveau"), usuário pode retornar nome.
- Sem ele: status retorna ID numérico. **Preferimos sem**, pois fazemos nossa própria tradução para PT-BR.

---

## Status dos Chamados (Mapeamento Numérico)

| ID | Status GLPI Original | Tradução PT-BR    | Ação na Planilha |
|----|----------------------|-------------------|------------------|
| 1  | New                  | Novo              | Manter           |
| 2  | Processing (assigned)| Em Atendimento    | Manter           |
| 3  | Processing (planned) | Em Atendimento    | Manter           |
| 4  | Pending              | Pendente          | Manter           |
| 5  | Solved               | Solucionado       | **Remover**      |
| 6  | Closed               | Fechado           | **Remover**      |

---

## Busca de Usuário por ID

```
GET /User/{user_id}
Resposta relevante:
{
  "id": 42,
  "name": "joao.silva",       <- login, não ideal
  "firstname": "João",
  "realname": "Silva",
  ...
}
```
Nome exibível = `f"{firstname} {realname}".strip()`

**Cache em memória** (`_cache_usuarios: dict[int, str]`) evita chamadas repetidas.

---

## Field 17 (Tempo para Solução) Frequentemente Vazio

A Search API nem sempre retorna o field `17` (`time_to_resolve`) mesmo com `forcedisplay[3]=17`.
Isso ocorre quando o ticket não tem SLA definido ou quando o GLPI não calcula o prazo automaticamente.

**Fallback implementado:** quando o field 17 está vazio, o script faz um `GET /Ticket/{id}` e
aplica regex no campo `content` (HTML bruto do formulário) para extrair o padrão visual que o
solicitante preenche:

```
Data de início: DD-MM-YYYY
```

**Regex usada:**
```python
r"Data de in[íi]cio:\s*(?:<[^>]+>|&nbsp;|\s)*(\d{2}[-/]\d{2}[-/]\d{4})"
```

- `in[íi]cio` → tolera com ou sem acento
- `(?:<[^>]+>|&nbsp;|\s)*` → ignora tags HTML e espaços entre o rótulo e a data
- `(\d{2}[-/]\d{2}[-/]\d{4})` → captura DD-MM-YYYY ou DD/MM/YYYY

A data capturada é normalizada para `DD/MM/YYYY` (troca `-` por `/`).

**Custo extra:** 1 chamada GET por ticket com SLA vazio. Mitigado pelo cache de usuários já existente
(o endpoint de usuário é separado). Tickets com SLA preenchido não fazem essa chamada extra.

---

## Paginação da Search API

O parâmetro `range` controla a paginação:
- `range=0-9999` → retorna até 10.000 registros por chamada.
- A resposta inclui o header `Content-Range` indicando o total real.

---

## Headers Corretos por Tipo de Chamada

| Cenário         | App-Token | Session-Token | Authorization         |
|-----------------|-----------|---------------|-----------------------|
| initSession     | ✅        | ❌            | `user_token <token>`  |
| Demais chamadas | ✅        | ✅            | ❌                    |
