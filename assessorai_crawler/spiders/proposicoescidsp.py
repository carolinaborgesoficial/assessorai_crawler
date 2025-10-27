import scrapy
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from ..items import ProposicaoItem

class ProposicoescidspSpider(scrapy.Spider):
    """
    Spider para coleta de proposições legislativas da Câmara Municipal de São Paulo.
    Extrai dados da lista principal e detalhes de cada projeto.
    """

    # --- 1. CONFIGURAÇÃO PADRÃO DO SCRAPY ---
    name = 'proposicoescidsp'
    allowed_domains = [
        'splegisconsulta.saopaulo.sp.leg.br',
        'splegispdarmazenamento.blob.core.windows.net'
    ]

    # --- 2. METADADOS DA CASA LEGISLATIVA ---
    slug = 'proposicoescidsp'
    casa_legislativa = 'Câmara Municipal de São Paulo'
    uf = 'SP'
    esfera = 'MUNICIPAL'
    municipio = 'São Paulo'

    # --- 3. URLs E PARÂMETROS DE COLETA ---
    ajax_url = 'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/PageDataProjeto'
    detalhes_url_template = (
        'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/DetailsDetalhado'
        '?COD_MTRA_LEGL=1&COD_PCSS_CMSP={codigo}&ANO_PCSS_CMSP={ano}'
    )
    items_por_page_ajax = 100

    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Validação de datas
        self.data_inicio = self._validar_data(data_inicio)
        self.data_fim = self._validar_data(data_fim)

        # Validação de limite
        try:
            self.limite_total_itens = int(limite) if limite else None
        except ValueError:
            raise ValueError("O parâmetro 'limite' deve ser um número inteiro.")

        self.itens_processados = 0

        log_msg = f"🕷️ Iniciando coleta para {self.casa_legislativa}"
        if self.data_inicio or self.data_fim:
            log_msg += f" | Período: {self.data_inicio or '...'} a {self.data_fim or '...'}"
        if self.limite_total_itens:
            log_msg += f" | Limite: {self.limite_total_itens} itens"
        self.logger.info(log_msg)

    def start_requests(self):
        """Inicia a coleta via requisição AJAX."""
        params = self._build_params(start=0)
        headers = {'Referer': 'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/IndexProjeto'}
        yield scrapy.Request(
            url=f"{self.ajax_url}?{urlencode(params)}",
            headers=headers,
            callback=self.parse,
            meta={'params_template': params.copy()}
        )

    def parse(self, response, **kwargs):
        """Processa a lista de proposições e dispara requisições para detalhes."""
        data_json = json.loads(response.text)
        proposicoes_ajax = data_json.get('data', [])

        for ajax_data in proposicoes_ajax:
            if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
                return

            item = self._create_item_from_ajax(ajax_data, response)
            if not item:
                continue

            self.itens_processados += 1
            detalhes_url = self.detalhes_url_template.format(
                codigo=item['numero_bruto'],
                ano=item['ano_bruto']
            )
            yield scrapy.Request(
                url=detalhes_url,
                callback=self.parse_detalhes,
                meta={'item': item}
            )

        # Paginação
        current_start = int(response.meta['params_template'].get('start', 0))
        total_records = data_json.get('recordsFiltered', 0)
        next_start = current_start + self.items_por_page_ajax

        if next_start < total_records and (
            not self.limite_total_itens or self.itens_processados < self.limite_total_itens
        ):
            next_params = self._build_params(
                start=next_start,
                draw=int(response.meta['params_template'].get('draw', 1)) + 1
            )
            yield scrapy.Request(
                url=f"{self.ajax_url}?{urlencode(next_params)}",
                headers=response.request.headers,
                callback=self.parse,
                meta={'params_template': next_params}
            )

    def _create_item_from_ajax(self, ajax_data, response):
        """Cria item bruto a partir da resposta AJAX."""
        codigo_processo = ajax_data.get('codigo')
        if not codigo_processo:
            return None

        item = ProposicaoItem()
        item['uuid'] = hashlib.md5(str(codigo_processo).encode()).hexdigest()
        item['casa_legislativa_bruto'] = self.casa_legislativa
        item['titulo_bruto'] = ajax_data.get('texto', '').strip()
        item['tipo_bruto'] = ajax_data.get('sigla', '').strip()
        item['numero_bruto'] = ajax_data.get('numero')
        item['ano_bruto'] = ajax_data.get('ano')
        item['autores_bruto'] = [p.get('texto', '').strip() for p in ajax_data.get('promoventes', [])]
        item['ementa_bruto'] = ajax_data.get('ementa', '').strip()
        item['data_raspagem_bruto'] = datetime.now().isoformat()
        item['meta_bruto'] = {'source_json_codigo': codigo_processo}
        item['uf_bruto'] = self.uf
        item['municipio_bruto'] = self.municipio
        item['slug_bruto'] = self.slug

        item['url_bruto'] = response.urljoin(
            f"/ArquivoProcesso/GerarArquivoProcessoPorID/{codigo_processo}?filtroAnexo=1"
        )
        item['file_urls'] = [item['url_bruto']]
        item['nome_arquivo_padronizado'] = f"{item['tipo_bruto']}_{item['numero_bruto']}_{item['ano_bruto']}"
        return item

    def parse_detalhes(self, response):
        """Extrai dados da página de detalhes da proposição."""
        item = response.meta['item']
        soup = BeautifulSoup(response.text, 'html.parser')

        item['data_documento_bruto'] = self._extrair_data_documento(soup)
        item['assuntos_bruto'] = self._extrair_assuntos(soup)
        item['status_bruto'] = self._extrair_status(soup)

        yield item

    # --- MÉTODOS AUXILIARES DE EXTRAÇÃO ---

    def _extrair_data_documento(self, soup):
        td = soup.find('td', class_='negrito', string=re.compile(r'\s*Apresentado em\s*'))
        if td:
            return td.find_next_sibling('td').get_text(strip=True)
        return None

    def _extrair_assuntos(self, soup):
        legend = soup.find('legend', string='Palavras-Chave')
        if legend:
            spans = legend.find_parent('fieldset').find_all('span')
            return [span.get_text(strip=True) for span in spans]
        return []

    def _extrair_status(self, soup):

        legend = soup.find('legend', string=re.compile(r'Histórico.*Tramitações', re.IGNORECASE))
        if not legend:
            self.logger.warning("⚠️ Legend de tramitações não encontrado.")
            return []

        fieldset = legend.find_parent('fieldset')
        tabela = fieldset.find('table') if fieldset else None
        if not tabela:
            self.logger.warning("⚠️ Tabela de tramitações não encontrada.")
            return []

        linhas = tabela.find_all('tr')[1:]  # Ignora cabeçalho
        status_list = []

        for tr in linhas[:3]:  # Pega até 3 últimas
            cols = tr.find_all('td')
            if len(cols) >= 2:
                data = cols[0].get_text(strip=True)
                descricao = cols[1].get_text(strip=True)
                status_list.append({"data": data, "descricao": descricao})
        return status_list

    def _build_params(self, start=0, draw=1):
        """Constrói os parâmetros da requisição AJAX."""
        params = {
            'draw': str(draw),
            'start': str(start),
            'length': str(self.items_por_page_ajax),
            'tipo': '1',
            'order[0][column]': '1',
            'order[0][dir]': 'desc',
            '_': int(datetime.now().timestamp() * 1000),
            'columns[0][data]': '', 'columns[0][name]': '', 'columns[0][searchable]': 'false',
            'columns[0][orderable]': 'false', 'columns[0][search][value]': '', 'columns[0][search][regex]': 'false',
            'columns[1][data]': '1', 'columns[1][name]': 'PROJETO', 'columns[1][searchable]': 'true',
            'columns[1][orderable]': 'true', 'columns[1][search][value]': '', 'columns[1][search][regex]': 'false',
            'columns[2][data]': 'ementa', 'columns[2][name]': 'EMENTA', 'columns[2][searchable]': 'true',
            'columns[2][orderable]': 'true', 'columns[2][search][value]': '', 'columns[2][search][regex]': 'false',
            'columns[3][data]': 'norma', 'columns[3][name]': 'NORMA', 'columns[3][searchable]': 'true',
            'columns[3][orderable]': 'true', 'columns[3][search][value]': '', 'columns[3][search][regex]': 'false',
            'columns[4][data]': 'assuntos', 'columns[4][name]': 'PALAVRA', 'columns[4][searchable]': 'true',
            'columns[4][orderable]': 'true', 'columns[4][search][value]': '', 'columns[4][search][regex]': 'false',
            'columns[5][data]': 'promoventes', 'columns[5][name]': 'PROMOVENTE', 'columns[5][searchable]': 'true',
            'columns[5][orderable]': 'true', 'columns[5][search][value]': '', 'columns[5][search][regex]': 'false',
            'search[value]': '', 'search[regex]': 'false'
        }

        if self.data_inicio:
            params['autuacaoI'] = self.data_inicio
        if self.data_fim:
            params['autuacaoF'] = self.data_fim

        return params

    def _validar_data(self, data_texto):
        """Valida e formata uma data no formato YYYY-MM-DD."""
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Formato de data inválido: '{data_texto}'. Use o formato YYYY-MM-DD.")
