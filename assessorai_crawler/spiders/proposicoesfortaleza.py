import scrapy
import re
import io
import fitz  # PyMuPDF
from datetime import datetime
import hashlib
from ..items import ProposicaoItem
import html2text

class ProposicoesFortalezaSpider(scrapy.Spider):
    """
    Coleta TODAS as proposições da Câmara Municipal de Fortaleza, implementando
    paginação e seguindo a arquitetura do projeto AssessorAI.
    """
    name = 'proposicoesfortaleza'
    house = 'Câmara Municipal de Fortaleza'
    uf = 'CE'
    slug = 'proposicoesfortaleza'
    allowed_domains = ['sapl.fortaleza.ce.leg.br']
    
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'DOWNLOAD_DELAY': 1 
    }
    
    TIPOS_DOCUMENTO = {
        #8: "Indicação",
        #10: "Mensagem",
        #12: "Parecer Prévio do Tribunal de Contas",
        6: "Projeto de Decreto Legislativo",
        9: "Projeto de Emenda à Lei Orgânica",
        #13: "Projeto de Iniciativa Popular",
        5: "Projeto de Lei Complementar",
        1: "Projeto de Lei Ordinária",
        #2: "Projeto de Resolução",
        #14: "Protocolo da Casa",
        #4: "Recurso",
        #3: "Requerimento",
        #11: "Veto"
    }
    TEXT_LIMIT = 2500

    def start_requests(self):
        """Gera as requisições iniciais para a PRIMEIRA página de cada tipo."""
        base_url = "https://sapl.fortaleza.ce.leg.br/materia/pesquisar-materia"
        self.logger.info(f"Iniciando coleta para os tipos: {list(self.TIPOS_DOCUMENTO.values())}")
        for codigo in self.TIPOS_DOCUMENTO.keys():
            url = f"{base_url}?page=1&tipo={codigo}"
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """
        Processa a página de listagem, extrai os itens e segue para a próxima página.
        """
        self.logger.info(f"Processando página de listagem: {response.url}")
        
        linhas = response.css('table.table-striped tr')
        self.logger.info(f"Encontradas {len(linhas)} matérias para processar nesta página.")
        
        for linha in linhas:
            item = self.extract_metadata_from_row(linha, response)
            if item and item.get('url'):
                yield scrapy.Request(
                    url=item['url'],
                    callback=self.parse_pdf,
                    meta={'item': item}
                )
        
        next_page_link = response.css('a.page-link:contains("Próxima")::attr(href)').get()
        if next_page_link:
            self.logger.info(f"Encontrada próxima página: {next_page_link}")
            yield response.follow(next_page_link, callback=self.parse)
        else:
            self.logger.info(f"Fim da paginação para a URL: {response.url}")

    def parse_pdf(self, response):
        """Processa o PDF baixado, finaliza o item e o entrega para o Scrapy."""
        item = response.meta['item']
        self.logger.debug(f"Processando PDF para: {item['title']}")
        
        try:
            texto_html = self._extract_full_text(response.body)
            texto_markdown = self._convert_to_markdown(texto_html)
            
            item['full_text'] = texto_markdown[:self.TEXT_LIMIT]
            item['length'] = len(item['full_text'])
        except Exception as e:
            self.logger.error(f"Falha ao processar PDF para '{item['title']}': {e}")
            item['full_text'] = "[ERRO_AO_PROCESSAR_PDF]"
            item['length'] = len(item['full_text'])
        
        if self.validate_item(item):
            self.logger.info(f"Item VÁLIDO processado: {item['title']}")
            yield item
        else:
            self.logger.warning(f"Item descartado por falha na validação: {item.get('title')}")

    def extract_metadata_from_row(self, linha_selector, response):
        item = ProposicaoItem()
        link_titulo_tag = linha_selector.css('a')
        if not link_titulo_tag: return None
        texto_titulo_completo = link_titulo_tag.css('::text').get('').strip()
        link_detalhes_relativo = link_titulo_tag.css('::attr(href)').get('')
        match_titulo = re.search(r'(\w+)\s+(\d+)/(\d{4})\s+-\s+(.*)', texto_titulo_completo)
        if match_titulo:
            item['number'] = int(match_titulo.group(2))
            item['year'] = int(match_titulo.group(3))
            item['type'] = match_titulo.group(4).strip()
            item['title'] = f"{item['type']} nº {item['number']}/{item['year']}"
        else:
            item['title'] = texto_titulo_completo
        item['subject'] = linha_selector.css('div.dont-break-out::text').get('').strip()
        item['presentation_date'] = linha_selector.xpath("string(.//strong[contains(text(), 'Apresentação:')]/following-sibling::text()[1])").get('').strip()
        item['author'] = [linha_selector.xpath("string(.//strong[contains(text(), 'Autor:')]/following-sibling::text()[1])").get('').strip()]
        pdf_relative_url = linha_selector.css('a:contains("Texto Original")::attr(href)').get()
        if pdf_relative_url:
            item['url'] = response.urljoin(pdf_relative_url)
        item['house'] = self.house
        item['scraped_at'] = datetime.now().isoformat()
        item['uuid'] = hashlib.md5(response.urljoin(link_detalhes_relativo).encode('utf-8')).hexdigest()
        return item

    def _extract_full_text(self, pdf_body):
        """
        Extrai o conteúdo HTML bruto do corpo de um PDF.
        O underscore (_) indica que é um método auxiliar interno.
        """
        if not pdf_body:
            return ""
        with fitz.open(stream=io.BytesIO(pdf_body), filetype="pdf") as doc:
            return "".join(page.get_text("html") for page in doc)

    def _convert_to_markdown(self, html_bruto):
        """
        Limpa o HTML bruto específico de Fortaleza e o converte para Markdown,
        seguindo o padrão da documentação.
        """
        if not html_bruto:
            return "[PDF SEM CONTEÚDO EXTRAÍVEL]"
        
        # 1. Conversão para Markdown 
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0
        markdown = h.handle(html_bruto)
        
        # 2. Limpeza específica de Fortaleza
        linhas_para_remover = [r'^\s*CÂMARA MUNICIPAL DE FORTALEZA.*$', r'^\s*GABINETE VEREADOR.*$']
        for pattern in linhas_para_remover:
            markdown = re.sub(pattern, '', markdown, flags=re.MULTILINE | re.IGNORECASE)
        
        # 3. Limpeza final no Markdown
        markdown = re.sub(r'\n\s*\n', '\n\n', markdown)
        return markdown.strip()

    def validate_item(self, item):
        if not item.get('title'): return False
        if not item.get('full_text') or len(item['full_text']) < 50 or "[ERRO" in item['full_text']: return False
        return True