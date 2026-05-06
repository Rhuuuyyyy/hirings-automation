# Integração Microsoft Graph API — SharePoint / OneDrive

## Visão Geral

O `SincronizadorExcel` foi migrado do salvamento local (`openpyxl` + pandas)
para atualização direta na nuvem via **Microsoft Graph API**.

A planilha `chamados_acompanhamento.xlsx` vive em um SharePoint/OneDrive for Business.
O script usa **Client Credentials Flow** (app-only, sem interação humana) — ideal para
workers rodando em background sem janela de login.

---

## Fluxo de Autenticação

```
Azure App (Client ID + Secret) ──POST──▶ login.microsoftonline.com/{tenant}/oauth2/v2.0/token
                                         ◀── access_token (Bearer, válido 1h)

access_token ──Header Authorization──▶ graph.microsoft.com/v1.0/...
```

O token expira em ~60 min. O cliente deve renovar automaticamente comparando
`time.time() >= token_expires_at`.

---

## Permissões de API necessárias

| Permissão             | Tipo        | Finalidade                                      |
|-----------------------|-------------|-------------------------------------------------|
| `Files.ReadWrite.All` | Application | Ler e escrever workbooks em qualquer drive      |
| `Sites.ReadWrite.All` | Application | Necessário se o arquivo estiver em site de equipe do SharePoint (não OneDrive pessoal) |

> **Atenção:** permissões Application precisam de **Admin Consent** —
> um administrador global deve aprovar no portal do Azure.

---

## Variáveis de Ambiente

```env
# Azure / Microsoft 365
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=seu_client_secret_aqui

# Localização do arquivo no SharePoint/OneDrive
SHAREPOINT_DRIVE_ID=b!...      # ID do Drive (Document Library)
SHAREPOINT_FILE_ID=...          # ID do Item (o arquivo .xlsx)

# Workbook interno
SHAREPOINT_SHEET_NAME=Chamados         # Nome da aba (worksheet)
SHAREPOINT_TABLE_NAME=TabelaChamados   # Nome da Excel Table dentro da aba
```

---

## Estratégia de Escrita: Table API (clear + repopulate)

```
GET  /drives/{drive_id}/items/{file_id}/workbook/tables/{table}/rows
     → lê estado atual (para log de diff)

DELETE /workbook/tables/{table}/rows/itemAt(index={i})
     → deletar linhas de baixo pra cima (evita index-shift)
     → loop: for i in range(row_count-1, -1, -1)

POST /workbook/tables/{table}/rows/add
     Body: {"values": [[row1], [row2], ...]}
     → insere todas as linhas de uma vez (batch)
```

Vantagens sobre Range API:
- Não é necessário calcular endereço de range
- A Table expande/contrai automaticamente
- AutoFilter e formatação do cabeçalho são preservados
- Usuários podem ter colunas extras na planilha — não são afetadas

---

## Endpoints Principais

```
Base: https://graph.microsoft.com/v1.0

# Listar linhas da tabela
GET  /drives/{drive_id}/items/{file_id}/workbook/tables/{table}/rows

# Contar linhas
GET  /drives/{drive_id}/items/{file_id}/workbook/tables/{table}/rows/count

# Deletar linha por índice (0-based, de baixo pra cima)
DELETE /drives/{drive_id}/items/{file_id}/workbook/tables/{table}/rows/itemAt(index={i})

# Inserir linhas em batch
POST /drives/{drive_id}/items/{file_id}/workbook/tables/{table}/rows/add
Body: {"values": [["ID", "Título", ...], [...], ...]}

# (Opcional) Criar workbook session para operações atômicas
POST /drives/{drive_id}/items/{file_id}/workbook/createSession
Body: {"persistChanges": true}
→ retorna sessionId; incluir em header: workbook-session-id: {id}
```

---

## Onde encontrar Drive ID e File ID

Após criar o app e conceder permissões (ver guia abaixo):

```bash
# 1. Listar sites SharePoint (encontrar o site correto)
GET https://graph.microsoft.com/v1.0/sites?search=*

# 2. Listar drives do site
GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives

# 3. Navegar pelo drive para achar o arquivo
GET https://graph.microsoft.com/v1.0/drives/{drive-id}/root/children

# Ou localizar pelo caminho relativo:
GET https://graph.microsoft.com/v1.0/drives/{drive-id}/root:/Documentos/chamados_acompanhamento.xlsx
→ retorna o objeto com "id" = SHAREPOINT_FILE_ID
```

Use o **Graph Explorer** (https://developer.microsoft.com/graph/graph-explorer) para
fazer essas chamadas de forma interativa antes de colocar no `.env`.

---

## Status de Implementação

- [ ] Azure App registrado (aguardando setup do usuário)
- [ ] Admin Consent concedido
- [ ] Drive ID e File ID descobertos
- [ ] `.env` preenchido com todas as vars
- [ ] `SincronizadorExcel` refatorado para Graph API
- [x] Estratégia definida (Table API, clear + repopulate)
- [x] Documentação `.brain/` criada
