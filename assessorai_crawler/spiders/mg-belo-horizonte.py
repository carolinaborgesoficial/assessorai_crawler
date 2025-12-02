# assessorai_crawler/spiders/mg-belo-horizonte.py

import scrapy
import re
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class MgBeloHorizonteSpider(scrapy.Spider):
    """Spider para Câmara Municipal de Belo Horizonte - MG"""

    name = 'mg-belo-horizonte'
    uf = 'MG'
    slug = 'mg-belo-horizonte'
    house = 'Câmara Municipal de Belo Horizonte'
    domain = 'cmbh.mg.gov.br'
    base_url = 'https://www.cmbh.mg.gov.br/sites/all/modules/proposicoes/pesquisar.php'

    # Tipos de documento
    TIPOS_DOCUMENTO = {
        '2c907f7801d41f2001024943e5ec004a': 'Projeto de Lei',
    }

    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'DOWNLOAD_DELAY': 1,
    }

    def __init__(self, ano=None, tipo=None, max_pages=None, reset=None, test_mode=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ano = ano
        self.tipo = tipo or '2c907f7801d41f2001024943e5ec004a'  # Default to Projeto de Lei
        self.max_pages = int(max_pages) if max_pages is not None else None
        self.reset = reset
        self.test_mode = test_mode
        if self.test_mode:
            self.custom_settings.update({
                'CLOSESPIDER_ITEMCOUNT': 5,
                'LOG_LEVEL': 'DEBUG',
            })

        self.allowed_domains = [self.domain, 'cmbhsilint.cmbh.mg.gov.br']

    def start_requests(self):
        """Inicia com POST para a primeira página."""
        formdata = {
            'tipo': self.tipo,
            'numero': '[número]',
            'ano': self.ano or '[ano]',
            'buscarPorProtocolo': 'false',
            'autor': '[autor]',
            'assunto': '[assunto]',
            'assunto2': '[assunto2]',
            'fase': '[Selecione]',
            'tramitando': 'Tanto faz',
            'buscarProposicoesOpinar': 'false',
            'paginaRequerida': '1',
            'metodo': '',
            'nomeProposicao': '',
            'urlProposicao': '',
            'idProposicao': '',
            'buscarEmendas_proposicoes': '',
            'idTipoEmenda': '',
            'idTipoSubemenda': '',
            'idTipoEmendaDeRedacao': '',
            'drupalUsername': 'deslogado-anonimo',
            'drupalEmail': '',
            'buscaViaUrl': '',
            'stormCodex': '410d41a2a8d879f46dc8675cb1ea8030',
            'mobile': '0'
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.cmbh.mg.gov.br/atividade-legislativa/pesquisar-proposicoes',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.cmbh.mg.gov.br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        yield scrapy.FormRequest(
            url=self.base_url,
            formdata=formdata,
            headers=headers,
            callback=self.parse,
            meta={'page_number': 1, 'formdata': formdata.copy(), 'headers': headers}
        )


    def parse(self, response):
        """Processa a página de resultados."""
        self.logger.info(f"Processando página: {response.url}")

        # Extrair itens da lista
        linhas = response.css('ul.lista-pesquisas li')
        self.logger.info(f"Encontrados {len(linhas)} itens nesta página.")

        for linha in linhas:
            item = self.extract_metadata_from_li(linha, response)
            if item:
                yield item

        # Verificar limite de páginas
        current_page = response.meta.get('page_number', 1)
        if self.max_pages and current_page >= self.max_pages:
            self.logger.info(f"Limite de páginas atingido ({self.max_pages})")
            return

        # Paginação
        # Verificar se há próxima página
        # O HTML tem <ul class='pagination'> com <li><a class='mudarPagina' href='#inicioResultados'>2</a></li>
        # Mas href='#inicioResultados', so need to find the next page number
        # Also, from the response, it has paginaRequerida in formdata
        # So, to get next page, increment paginaRequerida

        # But to know if there is next, check if current items < total or something
        # From the HTML: <span class='resumoResultados'>Estão sendo exibidos os itens de 1 a 7 de um total de 9233 itens</span>
        resumo = response.css('span.resumoResultados::text').get()
        if resumo:
            match = re.search(r'de um total de (\d+) itens', resumo)
            if match:
                total = int(match.group(1))
                per_page = 7  # from 1 a 7
                total_pages = (total + per_page - 1) // per_page
                if current_page < total_pages:
                    next_page = current_page + 1
                    self.logger.info(f"Próxima página: {next_page}")
                    # Repeat the formdata with paginaRequerida = str(next_page)
                    formdata = response.meta.get('formdata', {})
                    formdata['paginaRequerida'] = str(next_page)
                    headers = response.meta.get('headers', {})
                    yield scrapy.FormRequest(
                        url=self.base_url,
                        formdata=formdata,
                        headers=headers,
                        callback=self.parse,
                        meta={'page_number': next_page, 'formdata': formdata, 'headers': headers}
                    )

    def extract_metadata_from_li(self, li, response):
        """Extrai metadados do item da lista."""
        item = ProposicaoItem()

        # Título
        title_span = li.css('span.detalhar.vinculavel')
        if not title_span:
            return None

        texto_titulo_completo = title_span.css('::text').get('').strip()
        link_detalhes = title_span.css('::attr(data-caminho)').get('')

        # Parse title
        match_titulo = re.search(r'(.+?)\s*-\s*(\d+)/(\d{4})', texto_titulo_completo)
        if match_titulo:
            item['type'] = match_titulo.group(1).strip()
            item['number'] = str(match_titulo.group(2))
            item['year'] = str(match_titulo.group(3))
            item['title'] = f"{item['type']} nº {item['number']}/{item['year']}"
        else:
            item['title'] = texto_titulo_completo
            item['number'] = None
            item['year'] = None
            item['type'] = None

        # Extrair de <p>
        ps = li.css('p')
        status_list = []

        for p in ps:
            text = p.xpath('string(.)').get().strip()
            if 'Autoria:' in text:
                item['author'] = [a.strip() for a in text.replace('Autoria:', '').strip().split(';') if a.strip()]
            elif 'Ementa:' in text:
                item['emenda'] = text.replace('Ementa:', '').strip()
            elif 'Assunto:' in text:
                item['subject'] = [s.strip() for s in text.replace('Assunto:', '').strip().split(',') if s.strip()]
            elif 'Data de apresentação:' in text:
                item['presentation_date'] = text.replace('Data de apresentação:', '').strip()
            elif text.startswith('Situação:'):
                status_list.append({"descricao": text, "data": None})
            elif text.startswith('Fase Atual:'):
                status_list.append({"descricao": text, "data": None})

        if status_list:
            item['status'] = status_list

        # PDF URL
        pdf_links = li.css('a[title*="Baixar texto inicial"]::attr(href)').get()
        if pdf_links:
            item['url'] = response.urljoin(pdf_links)
            item['file_urls'] = [item['url']]

        item['house'] = self.house
        item['scraped_at'] = datetime.now().isoformat()
        item['uuid'] = hashlib.md5(link_detalhes.encode('utf-8')).hexdigest()
        item['project_url'] = link_detalhes

        # md_files
        normalized_type = item['type'].lower().replace(' ', '-').replace('à', 'a') if item['type'] else 'unknown'
        item['md_files'] = f"{self.uf}/{self.slug}/{normalized_type}-{item['number']}-{item['year']}.md"

        return item