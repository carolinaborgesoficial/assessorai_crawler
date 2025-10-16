# AssessorAI Crawler

Sistema de crawler para extração de proposições legislativas de assembleias estaduais brasileiras, desenvolvido com Scrapy e integração com Weaviate.

## 🏗️ Arquitetura do Projeto

```
assessorai_crawler/
├── assessorai_crawler/          # Código principal do Scrapy
│   ├── spiders/                 # Spiders para cada estado
│   │   ├── proposicoeslegislapi.py  # Spider base (classe pai)
│   │   ├── proposicoessp.py         # São Paulo
│   │   ├── proposicoesmg.py         # Minas Gerais
│   │   └── ...                      # Outros estados
│   ├── items.py                 # Definição dos dados estruturados
│   ├── pipelines.py             # Processamento e validação dos dados
│   ├── settings.py              # Configurações do Scrapy
│   └── utils.py                 # Funções utilitárias
├── output/                      # JSONs gerados pelos crawlers
├── importer.py                  # Script para importar dados no Weaviate
├── requirements.txt             # Dependências Python
└── .env                        # Variáveis de ambiente
```

## 🚀 Configuração do Ambiente

### 1. Instalação

```bash
# Clone o repositório
git clone <repo-url>
cd assessorai_crawler

# Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate     # Windows

# Instale as dependências
pip install -r requirements.txt
```

### 2. Configuração das Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto:

```env
# Weaviate Configuration
WEAVIATE_URL="your-weaviate-cluster-url"
WEAVIATE_APIKEY="your-weaviate-api-key"
WEAVIATE_CLASS="Bill"

# OpenAI Configuration (para embeddings)
OPENAI_APIKEY="your-openai-api-key"
```

## 📊 Como Funciona

### 1. Estrutura de Dados

O projeto usa o item `ProposicaoItem` definido em `items.py`:

```python
ProposicaoItem:
- title: str          # Título da proposição
- house: str          # Casa legislativa
- type: str           # Tipo (PL, PEC, etc.)
- number: int         # Número da proposição
- year: int           # Ano
- author: list        # Lista de autores
- subject: str        # Ementa/assunto
- full_text: str      # Texto completo
- url: str            # URL pública
- uuid: str           # Identificador único
- scraped_at: str     # Timestamp da coleta
```

### 2. Pipeline de Processamento

1. **ValidationPipeline**: Valida campos obrigatórios
2. **JsonWriterSinglePipeline**: Salva todos os itens em um único JSON

## 🕷️ Como Desenvolver um Novo Crawler Web

### Metodologia: Do Site à Estrutura de Dados

1. **🔍 Encontre a página da casa legislativa**
   - Identifique o site oficial (ex: `www.al[uf].gov.br`)
   - Localize a seção de "Proposições", "Projetos de Lei" ou similar

2. **📋 Encontre a página que lista os projetos**
   - Busque por páginas de listagem (ex: `/proposicoes`, `/projetos`)
   - Analise a paginação e filtros disponíveis

3. **🔗 Itere pela página, buscando links para projetos individuais**
   - Identifique os seletores CSS/XPath dos links
   - Colete metadados básicos da listagem (título, autor, data)

4. **💾 Armazene as variáveis necessárias**
   - Título da proposição
   - Tipo e número (PL, PEC, etc.)
   - Autor(es)
   - Data de apresentação
   - Ementa/assunto
   - URL pública

5. **📄 Faça download da íntegra e converta para markdown**
   - Acesse página individual do projeto
   - Extraia o texto completo (PDF, HTML, DOC)
   - Converta para markdown limpo

### Passo 1: Estrutura Básica do Spider

```python
# assessorai_crawler/spiders/proposicoes[uf].py
import scrapy
import hashlib
from datetime import datetime
from urllib.parse import urljoin
from ..items import ProposicaoItem

class Proposicoes[CASA]Spider(scrapy.Spider):
    name = 'proposicoes[casa]'
    house = 'Nome da Casa Legislativa'
    allowed_domains = ['www.[site da casa].gov.br']
    start_urls = ['https://www.[site da casa].gov.br/proposicoes']
    
    def parse(self, response):
        """Parse da página de listagem de proposições"""
        # Extrair links para proposições individuais
        proposicao_links = response.css('selector-para-links::attr(href)').getall()
        
        for link in proposicao_links:
            full_url = urljoin(response.url, link)
            yield response.follow(full_url, self.parse_proposicao)
        
        # Paginação
        next_page = response.css('selector-proxima-pagina::attr(href)').get()
        if next_page:
            yield response.follow(next_page, self.parse)
    
    def parse_proposicao(self, response):
        """Parse da página individual da proposição"""
        item = ProposicaoItem()
        
        # Extrair dados básicos
        item['title'] = response.css('h1.titulo::text').get('').strip()
        item['house'] = self.house
        item['url'] = response.url
        
        # Extrair tipo e número do título
        title_parts = item['title'].split()
        item['type'] = title_parts[0] if title_parts else ''
        
        # Extrair número e ano (formato: "123/2024")
        if len(title_parts) > 1:
            try:
                num_year = title_parts[1].split('/')
                item['number'] = int(num_year[0])
                item['year'] = int(num_year[1])
            except (ValueError, IndexError):
                item['number'] = None
                item['year'] = None
        
        # Extrair outros campos
        item['author'] = self.extract_authors(response)
        item['subject'] = response.css('.ementa::text').get('').strip()
        item['presentation_date'] = self.extract_date(response)
        
        # Extrair texto completo
        texto_completo = self.extract_full_text(response)
        item['full_text'] = self.convert_to_markdown(texto_completo)
        item['length'] = len(item['full_text'] or '')
        
        # Metadados
        item['uuid'] = hashlib.md5(item['title'].encode('utf-8')).hexdigest()
        item['scraped_at'] = datetime.now().isoformat()
        
        yield item
    
    def extract_authors(self, response):
        """Extrai lista de autores"""
        authors_text = response.css('.autores::text').get('')
        return [a.strip() for a in authors_text.split(',') if a.strip()]
    
    def extract_date(self, response):
        """Extrai data de apresentação"""
        date_text = response.css('.data-apresentacao::text').get('')
        # Implementar parsing de data específico do site
        return date_text.strip()
    
    def extract_full_text(self, response):
        """Extrai texto completo da proposição"""
        # Método 1: Texto direto na página
        full_text = response.css('.texto-completo').get()
        if full_text:
            return full_text
        
        # Método 2: Link para PDF/DOC
        pdf_link = response.css('a[href*=".pdf"]::attr(href)').get()
        if pdf_link:
            # Fazer request para PDF e processar (ver seção de bibliotecas)
            pass
        
        return ''

```

### Passo 2: Bibliotecas Úteis

Adicione ao `requirements.txt`:

```txt
# Parsing e extração
lxml                    # Parser XML/HTML rápido

# Conversão de documentos
markitdown              # https://github.com/microsoft/markitdown

# Processamento de texto
bleach                  # Limpeza de HTML
textract                # Extração de texto de vários formatos

# Utilidades web
requests-html           # Requests com suporte a JavaScript
selenium                # Automação de browser (para SPAs)
playwright              # Alternativa moderna ao Selenium
```

## 🏃‍♂️ Executando os Crawlers

### Executar um Spider Específico

```bash
# Executar spider de São Paulo
scrapy crawl proposicoessp

# Executar spider de Minas Gerais
scrapy crawl proposicoesmg

# Ver lista de todos os spiders
scrapy list
```

### Executar com Configurações Específicas

```bash
# Salvar em formato específico
scrapy crawl proposicoessp -o output/sp_dados.json

# Limitar número de itens (para testes)
scrapy crawl proposicoessp -s CLOSESPIDER_ITEMCOUNT=10

# Configurar delay entre requests
scrapy crawl proposicoessp -s DOWNLOAD_DELAY=2
```

### Exemplos Práticos de Desenvolvimento

```bash
# 1. Criar novo spider interativamente
scrapy genspider proposicoesgo www.assembleia.go.gov.br

# 2. Testar seletores com scrapy shell
scrapy shell "https://www.assembleia.go.gov.br/proposicoes"

# 3. Debug específico de uma página
scrapy shell "https://www.assembleia.go.gov.br/proposicao/12345"

# 4. Executar com configurações de desenvolvimento
scrapy crawl proposicoesgo \
  -s DOWNLOAD_DELAY=1 \
  -s CLOSESPIDER_ITEMCOUNT=5 \
  -L DEBUG
```

### Comandos Úteis no Scrapy Shell

```python
# No scrapy shell, use estes comandos para testar:

# Testar seletores CSS
response.css('a.proposicao-link').getall()
response.css('h1.titulo::text').get()

# Testar XPath
response.xpath('//a[contains(@href, "proposicao")]/@href').getall()

# Seguir link e testar
fetch('https://site.gov.br/proposicao/123')
response.css('.texto-completo::text').get()

# Testar regex
import re
title = "PL 123/2024"
match = re.match(r'(\w+)\s+(\d+)/(\d+)', title)
if match:
    print(f"Tipo: {match.group(1)}, Número: {match.group(2)}, Ano: {match.group(3)}")
```

## 🔧 Configurações Avançadas

### Modificar Pipelines

Em `settings.py`, você pode ajustar a ordem e configuração dos pipelines:

```python
ITEM_PIPELINES = {
    "assessorai_crawler.pipelines.ValidationPipeline": 100,      # Validação
    "assessorai_crawler.pipelines.JsonWriterSinglePipeline": 300, # Escrita JSON
}
```

## 📋 Checklist para Novo Estado

### Fase 1: Análise e Planejamento
- [ ] Identificar site oficial da casa legislativa
- [ ] Encontrar seção de proposições/projetos de lei
- [ ] Analisar estrutura da página de listagem
- [ ] Identificar sistema de paginação
- [ ] Verificar se requer JavaScript (SPA)
- [ ] Testar seletores com `scrapy shell`

### Fase 2: Desenvolvimento
- [ ] Criar arquivo `proposicoes[casa].py` no diretório `spiders/`
- [ ] Definir `name` , `house` e configurações básicas
- [ ] Implementar `parse()` para listagem
- [ ] Implementar `parse_proposicao()` para páginas individuais
- [ ] Implementar extração de texto completo
- [ ] Implementar conversão para markdown

### Fase 3: Testes
- [ ] Testar spider com poucos items (`CLOSESPIDER_ITEMCOUNT=5`)
- [ ] Validar extração de todos os campos obrigatórios
- [ ] Verificar qualidade da conversão para markdown
- [ ] Testar paginação completa
- [ ] Verificar tratamento de erros

### Fase 4: Validação
- [ ] Executar coleta completa
- [ ] Validar JSON de saída
- [ ] Verificar URLs públicas funcionais
- [ ] Testar importação no Weaviate
- [ ] Documentar peculiaridades do estado

## 🐛 Problemas Comuns

### Problemas de Seletores CSS/XPath

**Seletores não encontram elementos:**
```python
# ❌ Problema: Seletor muito específico
response.css('div.container > div.content > table.proposicoes > tr > td > a')

# ✅ Solução: Seletor mais genérico
response.css('a[href*="proposicao"]')
```

**Elementos carregados via JavaScript:**
```python
# ❌ Problema: Conteúdo não existe no HTML inicial
response.css('.proposicao-dinamica')  # Retorna vazio

# ✅ Solução: Usar Selenium
from selenium import webdriver
driver = webdriver.Chrome()
driver.get(response.url)
# Aguardar carregamento e extrair
```

### Problemas de Encoding

**Caracteres especiais quebrados:**
```python
# ✅ Solução: Configurar encoding correto
def parse(self, response):
    response = response.replace(encoding='utf-8')
    # ... resto do código
```

### Problemas de Rate Limiting

**Site bloqueia requests rápidos:**
```python
# ✅ Configurar delay no settings.py
DOWNLOAD_DELAY = 2  # 2 segundos entre requests
RANDOMIZE_DOWNLOAD_DELAY = 0.5  # Randomizar até 50%

# Ou no spider individual
custom_settings = {
    'DOWNLOAD_DELAY': 3,
    'CONCURRENT_REQUESTS': 1
}
```

## 📚 Recursos Úteis

- [Documentação do Scrapy](https://docs.scrapy.org/)
- [Weaviate Documentation](https://weaviate.io/developers/weaviate)
- [OpenAI API Documentation](https://platform.openai.com/docs)
