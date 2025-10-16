import json
import os
from scrapy.exceptions import DropItem
from scrapy.pipelines.files import FilesPipeline
from scrapy import Request
import google.generativeai as genai
from dotenv import load_dotenv
import hashlib
from datetime import datetime

load_dotenv()

class JsonWriterPipeline:
    def open_spider(self, spider):
        self.output_dir = f'output/{spider.slug}'
        os.makedirs(self.output_dir, exist_ok=True)

    def process_item(self, item, spider):
        filename = f"{item['uuid']}.json"
        path = os.path.join(self.output_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(dict(item), f, ensure_ascii=False, indent=2)
        return item

class JsonWriterSinglePipeline:
    def open_spider(self, spider):
        # Inicializa a lista de itens
        self.items = []
        # Garante pasta de saída
        output_dir = f'output'
        os.makedirs(output_dir, exist_ok=True)
        self.file_path = os.path.join(output_dir, f'{spider.slug}_proposicoes.json')

    def process_item(self, item, spider):
        # Coleta cada item para depois gravar em lote
        self.items.append(dict(item))
        return item

    def close_spider(self, spider):
        # Grava todos os itens em um único JSON
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

class ValidationPipeline:
    """Valida itens antes de enviá-los ao pipeline de escrita"""
    def process_item(self, item, spider):
        # Verifica se o item implementa validação
        missing = []
        if hasattr(item, 'missing_fields'):
            missing = item.missing_fields()
        if missing:
            spider.logger.warning(
                f"Descartando item incompleto no pipeline (uuid={item.get('uuid')}), faltam: {missing}"
            )
            raise DropItem(f"Campos faltando: {missing}")
        return item


class ProposicaoFilesPipeline(FilesPipeline):
    """Pipeline customizado para baixar arquivos de proposições"""
    
    def get_media_requests(self, item, info):
        """Baixa todos os arquivos listados em file_urls"""
        urls = item.get('file_urls', [])
        for url in urls:
            yield Request(url)
    
    def file_path(self, request, response=None, info=None, *, item=None):
        """Define o caminho onde o arquivo será salvo"""
        # Criar estrutura de pastas: files/{spider_name}/{year}/{number}/
        spider_name = info.spider.name
        year = item.get('year', 'unknown')
        number = item.get('number', 'unknown')
        
        # Extrair nome do arquivo da URL
        url_hash = hashlib.md5(request.url.encode()).hexdigest()
        ext = os.path.splitext(request.url)[1] or '.pdf'
        filename = f"{number}_{year}_{url_hash}{ext}"
        
        return f"{spider_name}/{year}/{filename}"
    
    def item_completed(self, results, item, info):
        """Adiciona informações dos arquivos baixados ao item"""
        file_paths = [x['path'] for ok, x in results if ok]
        if file_paths:
            item['files'] = file_paths
        return item


class GeminiPDFExtractionPipeline:
    """Pipeline que usa Google Gemini para extrair texto de PDFs"""
    
    def __init__(self):
        # Configurar API do Gemini
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY não encontrada no arquivo .env")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Prompt para extração de texto legislativo
        self.extraction_prompt = """
Você é um assistente especializado em extrair texto de documentos legislativos brasileiros.

Extraia o texto completo deste documento PDF, preservando:
- A estrutura de artigos, parágrafos e incisos
- Numeração e formatação legal
- Texto de justificativas e ementas

Retorne apenas o texto extraído em formato markdown, sem comentários adicionais.
Organize o texto de forma clara e estruturada.
"""
    
    def process_item(self, item, spider):
        """Processa PDFs baixados e extrai texto usando Gemini"""
        files = item.get('files', [])
        
        if not files:
            spider.logger.warning(f"Item {item.get('title')} não possui arquivos para processar")
            return item
        
        extracted_texts = []
        files_dir = spider.settings.get('FILES_STORE', 'downloads')
        
        for file_path in files:
            full_path = os.path.join(files_dir, file_path)
            
            if not os.path.exists(full_path):
                spider.logger.warning(f"Arquivo não encontrado: {full_path}")
                continue
            
            try:
                # Upload do arquivo para o Gemini
                spider.logger.info(f"Processando PDF: {file_path}")
                uploaded_file = genai.upload_file(full_path)
                
                # Extrair texto usando o modelo
                response = self.model.generate_content([
                    self.extraction_prompt,
                    uploaded_file
                ])
                
                extracted_text = response.text
                extracted_texts.append(extracted_text)
                
                spider.logger.info(f"Texto extraído com sucesso de {file_path} ({len(extracted_text)} caracteres)")
                
                # Limpar arquivo do Gemini
                genai.delete_file(uploaded_file.name)
                
            except Exception as e:
                spider.logger.error(f"Erro ao processar {file_path}: {str(e)}")
                continue
        
        # Combinar todos os textos extraídos
        if extracted_texts:
            item['full_text'] = "\n\n---\n\n".join(extracted_texts)
            item['length'] = len(item['full_text'])
            spider.logger.info(f"Texto completo extraído: {item['length']} caracteres")
        else:
            spider.logger.warning(f"Nenhum texto foi extraído para {item.get('title')}")
            item['full_text'] = ""
            item['length'] = 0
        
        return item