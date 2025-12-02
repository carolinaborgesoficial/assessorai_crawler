# assessorai_crawler/spiders/base_sapl.py

import scrapy
import re
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class BaseSaplSpider(scrapy.Spider):
    """Classe base para spiders do sistema SAPL (Sistema de Apoio ao Processo Legislativo)."""

    # Atributos a serem definidos nas subclasses
    uf = None
    slug = None
    house = None
    domain = None
    base_url = None  # Ex.: "https://sapl.fortaleza.ce.leg.br/materia/pesquisar-materia"

    # Tipos de documento suportados (pode ser sobrescrito)
    TIPOS_DOCUMENTO = {
        1: "Projeto de Lei Ordinária",
        5: "Projeto de Lei Complementar",
        6: "Projeto de Decreto Legislativo",
        9: "Projeto de Emenda à Lei Orgânica",
    }

    # Configurações padrão
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'DOWNLOAD_DELAY': 1,
    }


    def __init__(self, ano=None, tipo=None, max_pages=None, reset=None, test_mode=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ano = ano
        self.tipo = tipo  # não usa mais default_tipo
        self.max_pages = int(max_pages) if max_pages is not None else None
        self.reset = reset
        self.test_mode = test_mode
        if self.test_mode:
            self.custom_settings.update({
                'CLOSESPIDER_ITEMCOUNT': 5,
                'LOG_LEVEL': 'DEBUG',
            })

        if not self.domain or not self.base_url:
            raise ValueError("Subclass must define 'domain' and 'base_url'")

        self.allowed_domains = [self.domain]

    def start_requests(self):
        """Gera as requisições iniciais para a primeira página de cada tipo."""
        tipos = [self.tipo] if self.tipo else list(self.TIPOS_DOCUMENTO.keys())
        self.logger.info(f"Iniciando coleta para os tipos: {[self.TIPOS_DOCUMENTO.get(t, t) for t in tipos]}")

        for codigo in tipos:
            params = f"page=1&tipo={codigo}"
            if self.ano:
                params += f"&ano={self.ano}"
            url = f"{self.base_url}?{params}"
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """Processa a página de listagem, extrai os itens e segue para a próxima página."""
        self.logger.info(f"Processando página de listagem: {response.url}")

        linhas = response.css('table.table-striped tr')
        self.logger.info(f"Encontradas {len(linhas)} matérias para processar nesta página.")

        for linha in linhas:
            item = self.extract_metadata_from_row(linha, response)
            if item:
                if item.get('file_urls'):
                    # PDF encontrado na listagem, yield diretamente
                    yield item
                else:
                    # PDF não encontrado, buscar na página de detalhes
                    if item.get('url'):
                        yield scrapy.Request(
                            url=item['url'],
                            callback=self.parse_process_page,
                            meta={'item': item}
                        )

        # Verificar limite de páginas
        current_page = response.meta.get('page_number', 1)
        if self.max_pages and current_page >= self.max_pages:
            self.logger.info(f"Limite de páginas atingido ({self.max_pages}) para {response.url}")
            return

        next_page_link = response.css('a.page-link:contains("Próxima")::attr(href)').get()
        if next_page_link:
            self.logger.info(f"Encontrada próxima página: {next_page_link}")
            next_page_url = response.urljoin(next_page_link)
            yield scrapy.Request(next_page_url, callback=self.parse, meta={'page_number': current_page + 1})
        else:
            self.logger.info(f"Fim da paginação para a URL: {response.url}")

    def extract_metadata_from_row(self, linha_selector, response):
        """Extrai metadados da linha da tabela."""
        item = ProposicaoItem()
        link_titulo_tag = linha_selector.css('a')
        if not link_titulo_tag:
            return None

        texto_titulo_completo = link_titulo_tag.css('::text').get('').strip()
        link_detalhes_relativo = link_titulo_tag.css('::attr(href)').get('')

        # Regex para extrair tipo, número, ano e título
        match_titulo = re.search(r'(\w+)\s+(\d+)/(\d{4})\s+-\s+(.*)', texto_titulo_completo)
        if match_titulo:
            item['number'] = str(match_titulo.group(2))  # Manter como string para consistência
            item['year'] = str(match_titulo.group(3))
            item['type'] = match_titulo.group(4).strip()
            item['title'] = f"{item['type']} nº {item['number']}/{item['year']}"
        else:
            item['title'] = texto_titulo_completo
            item['number'] = None
            item['year'] = None
            item['type'] = None

        item['subject'] = linha_selector.css('div.dont-break-out::text').get('').strip()

        #padronização da data
        raw_date = linha_selector.xpath("string(.//strong[contains(text(), 'Apresentação:')]/following-sibling::text()[1])").get('').strip()
        item['presentation_date'] = self._formatar_data(raw_date)
       
        item['author'] = [linha_selector.xpath("string(.//strong[contains(text(), 'Autor:')]/following-sibling::text()[1])").get('').strip()]

        pdf_relative_url = linha_selector.css('a:contains("Texto Original")::attr(href)').get()
        if pdf_relative_url:
            item['url'] = response.urljoin(pdf_relative_url)
            item['file_urls'] = [item['url']]

        item['house'] = self.house
        item['scraped_at'] = datetime.now().isoformat()
        item['uuid'] = hashlib.md5(response.urljoin(link_detalhes_relativo).encode('utf-8')).hexdigest()
        item['project_url'] = response.urljoin(link_detalhes_relativo)  # URL da página de detalhes do projeto

        # Caminho para .md
        normalized_type = item['type'].lower().replace(' ', '-').replace('à', 'a') if item['type'] else 'unknown'
        item['md_files'] = f"{self.uf}/{self.slug}/{normalized_type}-{item['number']}-{item['year']}.md"

        #status
        status_list = []

        localizacao = linha_selector.xpath("string(.//strong[contains(text(), 'Localização Atual:')]/following-sibling::text()[1])").get()
        if localizacao:
            status_list.append({"descricao": f"Localização Atual: {localizacao.strip()}", "data": None})

        status = linha_selector.xpath("string(.//strong[contains(text(), 'Status:')]/following-sibling::text()[1])").get()
        if status:
            status_list.append({"descricao": f"Status: {status.strip()}", "data": None})

        data_tramitacao = linha_selector.xpath("string(.//strong[contains(text(), 'Data da última Tramitação:')]/following-sibling::text()[1])").get()
        if data_tramitacao:
            status_list.append({"descricao": "Data da última Tramitação", "data": self._formatar_data(data_tramitacao.strip())})

        ultima_acao = linha_selector.xpath("string(.//strong[contains(text(), 'Última Ação:')]/following-sibling::text()[1])").get()
        if ultima_acao:
            status_list.append({"descricao": f"Última Ação: {ultima_acao.strip()}", "data": None})

        if status_list:
            item['status'] = status_list

        return item

    def _formatar_data(self, data_texto):
        if not data_texto:
            return None
        # tenta formato "8 de março de 2025"
        m = re.match(r'(\d{1,2}) de (\w+) de (\d{4})', data_texto.strip(), re.IGNORECASE)
        MESES = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
        }
        if m:
            dia, mes_nome, ano = m.groups()
            mes = MESES.get(mes_nome.lower())
            if mes:
                return f"{ano}-{mes:02d}-{int(dia):02d}"
        # tenta dd/mm/yyyy
        try:
            return datetime.strptime(data_texto.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
        # tenta yyyy-mm-dd
        try:
            return datetime.strptime(data_texto.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
