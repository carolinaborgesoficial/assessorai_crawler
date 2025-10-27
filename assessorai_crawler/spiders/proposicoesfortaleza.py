import scrapy
import hashlib
import re
from datetime import datetime
from ..items import ProposicaoItem

class ProposicoesFortalezaSpider(scrapy.Spider):
    """
    Spider para coleta de proposições legislativas da Câmara Municipal de Fortaleza.
    Extrai dados da lista principal e aponta o link do PDF, respeitando filtros de data e limite.
    """

    # --- 1. CONFIGURAÇÃO PADRÃO DO SCRAPY ---
    name = 'proposicoesfortaleza'
    allowed_domains = ['sapl.fortaleza.ce.leg.br']
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'DOWNLOAD_DELAY': 2,
        'AUTOTHROTTLE_ENABLED': True
    }

    # --- 2. METADADOS DA CASA LEGISLATIVA ---
    slug = 'proposicoesfortaleza'
    casa_legislativa = 'Câmara Municipal de Fortaleza'
    uf = 'CE'
    municipio = 'Fortaleza'
    esfera = 'MUNICIPAL'

    # --- 3. TIPOS DE DOCUMENTO A COLETAR ---
    TIPOS_DOCUMENTO = {
        #6: "Projeto de Decreto Legislativo",
        #9: "Projeto de Emenda à Lei Orgânica",
        #5: "Projeto de Lei Complementar",
        1: "Projeto de Lei Ordinária",
    }

    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_inicio = self._validar_data(data_inicio)
        self.data_fim = self._validar_data(data_fim)
        try:
            self.limite_total_itens = int(limite) if limite else None
        except ValueError:
            raise ValueError("O parâmetro 'limite' deve ser um número inteiro.")
        self.itens_processados = 0

    def start_requests(self):
        base_url = "https://sapl.fortaleza.ce.leg.br/materia/pesquisar-materia"
        for tipo in self.TIPOS_DOCUMENTO.keys():
            url = f"{base_url}?page=1&tipo={tipo}"
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        linhas = response.css('table.table-striped tr')
        for linha in linhas:
            if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
                return

            data_str = linha.xpath("string(.//strong[contains(text(), 'Apresentação:')]/following-sibling::text()[1])").get('').strip()
            data_obj = self._extrair_data_obj(data_str)

            # Filtro manual por data
            if self.data_inicio and data_obj and data_obj < datetime.strptime(self.data_inicio, '%Y-%m-%d'):
                continue
            if self.data_fim and data_obj and data_obj > datetime.strptime(self.data_fim, '%Y-%m-%d'):
                continue


            item = self._create_item_from_lista(linha, response, data_str)
            if item:
                self.itens_processados += 1
                yield item

        if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
            return

        next_page_link = response.css('a.page-link:contains("Próxima")::attr(href)').get()
        if next_page_link:
            yield response.follow(next_page_link, callback=self.parse)


    def _create_item_from_lista(self, linha, response, data_str):
        item = ProposicaoItem()

        link_tag = linha.css('strong a')
        if not link_tag:
            return None

        texto_titulo = link_tag.css('::text').get('').strip()
        link_detalhes = link_tag.css('::attr(href)').get('')
        match = re.search(r'(\w+)\s+(\d+)/(\d{4})\s+-\s+(.*)', texto_titulo)
        if match:
            item['numero_bruto'] = match.group(2)
            item['ano_bruto'] = match.group(3)
            item['tipo_bruto'] = match.group(4).strip()
        item['titulo_bruto'] = texto_titulo
        item['ementa_bruto'] = linha.css('div.dont-break-out::text').get('').strip()
        item['data_documento_bruto'] = data_str

        autores = linha.xpath("string(.//strong[contains(text(), 'Autor:')]/following-sibling::text()[1])").get('').strip()
        item['autores_bruto'] = [autores] if autores else []

        status_descricao = linha.xpath("string(.//strong[contains(text(), 'Status:')]/following-sibling::text()[1])").get('').strip()
        status_data = linha.xpath("string(.//strong[contains(text(), 'Data da última Tramitação:')]/following-sibling::text()[1])").get('').strip()
        item['status_bruto'] = [{"descricao": status_descricao, "data": status_data}] if status_descricao else []

        item['assuntos_bruto'] = []

        pdf_url = linha.css('a:contains("Texto Original")::attr(href)').get()
        if pdf_url:
            item['url_bruto'] = response.urljoin(pdf_url)
            item['file_urls'] = [item['url_bruto']]
            item['nome_arquivo_padronizado'] = f"{item.get('tipo_bruto', 'doc').replace(' ', '-')}_{item.get('numero_bruto', 's_n')}_{item.get('ano_bruto', 's_a')}"

        item['casa_legislativa_bruto'] = self.casa_legislativa
        item['data_raspagem_bruto'] = datetime.now().isoformat()
        item['uf_bruto'] = self.uf
        item['municipio_bruto'] = self.municipio
        item['slug_bruto'] = self.slug
        item['meta_bruto'] = {'source_url': response.urljoin(link_detalhes)}
        item['uuid'] = hashlib.md5(response.urljoin(link_detalhes).encode('utf-8')).hexdigest()

        return item

    def _validar_data(self, data_texto):
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Formato de data inválido: '{data_texto}'. Use o formato YYYY-MM-DD.")

    def _extrair_data_obj(self, data_str):
        if not data_str:
            return None
        try:
            meses = {
                'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
                'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
                'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
            }
            dia, mes_nome, ano = data_str.split(' de ')
            return datetime.strptime(f"{dia}/{meses[mes_nome.lower()]}/{ano}", '%d/%m/%Y')
        except (ValueError, KeyError):
            return None
