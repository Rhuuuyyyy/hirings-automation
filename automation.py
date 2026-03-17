# ==========================================
# IMPORTAÇÃO DE BIBLIOTECAS (O Arsenal de Ferramentas)
# ==========================================
import os           # Biblioteca para interagir com o Sistema Operacional. Usada para ler variáveis de ambiente de forma segura.
import time         # Biblioteca para lidar com tempo. Usada aqui para fazer o programa "dormir" (pausar) entre as execuções do loop.
import requests     # A biblioteca mais famosa do Python para fazer requisições HTTP (GET, POST, PUT) e falar com APIs externas (como a do Verdanadesk).
import re           # Módulo de Expressões Regulares (Regex). Usado para encontrar e manipular padrões em textos (como extrair só os números de um telefone).
import unicodedata  # Usada para lidar com caracteres especiais e acentuação, garantindo que o texto fique limpo (ex: transformar "João" em "Joao").
from datetime import datetime  # Usada para interpretar e formatar datas, convertendo strings como "10-03-2026" em objetos de tempo reais.

# O Pydantic é o "segurança" da nossa aplicação. Ele garante que os dados que a IA devolver
# estejam exatamente no formato que o restante do código espera, evitando que o programa quebre.
from pydantic import BaseModel, Field

# Ferramentas do LangChain para construir a ponte entre o seu código e a inteligência artificial.
# ChatPromptTemplate: Cria as instruções (o prompt) de forma estruturada.
# ChatOpenAI: O cliente que conecta o seu código aos servidores da OpenAI (usando o modelo GPT).
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

# O dotenv lê o arquivo '.env' e carrega aquelas variáveis (senhas, URLs) para a memória do sistema,
# permitindo que o 'os.getenv' consiga enxergá-las.
from dotenv import load_dotenv

# Executa a função que efetivamente lê o arquivo .env e carrega as chaves.
load_dotenv()

# ==========================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ==========================================
# Aqui, em vez de deixar as senhas expostas no código (o que é uma falha grave de segurança),
# puxamos tudo do ambiente seguro criado pelo dotenv.
VERDANADESK_URL = os.getenv("VERDANADESK_URL")
USER_TOKEN = os.getenv("USER_TOKEN")
APP_TOKEN = os.getenv("APP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Esta variável guarda as filas de chamados que queremos vigiar. Pode conter um ou vários IDs separados por vírgula.
CATEGORIA_CONTRATACAO_IDS = os.getenv("CATEGORIA_CONTRATACAO_IDS")

# O LangChain, por baixo dos panos, procura a chave da OpenAI nesta variável de ambiente específica.
# Este bloco 'if' atua como um sistema de alarme precoce: se você esquecer de colocar a chave no .env,
# o programa morre aqui mesmo avisando o motivo, em vez de dar um erro confuso lá na frente.
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
else:
    raise ValueError("Chave da OpenAI não encontrada no arquivo .env!")

# ==========================================
# 2. MODELOS E REGRAS DE NEGÓCIO (LLM + Pydantic)
# ==========================================

# Definimos o "Contrato de Dados". Esta classe diz como o JSON extraído pela IA DEVE ser.
# Se a IA tentar devolver um 'is_pj' como texto ("Sim") em vez de um booleano (True/False), 
# o Pydantic intercepta, traduz ou barra a operação. Isso traz previsibilidade para sistemas de IA.
class DadosColaborador(BaseModel):
    nome_completo: str
    is_pj: bool = Field(description="True se o texto mencionar CNPJ, 'Substituição: Não' associado a consultoria externa, ou for cooperado")
    data_inicio_dd_mm_yyyy: str
    cargo_ingles: str = Field(description="O cargo da pessoa, traduzido para o inglês corporativo (ex: DevOps PL Analyst)")
    centro_custo: str
    cidade_escritorio: str
    telefone: str
    gestor_nome: str
    fornecedor_equipamento: str = Field(description="DEXIAN ou CLIENTE")

# Esta classe isola as "Regras de Negócio". O princípio aqui é a Separação de Responsabilidades (Separation of Concerns).
# A IA só extrai o dado puro. Esta classe pega o dado puro e aplica as lógicas da sua empresa (formatar telefone, definir licenças, etc).
class GeradorDeChamado:
    def __init__(self, dados: DadosColaborador):
        self.dados = dados # Guarda os dados estruturados dentro do objeto para serem usados pelos métodos abaixo.

    # O @staticmethod indica que esta função não precisa acessar o estado da classe (não usa o 'self').
    # Ela é apenas uma ferramenta utilitária isolada que recebe um texto e devolve ele sem acentos.
    @staticmethod
    def remover_acentos(texto: str) -> str:
        # Normaliza o texto, converte para ASCII (removendo acentos) e volta para string padrão (utf-8).
        return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')

    # Separa o nome completo em partes para usarmos o primeiro e o último nome no e-mail.
    def extrair_nomes(self):
        partes = self.remover_acentos(self.dados.nome_completo).split()
        primeiro_nome, ultimo_sobrenome = partes[0], partes[-1]
        nome_formatado = f"{primeiro_nome}.{ultimo_sobrenome}".lower()
        return primeiro_nome, ultimo_sobrenome, nome_formatado

    # Padroniza o telefone para o padrão internacional usado no Active Directory / Office 365.
    def formatar_telefone(self) -> str:
        # Regex (r'\D') que substitui tudo que NÃO for número por um espaço vazio. Sobram só os dígitos.
        numeros = re.sub(r'\D', '', self.dados.telefone)
        if len(numeros) >= 11: 
            numeros = numeros[-11:] # Garante que só vamos pegar DDD + 9 dígitos, ignorando códigos de país que o RH possa ter digitado.
        return f"+55 {numeros[:2]}{numeros[2:]}" if numeros else "Não informado"

    # Transforma o padrão brasileiro (DD-MM-YYYY) para o padrão americano (MM/DD/YY) exigido pela Dexian global.
    def formatar_data_americana(self) -> str:
        try:
            # strptime lê a string e converte num objeto datetime; strftime converte o datetime de volta para string no novo formato.
            return datetime.strptime(self.dados.data_inicio_dd_mm_yyyy, '%d-%m-%Y').strftime('%m/%d/%y')
        except:
            # Se der erro (ex: a IA extraiu a data num formato muito bizarro), devolve o original para não quebrar o código.
            return self.dados.data_inicio_dd_mm_yyyy

    # Formata o nome do gestor para o padrão "nome.sobrenome".
    def formatar_gestor(self) -> str:
        partes = self.remover_acentos(self.dados.gestor_nome).split()
        return f"{partes[0].lower()}.{partes[-1].lower()}" if len(partes) >= 2 else partes[0].lower()

    # O método principal da classe. Junta todas as peças processadas e monta a string final do e-mail.
    def gerar_template(self) -> str:
        primeiro, ultimo, nome_formatado = self.extrair_nomes()
        
        # Operadores ternários (um 'if/else' em uma linha só) para aplicar as regras de PJ ou CLT.
        email = f"{nome_formatado}-ext@dexian.com" if self.dados.is_pj else f"{nome_formatado}@dexian.com"
        dl = "Distribution/Brazil" if self.dados.is_pj else "Distribution/Brazil Distribution Groups/todos-brasil"
        
        # Aplica as regras de licença e acessos baseadas na origem do equipamento.
        if self.dados.fornecedor_equipamento.upper() == "DEXIAN":
            licenca, rbac, laptop = "Microsoft F3", "RBAC-APPS-ENTRA-VERDANADESK-BR", "Y"
        else:
            licenca, rbac, laptop = "Microsoft Kiosk", "RBAC-APPS-ENTRA-VERDANADESK-CLOUD-USER", "N"

        # Retorna uma f-string multilinhas (as três aspas """) interpolando as variáveis calculadas acima no texto bruto.
        return f"""Hello! Good day!
Please, create an e-mail account for:

Name: {self.remover_acentos(self.dados.nome_completo)}
Display name: {ultimo}, {primeiro}
First name: {primeiro}
Last name: {ultimo}
Profile: {self.dados.cargo_ingles}
Office: {self.dados.cidade_escritorio}
e-mail: {email}
Distribution Lists: {dl}
OU = South America / Brazil / Brasil-Consultants
Description: Brazil External Consultant

{rbac}

Department: {self.dados.centro_custo}
Mobile Phone: {self.formatar_telefone()}
License: {licenca}
Dexian Laptop: {laptop}
Reporting Manager: {self.formatar_gestor()}
Employee ID: Info pending – will be added later.  
Employee hire date: {self.formatar_data_americana()}

Please, set the option “User must change the password at next logon" to TRUE … it is very important!
Thank you very much!"""

# ==========================================
# 3. INTEGRAÇÃO VERDANADESK (GLPI API)
# ==========================================
# Esta classe encapsula toda a comunicação com o mundo externo (A API de chamados e a IA).
class VerdanadeskAutomator:
    def __init__(self):
        # Ao instanciar a classe, ela já faz o login na API e guarda o token da sessão.
        self.session_token = self._iniciar_sessao()
        
        # Headers padrão exigidos pela API do GLPI/Verdanadesk para todas as requisições futuras.
        self.headers = {
            "App-Token": APP_TOKEN,
            "Session-Token": self.session_token,
            "Content-Type": "application/json"
        }
        
        # === CONFIGURAÇÃO DO PIPELINE DE IA ===
        # Definimos o modelo (gpt-4o-mini é rápido e barato, ideal para tarefas repetitivas de extração).
        # temperature=0 significa que não queremos criatividade. Queremos respostas exatas e previsíveis.
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        
        # Montamos uma "Chain" (corrente) do LangChain. 
        # Passamos o texto bruto para o template, mandamos para o LLM e, na saída (.with_structured_output),
        # obrigamos a IA a formatar a resposta para encaixar perfeitamente no nosso modelo Pydantic 'DadosColaborador'.
        self.extrator_chain = ChatPromptTemplate.from_messages([
            ("system", "Extraia os dados do chamado de contratação de TI seguindo estritamente o esquema JSON."),
            ("human", "{texto}")
        ]) | llm.with_structured_output(DadosColaborador)

    # Método interno (indicado pelo '_' no início do nome) que faz a autenticação.
    def _iniciar_sessao(self):
        url = f"{VERDANADESK_URL}/initSession"
        headers = {"App-Token": APP_TOKEN, "Authorization": f"user_token {USER_TOKEN}"}
        response = requests.get(url, headers=headers)
        
        # Se a API retornar um erro (ex: 401 Unauthorized por token inválido), o raise_for_status interrompe o script e avisa.
        response.raise_for_status() 
        return response.json().get("session_token")

    # Método que consulta o sistema de chamados procurando trabalho novo.
    def buscar_novos_chamados(self):
        url = f"{VERDANADESK_URL}/search/Ticket"
        
        # Transforma a string do .env "152,153" em uma lista de strings reais: ['152', '153']
        ids_categorias = CATEGORIA_CONTRATACAO_IDS.split(',')
        chamados_encontrados = []

        # Faz um loop para buscar primeiro os chamados da fila 152, e depois da fila 153.
        for cat_id in ids_categorias:
            # Esses "criteria" são a forma como a API do GLPI estrutura buscas. 
            # É equivalente a dizer no banco de dados: WHERE field(7) == ID AND field(12) == Status Novo.
            params = {
                "criteria[0][field]": 7,  # Campo 7 é o ID da Categoria
                "criteria[0][searchtype]": "equals", 
                "criteria[0][value]": cat_id.strip(), # strip() remove eventuais espaços em branco acidentais
                "criteria[1][link]": "AND", 
                "criteria[1][field]": 12, # Campo 12 é o Status do Chamado
                "criteria[1][searchtype]": "equals", 
                "criteria[1][value]": 1   # Status 1 significa "Novo" (Não atribuído)
            }
            response = requests.get(url, headers=self.headers, params=params)
            
            # Se a requisição deu certo (Status 200), adicionamos os chamados encontrados na nossa lista geral.
            if response.status_code == 200:
                dados = response.json().get("data", [])
                chamados_encontrados.extend(dados)

        return chamados_encontrados

    # Orquestra todo o trabalho para um único chamado. É a união de todas as classes.
    def processar_chamado(self, ticket_id):
        # 1. Pega o conteúdo bruto do chamado batendo na rota /Ticket/{id}
        texto = requests.get(f"{VERDANADESK_URL}/Ticket/{ticket_id}", headers=self.headers).json().get("content", "")
        if not texto: return # Se o chamado estiver vazio, ignora e segue a vida.

        try:
            # 2. IA LENDO: Passa o texto bagunçado para a corrente do LangChain, que devolve o objeto Pydantic limpinho.
            dados_estruturados = self.extrator_chain.invoke({"texto": texto})
            
            # 3. TRANSFORMANDO: Instancia a classe de regras com os dados limpos e pede para ela gerar o texto final em inglês.
            template_final = GeradorDeChamado(dados_estruturados).gerar_template()
            
            # 4. ENVIANDO DE VOLTA: Monta o "payload" (corpo da requisição) para adicionar um comentário (ITILFollowup).
            payload = {"input": {"items_id": ticket_id, "itemtype": "Ticket", "content": template_final, "is_private": 1}}
            requests.post(f"{VERDANADESK_URL}/Ticket/{ticket_id}/ITILFollowup", headers=self.headers, json=payload)
            
            # 5. ATUALIZANDO STATUS: Muda o chamado para "Em Atendimento" (status: 2) para o bot não ficar processando o mesmo chamado para sempre.
            requests.put(f"{VERDANADESK_URL}/Ticket/{ticket_id}", headers=self.headers, json={"input": {"id": ticket_id, "status": 2}})
            
            print(f"✅ Ticket #{ticket_id} processado e atualizado!")
            
        # O bloco except funciona como um airbag. Se a IA falhar na extração ou der erro na API,
        # o script apenas avisa que aquele chamado falhou, mas NÃO quebra o loop inteiro. Ele vai tentar o próximo chamado.
        except Exception as e:
            print(f"!!! Erro ao processar Ticket #{ticket_id}: {e}")

# ==========================================
# 4. LOOP DE EXECUÇÃO (Polling / Worker)
# ==========================================
# O 'if __name__ == "__main__":' garante que este código só rode se o arquivo for executado diretamente,
# e não se for importado como um módulo em outro script. É uma boa prática padrão em Python.
if __name__ == "__main__":
    print(f"Automação Verdanadesk iniciada. Consultando a lista de chamados a cada 5 minutos...")
    try:
        automator = VerdanadeskAutomator()
        
        # O "while True" cria um loop infinito (Daemon). É assim que "workers" de backend ficam vigiando processos para sempre.
        while True:
            chamados = automator.buscar_novos_chamados() # Olha as filas...
            for chamado in chamados:
                automator.processar_chamado(chamado['id']) # Processa quem achou...
            
            # Após checar tudo, manda o sistema operacional "congelar" este script por 300 segundos (5 minutos).
            # Isso impede que o seu programa sobrecarregue a API do Verdanadesk fazendo milhares de requisições por segundo.
            time.sleep(300) 
            
    # Se ocorrer um erro cataclísmico (como ficar sem internet) que quebre o loop principal, o script avisa antes de morrer.
    except Exception as e:
        print(f"Erro crítico: {e}")