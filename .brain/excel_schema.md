# Schema do Excel — chamados_acompanhamento.xlsx

## Arquivo de Saída

- **Caminho padrão**: `chamados_acompanhamento.xlsx` (raiz do projeto)
- **Configurável via**: variável de ambiente `EXCEL_PATH`
- **Biblioteca**: `openpyxl` via `pandas` (`df.to_excel()`) + pós-processamento de estilo

---

## Colunas (em ordem)

| Coluna               | Tipo Python | Fonte na API GLPI        | Observações                                          |
|----------------------|-------------|--------------------------|------------------------------------------------------|
| `ID do Chamado`      | `int`       | Field `2` (search API)   | Chave primária para upsert/delete                    |
| `Título`             | `str`       | Field `1` (search API)   |                                                      |
| `Status`             | `str`       | Field `12` → STATUS_MAP  | IDs numéricos traduzidos para PT-BR                  |
| `Tempo para Solução` | `str`       | Field `17` ou regex HTML | Datetime `DD/MM/YYYY HH:MM`; fallback extrai do body |
| `Data de Abertura`   | `str`       | Field `15` (search API)  | Datetime formatado como `DD/MM/YYYY HH:MM`           |
| `Requerente`         | `str`       | Field `4` → `/User/{id}` | Lookup de nome com cache                             |
| `Termo Status`       | `str`       | `/Ticket/{id}/TicketTask`| Ver `.brain/task_automation.md`                      |

---

## Regras de Sincronização

### Inserção
- Chamados **novos** (ID não presente na planilha) com status ativo (1, 2, 3, 4) são adicionados.

### Atualização (Upsert)
- Chamados **existentes** (ID já na planilha) têm todos os campos substituídos com os dados mais recentes.
- Implementação: remove a linha antiga do DataFrame, insere a linha nova.

### Remoção
- Chamados com status `5` (Solucionado) ou `6` (Fechado) **não aparecem** na busca ativa.
- Qualquer ID presente na planilha mas **ausente** do resultado da API é removido.
- Isso captura tanto chamados resolvidos quanto chamados excluídos/spam.

---

## Tratamento de Arquivo Aberto

Se o usuário tiver o Excel aberto ao tentar salvar:
- `PermissionError` é capturado silenciosamente.
- Um `logger.warning` é emitido.
- A planilha em memória é descartada.
- **A próxima varredura** (5 minutos depois) tentará salvar novamente com dados frescos.

O script nunca crasha por causa de um arquivo aberto.

---

## Formato de Datas

Datas chegam da API como `YYYY-MM-DD HH:MM:SS` e são formatadas para `DD/MM/YYYY HH:MM`.

Função utilitária: `_formatar_datetime(valor: Any) -> str` em `glpi_to_excel_sync.py`.

---

## Formatação Visual (openpyxl pós-salvamento)

O pandas salva os dados puros via `df.to_excel()`. Em seguida, `_aplicar_formatacao_excel()`
abre o arquivo com `load_workbook()` e aplica estilo, depois salva novamente. Os dois passos
são isolados por `try/except` — se a formatação falhar, os dados já foram persistidos.

| Recurso              | Detalhe                                                              |
|----------------------|----------------------------------------------------------------------|
| Cabeçalho            | Negrito, fundo azul `#1F4E79`, fonte branca, altura 22 pt           |
| Freeze panes         | `A2` — primeira linha sempre visível ao rolar                        |
| AutoFilter           | Em toda a faixa de dados (`ws.dimensions`)                           |
| Largura de colunas   | `max(len(cabeçalho), len(maior_dado)) + 4`, cap 65 chars             |
| Alinhamento central  | `ID do Chamado`, `Status`, `Tempo para Solução`, `Data de Abertura`, `Termo Status` |
| Alinhamento esquerda | `Título`, `Requerente`                                               |

Constantes relevantes: `_COLUNAS_CENTRADAS`, `_COR_CABECALHO`, `_LARGURA_MAXIMA_COLUNA`.

---

## Constante de Referência (no código)

```python
COLUNAS_EXCEL = [
    "ID do Chamado",
    "Título",
    "Status",
    "Tempo para Solução",
    "Data de Abertura",
    "Requerente",
    "Termo Status",
]
```
