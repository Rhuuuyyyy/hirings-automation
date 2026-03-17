# hirings-automation

🤖 Automação de Pedidos de Contratação (Verdanadesk / GLPI + LLM)

📌 Visão Geral do Projeto

Este repositório contém um worker em Python concebido para automatizar o processamento de pedidos de "Nova Contratação" no sistema ITSM Verdanadesk (baseado em GLPI).

O sistema atua como um pipeline de ETL (Extract, Transform, Load) impulsionado por Inteligência Artificial:

Extract (Extração): Busca chamados recém-abertos via API Rest do Verdanadesk e usa um LLM (OpenAI via LangChain) para extrair dados estruturados a partir de textos não-estruturados e ruidosos inseridos pelos Recursos Humanos.

Transform (Transformação): Aplica regras de negócio (formatação de telefone, tradução de cargos, definição de licenças Microsoft e RBAC) baseadas no vínculo contratual (PJ/CLT) e no fornecimento de equipamento.

Load (Carga): Gera um template padronizado em inglês e insere-o de volta no chamado original como um Acompanhamento Privado (ITILFollowup), alterando o estado do ticket para "Em Atendimento".

🛠️ Stack Tecnológica

Linguagem: Python 3.x

Integração LLM: langchain-core, langchain-openai (Modelo: gpt-4o-mini)

Validação de Dados: pydantic (Garantia de tipagem do output do LLM)

Pedidos HTTP: requests (Comunicação com a API REST do GLPI/Verdanadesk)

Gestão de Ambiente: python-dotenv

⚙️ Variáveis de Ambiente (.env)

Para que o worker funcione, as seguintes variáveis devem ser declaradas num ficheiro .env na raiz do projeto:

VERDANADESK_URL=https://[seu-dominio][.verdanadesk.com/apirest.php](https://.verdanadesk.com/apirest.php)
USER_TOKEN=[token_do_utilizador_glpi]
APP_TOKEN=[token_da_aplicacao_api_glpi]
OPENAI_API_KEY=[chave_api_openai]
CATEGORIA_CONTRATACAO_IDS=152,153 # IDs das categorias ITIL separados por vírgula


🏗️ Arquitetura e Componentes Principais

1. Contrato de Dados (DadosColaborador)

Classe pydantic.BaseModel que define o esquema estrito de saída esperado pelo LLM. Se o LLM falhar na estruturação, o Pydantic rejeita a resposta. Contém os campos:

nome_completo, is_pj, data_inicio_dd_mm_yyyy, cargo_ingles, centro_custo, cidade_escritorio, telefone, gestor_nome, fornecedor_equipamento.

2. Motor de Regras de Negócio (GeradorDeChamado)

Responsável por consumir o objeto DadosColaborador e aplicar as lógicas empresariais:

Regra PJ/Cooperados: Se is_pj for True, o email recebe o sufixo -ext (ex: nome.sobrenome-ext@dexian.com) e é removida a lista de distribuição global.

Regra de Equipamentos: * Se Fornecedor = DEXIAN: Atribui licença Microsoft F3 e laptop Y.

Se Fornecedor = CLIENTE (Nuvem/BYOD): Atribui licença Microsoft Kiosk e laptop N.

Formatação: Converte datas de DD-MM-YYYY para MM/DD/YY, remove acentuação e converte telefones para o padrão internacional (+55).

3. Orquestrador (VerdanadeskAutomator)

Classe responsável pela comunicação I/O:

Autenticação e gestão de sessão (Session-Token) na API do Verdanadesk.

Polling de novos chamados (Status = 1) baseados nas CATEGORIA_CONTRATACAO_IDS.

Invocação da extrator_chain (LangChain with_structured_output) passando o texto do chamado.

Atualização do ticket via POST (Followup) e PUT (Mudança de Status para 2).

🚀 Como Executar Localmente

Crie o ambiente virtual:

python -m venv .venv


Ative o ambiente virtual:

Windows: .\.venv\Scripts\Activate.ps1

Linux/Mac: source .venv/bin/activate

Instale as dependências:

pip install requests pydantic langchain-core langchain-openai python-dotenv


Configure o ficheiro .env com as suas credenciais.

Inicie o worker (ele rodará em loop a cada 5 minutos):

python automacao_dexian.py


Documentação otimizada para ingestão de contexto por agentes LLM e revisão de código por pares.