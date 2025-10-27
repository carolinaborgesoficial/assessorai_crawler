# Arquivo: assessorai_crawler/pipelines.py

import json
import os
import re
from unidecode import unidecode
from scrapy import Request
from scrapy.exceptions import DropItem
from scrapy.pipelines.files import FilesPipeline
from datetime import datetime

class PipelinePadronizacao:
    """
    Recebe o item bruto, padroniza os dados e gera os caminhos dos arquivos.
    """
    def _slugify(self, text):
        """Converte um texto como "São Paulo" para "sao-paulo"."""
        if not text: return ""
        text = unidecode(str(text))
        text = text.lower()
        text = re.sub(r'[\s\W_]+', '-', text)
        return text.strip('-')

    def process_item(self, item, spider):
        autores_final = []
        for autor_raw in item.get('autores_bruto', []):
            nome, partido = self._extrair_nome_partido(autor_raw)
            autores_final.append({"nome": nome, "partido": partido})

        data_formatada = self._formatar_data(item.get('data_documento_bruto'))
        
        # --- LÓGICA CORRIGIDA DE CRIAÇÃO DE CAMINHOS ---
        uf_slug = self._slugify(spider.uf)
        municipio_slug = self._slugify(spider.municipio)
        nome_arquivo = self._slugify(item.get('nome_arquivo_padronizado', 'arquivo-sem-nome'))
        
        caminho_base = f"{uf_slug}/{municipio_slug}/{spider.slug}/{nome_arquivo}"
        caminho_pdf = f"{caminho_base}.pdf"
        caminho_md = f"{caminho_base}.md"

        item_padronizado = {
            "localidade": {"esfera": spider.esfera, "municipio": spider.municipio, "estado": spider.uf},
            "casa_legislativa": spider.casa_legislativa,
            "tipo_documento": item.get('tipo_bruto'),
            "numero_documento": str(item.get('numero_bruto')),
            "data_documento": data_formatada,
            "autores": autores_final,
            "ementa": item.get('ementa_bruto'),
            "assuntos": item.get('assuntos_bruto', []),
            "status_tramitacao": [
                {
                    "descricao": s.get("descricao"),
                    "data": self._formatar_data(s.get("data"))
                }
                for s in item.get('status_bruto', [])
            ],
            "url_documento_original": item.get('url_bruto'),
            "caminho_arquivo_original": caminho_pdf,
            "caminho_arquivo_texto": caminho_md,
            "data_raspagem": item.get('data_raspagem_bruto')
        }
        
        return {'item_bruto': item, 'item_padronizado': item_padronizado}

    def _extrair_nome_partido(self, texto_autor):
        match = re.search(r'\((.*?)\)', texto_autor)
        if match:
            partido = match.group(1).strip().upper()
            nome = re.sub(r'^\s*Ver\.\s*', '', texto_autor).replace(f"({match.group(1)})", "").strip()
            return nome, partido
        return texto_autor.strip(), None

    def _formatar_data(self, data_texto):
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            pass
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y %H:%M').strftime('%Y-%m-%d')
        except ValueError:
            pass
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
        except ValueError:
            pass
        match = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', data_texto, re.IGNORECASE)
        if match:
            dia, mes_nome, ano = match.groups()
            meses = {
                'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
                'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
                'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
            }
            mes = meses.get(mes_nome.lower())
            if mes:
                return f"{ano}-{mes}-{int(dia):02d}"
        return data_texto


class ProposicaoFilesPipeline(FilesPipeline):
    def get_media_requests(self, item, info):
        item_bruto = item['item_bruto']
        urls = item_bruto.get('file_urls', [])
        for url in urls:
            yield Request(url, meta={'item': item})
    
    def file_path(self, request, response=None, info=None, *, item=None):
        item_padronizado = item['item_padronizado']
        return item_padronizado.get('caminho_arquivo_original')

class JsonWriterSinglePipeline:
    """Salva cada item padronizado como uma linha em um arquivo .jl."""
    def open_spider(self, spider):
        output_dir = f'output'
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f'{spider.slug}_proposicoes.jl')
        self.file = open(file_path, 'w', encoding='utf-8')

    def process_item(self, item, spider):
        item_padronizado = item['item_padronizado']
        # --- CORREÇÃO AQUI: Escreve uma única linha, sem indentação ---
        line = json.dumps(dict(item_padronizado), ensure_ascii=False) + "\n"
        self.file.write(line)
        return item

    def close_spider(self, spider):
        self.file.close()

class ValidationPipeline:
    """Valida se o spider coletou os dados brutos mínimos necessários."""
    def process_item(self, item, spider):
        item_bruto = item['item_bruto']
        if hasattr(item_bruto, 'missing_fields'):
            missing = item_bruto.missing_fields()
            if missing:
                raise DropItem(f"Item bruto descartado, campos faltando: {missing}")
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

