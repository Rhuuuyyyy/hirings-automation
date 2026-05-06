# Automação de Tarefas — Termo de Responsabilidade

## Regra de Negócio

Chamados de contratação que envolvem envio de equipamento ao novo funcionário precisam de
um controle de "Termo de responsabilidade" — um documento que o RH/TI envia e que o
funcionário assina. O script garante que essa tarefa existe no GLPI e acompanha seu status.

---

## Configuração

```env
# .env
CATEGORIA_CONTRATACAO_ID_WITH_ASSETS=154   # ID da categoria com envio de equipamento
```

- Variável **opcional**: se omitida ou vazia, todos os chamados recebem `"Sem equipamento"`.
- Aceita um único ID inteiro (não é lista, ao contrário de `CATEGORIA_CONTRATACAO_IDS`).

---

## Coluna na Planilha: "Termo Status"

| Valor                | Condição                                                             |
|----------------------|----------------------------------------------------------------------|
| `Sem equipamento`    | Categoria do chamado ≠ `CATEGORIA_CONTRATACAO_ID_WITH_ASSETS`       |
| `Pendente de envio`  | Tarefa existe mas `state < 2`; ou tarefa recém-criada pelo script   |
| `Termo enviado`      | Tarefa encontrada com `state >= 2` (Done)                           |
| `Erro ao criar tarefa` | Falha na API ao ler ou criar a tarefa (ver logs)                  |

---

## Fluxo Implementado

```
_chamado_para_linha(chamado)
  │
  ├─ cat_id == CATEGORIA_CONTRATACAO_ID_WITH_ASSETS?
  │     NÃO → "Sem equipamento"
  │     SIM → verificar_ou_criar_tarefa_termo(ticket_id)
  │               │
  │               ├─ ticket_id ∈ _termos_concluidos? → "Termo enviado"  (cache)
  │               │
  │               ├─ GET /Ticket/{id}/TicketTask
  │               │     ├─ Itera tasks, busca "_TEXTO_TAREFA_TERMO" (case-insensitive, sem HTML)
  │               │     ├─ Encontrou + state >= 2 → cache + "Termo enviado"
  │               │     ├─ Encontrou + state < 2  → "Pendente de envio"
  │               │     └─ Não encontrou → POST /Ticket/{id}/TicketTask → "Pendente de envio"
  │               │
  │               └─ Qualquer Exception → logger.error + "Erro ao criar tarefa"
```

---

## Detalhes da API GLPI

### Leitura de Tarefas
```
GET /Ticket/{id}/TicketTask
Headers: App-Token, Session-Token

Resposta: array JSON de objetos, ex.:
[
  {
    "id": 10,
    "tickets_id": 42,
    "content": "<p>Envio do termo de responsabilidade</p>",
    "state": 1,        ← 1=To do, 2=Done
    ...
  }
]
```

Retorna `[]` se não há tarefas; retorna corpo vazio (tratado como `{}` pelo `_get()`).

### Criação de Tarefa
```
POST /Ticket/{id}/TicketTask
Body: {"input": {"tickets_id": <id>, "content": "Envio do termo de responsabilidade", "state": 1}}

Resposta: {"id": <novo_id>, "message": "Item successfully added"}
```

### Estados de Tarefa (Planning)
| state | Significado GLPI |
|-------|-----------------|
| 0     | Sem informação  |
| 1     | A fazer (To do) |
| 2     | Feito (Done)    |

Constante no código: `_GLPI_TASK_STATE_DONE = 2`

---

## Cache de Termos Concluídos

`ClienteGLPI._termos_concluidos: set[int]`

- Tickets com `"Termo enviado"` são adicionados ao set durante a varredura.
- Varreduras seguintes pulam a chamada `GET /TicketTask` para esses tickets.
- O cache é **em memória** (resetado ao reiniciar o script). Isso é intencional:
  ao reiniciar, o script re-verifica o estado real do GLPI e reconstrói o cache na
  primeira varredura. Tickets "Pendente de envio" são re-verificados a cada ciclo.

---

## Texto da Tarefa

```python
_TEXTO_TAREFA_TERMO = "Envio do termo de responsabilidade"
```

- Busca **case-insensitive** no conteúdo da tarefa.
- Tags HTML são removidas antes da comparação (`re.sub(r"<[^>]+>", " ", content)`).
- Correspondência por `in` (substring), não por igualdade exata — cobre casos onde
  o GLPI wrappa o texto em `<p>` ou adiciona formatação.
