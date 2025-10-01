import scrapy
import re
import io
import fitz  # PyMuPDF
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class ProposicoesPocosDeCaldasSpider(scrapy.Spider):
    """
    Coleta as proposições da Câmara Municipal de Poços de Caldas de acordo com o dicionario de dados TIPOS_DOCUMENTO
    """
    name = 'proposicoespocosdecaldas'
    house = 'Câmara Municipal de Poços de Caldas'
    uf = 'MG'
    slug = 'proposicoespocosdecaldas'
    allowed_domains = ['pocosdecaldas.siscam.com.br']
    
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'DOWNLOAD_DELAY': 1.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 8,
        'ROBOTSTXT_OBEY': False
    }
    
    # Dicionário de tipos de documento a serem coletados para Poços de Caldas. Há outros tipos disponíveis no site que não foram coletados.
    TIPOS_DOCUMENTO = {
        137: "Projeto de Decreto Legislativo",
        139: "Projeto de Emenda à Lei Orgânica",
        135: "Projeto de Lei",
        136: "Projeto de Lei Complementar",
    }
    TEXT_LIMIT = 2500

    def start_requests(self):
        """
        Gera as requisições iniciais para a PRIMEIRA página de cada tipo de documento.
        """
        base_url = "https://pocosdecaldas.siscam.com.br/Documentos/Pesquisa"
        self.logger.info(f"Iniciando coleta para os tipos: {list(self.TIPOS_DOCUMENTO.values())}")
        
        for codigo_tipo in self.TIPOS_DOCUMENTO.keys():
            url = f"{base_url}?id=80&pagina=1&Modulo=8&Documento={codigo_tipo}"
            yield scrapy.Request(
                url, 
                callback=self.parse,
                # Passamos o 'codigo_tipo' e 'page_number' para controlar a paginação
                meta={'page_number': 1, 'codigo_tipo': codigo_tipo}
            )

    def parse(self, response):
        """
        Processa a página de listagem, extrai os itens e segue para a próxima página.
        """
        page_number = response.meta['page_number']
        codigo_tipo = response.meta['codigo_tipo']
        self.logger.info(f"Processando página {page_number} para o tipo de documento {codigo_tipo}.")
        
        proposicoes = response.css("div.data-list-item")
        self.logger.info(f"Encontradas {len(proposicoes)} matérias para processar nesta página.")
        
        # Se a página não retornar itens, consideramos o fim da paginação para este tipo.
        if not proposicoes:
            self.logger.info(f"Nenhuma proposição encontrada na página {page_number}. Fim da paginação para o tipo {codigo_tipo}.")
            return

        for proposicao_selector in proposicoes:
            item = self.extract_metadata(proposicao_selector, response)
            if item and item.get('url'):
                yield scrapy.Request(
                    url=item['url'],
                    callback=self.parse_pdf,
                    meta={'item': item}
                )
        
        # Lógica de paginação: constrói a URL da próxima página e continua a coleta.
        next_page = page_number + 1
        next_page_url = response.urljoin(f"?id=80&pagina={next_page}&Modulo=8&Documento={codigo_tipo}")
        
        self.logger.info(f"Agendando próxima página: {next_page_url}")
        yield scrapy.Request(
            next_page_url,
            callback=self.parse,
            meta={'page_number': next_page, 'codigo_tipo': codigo_tipo}
        )

    def parse_pdf(self, response):
        """
        Processa o PDF baixado, finaliza o item e o entrega para o Scrapy.
        """
        item = response.meta['item']
        self.logger.debug(f"Processando PDF para: {item['title']}")
        
        try:
            texto_limpo = self._process_and_clean_pdf_text(response.body)
            item['full_text'] = texto_limpo[:self.TEXT_LIMIT]
            item['length'] = len(item['full_text'])
        except Exception as e:
            self.logger.error(f"Falha ao processar PDF para '{item['title']}': {e}")
            item['full_text'] = "[ERRO_AO_PROCESSAR_PDF]"
            item['length'] = 0
        
        if self.validate_item(item):
            self.logger.info(f"Item VÁLIDO processado: {item['title']}")
            yield item
        else:
            self.logger.warning(f"Item descartado por falha na validação: {item.get('title')}")

    def extract_metadata(self, proposicao_selector, response):
        """
        Extrai os metadados de uma única proposição na página de listagem.
        """
        item = ProposicaoItem()
        
        title_tag = proposicao_selector.css("h4 a")
        if not title_tag:
            return None

        full_title_text = title_tag.css('::text').get('').strip()
        link_detalhes_relativo = title_tag.css('::attr(href)').get('')

        match = re.search(r'^(.*?)\s+Nº\s+(\d+)/(\d{4})', full_title_text, re.IGNORECASE)
        if match:
            item['type'] = match.group(1).strip()
            item['number'] = int(match.group(2))
            item['year'] = int(match.group(3))
            item['title'] = f"{item['type']} nº {item['number']}/{item['year']}"
        else:
            item['title'] = full_title_text
        
        def get_text_from_p_tag(strong_text):
            """
            Função auxiliar para extrair texto de uma tag <p> que contém uma <strong> específica.
            Ex: <p><strong>Assunto:</strong> Este é o assunto.</p> -> Retorna: "Este é o assunto."
            """
            p_tag_text = proposicao_selector.xpath(f".//p[strong[contains(text(), '{strong_text}')]]//text()").getall()
            if not p_tag_text:
                return None
            
            full_text = " ".join(p.strip() for p in p_tag_text).strip()
            label_to_remove = f"{strong_text.strip()} " 
            cleaned_text = full_text.replace(label_to_remove, "").strip()
            return cleaned_text

        autores_texto = get_text_from_p_tag("Autoria:")
        item['author'] = [autor.strip() for autor in autores_texto.split(',')] if autores_texto else []
        item['subject'] = get_text_from_p_tag("Assunto:")
        item['presentation_date'] = get_text_from_p_tag("Data:")

        pdf_link_tag = proposicao_selector.css('a[title="Documento Assinado"]::attr(href)').get()
        if not pdf_link_tag:
            pdf_link_tag = proposicao_selector.css('a[href*="/arquivo?Id="]::attr(href)').get()
        
        if pdf_link_tag:
            item['url'] = response.urljoin(pdf_link_tag)

        item['house'] = self.house
        item['scraped_at'] = datetime.now().isoformat()
        item['uuid'] = hashlib.md5(response.urljoin(link_detalhes_relativo).encode('utf-8')).hexdigest()
        
        return item
    
    def _process_and_clean_pdf_text(self, pdf_body):
        """
        Extrai o texto bruto do PDF e o passa para a função de limpeza.
        O underscore (_) indica que é um método auxiliar interno.
        """
        if not pdf_body:
            return ""
            
        with fitz.open(stream=io.BytesIO(pdf_body), filetype="pdf") as doc:
            texto_bruto = "".join(page.get_text("text") for page in doc)
        
        return self._limpar_texto_extraido(texto_bruto)

    def _limpar_texto_extraido(self, texto_bruto):
        """
        Aplica a lógica de limpeza com expressões regulares ao texto extraído do PDF.
        """
        if not texto_bruto:
            return "[TEXTO NÃO EXTRAÍDO]"
            
        texto_processado = texto_bruto
        match_inicio = re.search(r'PROJETO DE (LEI|DECRETO|EMENDA)', texto_processado, re.IGNORECASE)
        if match_inicio:
            texto_processado = texto_processado[match_inicio.start():]
        else:
            match_generico = re.search(r'Concede|Institui|Altera|Dispõe', texto_processado, re.IGNORECASE)
            if match_generico:
                texto_processado = texto_processado[match_generico.start():]
        
        match_justificativa = re.search(r'\n\s*JUSTIFICATIVA\s*\n', texto_processado, re.IGNORECASE)
        if match_justificativa:
            texto_processado = texto_processado[:match_justificativa.start()]
        
        match_fim = re.search(r'Plenário|Sala\s+"Ver\. José', texto_processado, re.IGNORECASE)
        if match_fim:
            texto_processado = texto_processado[:match_fim.start()]

        texto_processado = re.sub(r'-\n', '', texto_processado)
        texto_processado = re.sub(r'\s*\n\s*', ' ', texto_processado)
        texto_final = re.sub(r'\s{2,}', ' ', texto_processado).strip()

        if "JUNTA COMERCIAL" in texto_final.upper():
            return "[DOCUMENTO INVÁLIDO - CONTRATO SOCIAL]"
            
        return texto_final

    def validate_item(self, item):
        """
        Valida se o item extraído contém os campos essenciais para ser salvo.
        """
        if not all([item.get('title'), item.get('url'), item.get('uuid')]):
            return False
        
        if not item.get('full_text') or len(item['full_text']) < 50 or "[ERRO" in item['full_text'] or "[DOCUMENTO INVÁLIDO" in item['full_text'] or "[TEXTO NÃO EXTRAÍDO" in item['full_text']:
            return False

        return True