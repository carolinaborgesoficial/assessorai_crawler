# Pipeline de Extração de PDFs com Google Gemini

Este documento explica como funciona o sistema de download e extração de texto de PDFs usando o Google Gemini.

## 🏗️ Arquitetura

O sistema usa 3 pipelines em sequência:

1. **ProposicaoFilesPipeline**: Baixa arquivos PDF das proposições
2. **GeminiPDFExtractionPipeline**: Extrai texto dos PDFs usando Gemini
3. **ValidationPipeline**: Valida dados antes de salvar
4. **JsonWriterSinglePipeline**: Salva tudo em JSON

## 📋 Configuração

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar API do Gemini

Adicione sua chave da API do Gemini no arquivo `.env`:

```env
GEMINI_API_KEY="sua-chave-aqui"
```

Para obter uma chave gratuita:
1. Acesse https://aistudio.google.com/app/apikey
2. Crie uma nova API key
3. Copie e cole no arquivo `.env`

### 3. Estrutura de Pastas

Os arquivos serão salvos em:
```
downloads/
  └── proposicoespcd/
      └── 2025/
          ├── 123_2025_abc123.pdf
          ├── 124_2025_def456.pdf
          └── ...
```

## 🕷️ Como Usar nos Spiders

### Exemplo Básico

```python
import scrapy
from assessorai_crawler.items import ProposicaoItem

class MeuSpider(scrapy.Spider):
    name = "meuspider"
    
    def parse_detail(self, response):
        item = ProposicaoItem()
        
        # Preencher campos básicos
        item['title'] = response.css('h1::text').get()
        item['house'] = 'Casa Legislativa'
        item['url'] = response.url
        # ... outros campos ...
        
        # Coletar URLs de PDFs
        file_urls = []
        for link in response.css('a[href$=".pdf"]'):
            pdf_url = response.urljoin(link.attrib['href'])
            file_urls.append(pdf_url)
        
        item['file_urls'] = file_urls  # O pipeline fará o resto!
        
        yield item
```

### O que Acontece Automaticamente

1. **Download**: `ProposicaoFilesPipeline` baixa todos os PDFs listados em `file_urls`
2. **Extração**: `GeminiPDFExtractionPipeline` processa cada PDF com Gemini
3. **Preenchimento**: O campo `full_text` é automaticamente preenchido com o texto extraído
4. **Salvamento**: Tudo é salvo em JSON

## 🎯 Prompt de Extração

O pipeline usa um prompt especializado para documentos legislativos:

```
Você é um assistente especializado em extrair texto de documentos legislativos brasileiros.

Extraia o texto completo deste documento PDF, preservando:
- A estrutura de artigos, parágrafos e incisos
- Numeração e formatação legal
- Texto de justificativas e ementas

Retorne apenas o texto extraído em formato markdown, sem comentários adicionais.
Organize o texto de forma clara e estruturada.
```

### Customizar o Prompt

Edite o arquivo `pipelines.py`, na classe `GeminiPDFExtractionPipeline`:

```python
self.extraction_prompt = """
Seu prompt customizado aqui...
"""
```

## 🔧 Configurações Avançadas

### Desabilitar Extração de PDF

Se quiser apenas baixar os PDFs sem extrair texto:

```python
# settings.py
ITEM_PIPELINES = {
    "assessorai_crawler.pipelines.ProposicaoFilesPipeline": 1,
    # Comentar a linha abaixo para desabilitar extração
    # "assessorai_crawler.pipelines.GeminiPDFExtractionPipeline": 2,
    "assessorai_crawler.pipelines.ValidationPipeline": 100,
    "assessorai_crawler.pipelines.JsonWriterSinglePipeline": 300,
}
```

### Mudar Local de Download

```python
# settings.py
FILES_STORE = 'minha_pasta_personalizada'
```

### Ajustar Tempo de Expiração

```python
# settings.py
FILES_EXPIRES = 90  # Dias (0 = nunca expira)
```

## 📊 Campos do ProposicaoItem

### Campos Obrigatórios

- `title`: Título da proposição
- `house`: Casa legislativa
- `subject`: Ementa/assunto
- `url`: URL pública da proposição
- `full_text`: Texto completo (preenchido automaticamente)

### Campos para Download de Arquivos

- `file_urls`: Lista de URLs de PDFs para baixar
- `files`: Lista de caminhos dos arquivos baixados (preenchido automaticamente)

### Exemplo Completo

```python
item = ProposicaoItem()
item['title'] = 'PL 123/2025'
item['house'] = 'Câmara Municipal'
item['type'] = 'PL'
item['number'] = 123
item['year'] = 2025
item['author'] = ['Vereador A', 'Vereador B']
item['subject'] = 'Dispõe sobre...'
item['url'] = 'https://site.gov.br/pl/123'
item['uuid'] = hashlib.md5(item['title'].encode()).hexdigest()
item['scraped_at'] = datetime.now().isoformat()

# URLs dos PDFs
item['file_urls'] = [
    'https://site.gov.br/pdf/123.pdf',
    'https://site.gov.br/pdf/123-emenda.pdf'
]

# Estes campos são preenchidos automaticamente:
# item['files'] = [...]  # Pelo ProposicaoFilesPipeline
# item['full_text'] = '...'  # Pelo GeminiPDFExtractionPipeline
# item['length'] = 12345  # Pelo GeminiPDFExtractionPipeline

yield item
```

## 🚀 Exemplo Prático: Poços de Caldas

```bash
# Executar spider de Poços de Caldas para 2025
scrapy crawl proposicoespcd -a ano=2025

# O spider irá:
# 1. Acessar página de listagem
# 2. Para cada proposição, entrar na página de detalhes
# 3. Coletar URLs de todos os PDFs
# 4. Baixar PDFs automaticamente
# 5. Extrair texto com Gemini
# 6. Salvar JSON com texto completo
```

## ⚠️ Considerações

### Custos da API

O Gemini possui um tier gratuito generoso, mas fique atento:
- **Gemini 1.5 Flash**: 15 requisições/minuto (gratuito)
- **Limite diário**: Verifique em https://aistudio.google.com/app/apikey

### Tratamento de Erros

O pipeline loga erros e continua:
```python
# Se um PDF falhar, os outros continuam sendo processados
# Erros são logados mas não interrompem a execução
```

### Performance

- PDFs grandes podem levar alguns segundos
- O Gemini processa em batch quando possível
- Arquivos são cacheados localmente

## 🐛 Debug

### Ver logs detalhados

```bash
scrapy crawl proposicoespcd -a ano=2025 -L DEBUG
```

### Testar apenas 5 itens

```bash
scrapy crawl proposicoespcd -a ano=2025 -s CLOSESPIDER_ITEMCOUNT=5
```

### Verificar arquivos baixados

```bash
ls -la downloads/proposicoespcd/2025/
```

## 📚 Recursos

- [Documentação do Scrapy FilesPipeline](https://docs.scrapy.org/en/latest/topics/media-pipeline.html)
- [Documentação do Google Gemini](https://ai.google.dev/docs)
- [Gemini API Pricing](https://ai.google.dev/pricing)
