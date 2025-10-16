import scrapy
import hashlib
from datetime import datetime
from assessorai_crawler.items import ProposicaoItem
from urllib.parse import urlencode

class ProposicoesPCDSpider(scrapy.Spider):
    name = "proposicoespcd"
    house = "Câmara Municipal de Poços de Caldas"
    allowed_domains = ["pocosdecaldas.siscam.com.br"]
    slug = "proposicoespcd"
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DEFAULT_REQUEST_HEADERS': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
    }

    def __init__(self, ano=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if ano is None:
            raise ValueError("É necessário informar o parâmetro 'ano'. Ex: scrapy crawl proposicoespcd -a ano=2025")
        self.ano = ano

    def start_requests(self):
        base_url = "https://pocosdecaldas.siscam.com.br/Documentos/Pesquisa/80"
        params = {
            "Pesquisa": "Simples",
            "Pagina": 1,
            "Documento": 135,
            "Modulo": 8,
            "AnoInicial": self.ano
        }
        url = f"{base_url}?{urlencode(params)}"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """Parse da página de listagem"""
        for row in response.css("table.table tbody tr"):
            item = ProposicaoItem()
            
            # Dados básicos
            item["house"] = self.house
            item["title"] = row.css("td:nth-child(2)::text").get(default="").strip()
            item["type"] = row.css("td:nth-child(1)::text").get(default="").strip()
            item["number"] = row.css("td:nth-child(3)::text").get(default="").strip()
            item["year"] = self.ano
            item["presentation_date"] = row.css("td:nth-child(4)::text").get(default="").strip()
            item["author"] = [row.css("td:nth-child(5)::text").get(default="").strip()]
            item["subject"] = row.css("td:nth-child(6)::text").get(default="").strip()
            
            # URL da proposição
            detail_link = row.css("td a[href*='Documentos/Detalhes']::attr(href)").get()
            if detail_link:
                item["url"] = response.urljoin(detail_link)
            else:
                item["url"] = ""
            
            # Metadados
            item["uuid"] = hashlib.md5(item["title"].encode('utf-8')).hexdigest()
            item["scraped_at"] = datetime.now().isoformat()
            item["meta"] = {}
            
            # Campos a serem preenchidos pelos pipelines
            item["full_text"] = ""
            item["length"] = 0
            item["file_urls"] = []
            item["files"] = []
            
            # Seguir para página de detalhes para coletar arquivos
            if item["url"]:
                yield response.follow(item["url"], callback=self.parse_detail, meta={"item": item})
            else:
                yield item

        # Paginação
        next_page = response.css("ul.pagination li a[rel='next']:not(.disabled)::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_detail(self, response):
        """Parse da página de detalhes para extrair URLs de arquivos"""
        item = response.meta["item"]
        
        # Extrair todas as URLs de download de arquivos
        file_urls = []
        for link in response.css("a[href*='/Documentos/Download']"):
            file_url = response.urljoin(link.attrib["href"])
            file_urls.append(file_url)
        
        item["file_urls"] = file_urls
        
        # O FilesPipeline vai baixar os arquivos automaticamente
        # O GeminiPDFExtractionPipeline vai extrair o texto
        yield item
