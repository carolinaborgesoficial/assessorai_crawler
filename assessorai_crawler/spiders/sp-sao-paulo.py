# Arquivo: assessorai_crawler/spiders/sp-sao-paulo.py
import scrapy
import hashlib
import json
from datetime import datetime
from ..items import ProposicaoItem

class SpSaoPauloSpider(scrapy.Spider):
    """
    Coleta proposições da Câmara Municipal de São Paulo, processando os PDFs associados.
    """
    name = 'sp-sao-paulo'
    house = 'Câmara Municipal de São Paulo'
    uf = 'SP'
    slug = 'sp-sao-paulo'
    allowed_domains = ['splegisconsulta.saopaulo.sp.leg.br', 'splegispdarmazenamento.blob.core.windows.net']
    ajax_url = 'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/PageDataProjeto'
    
    # O spider usará as configurações de delay e concorrência do settings.py
    
    items_per_page_ajax = 100 # Busca em pacotes de 100 para eficiência


    def __init__(self, data_inicio=None, data_fim=None, limit=None, *args, **kwargs):
        """
        Permite limitar a coleta via linha de comando: -a limit=100
        """
        super(SpSaoPauloSpider, self).__init__(*args, **kwargs)
        self.data_inicio = data_inicio
        self.data_fim = data_fim
        self.total_items_limit = int(limit) if limit else None
        self.items_processed_count = 0
        
        if self.total_items_limit:
            self.logger.info(f"Coleta limitada a {self.total_items_limit} itens.")
        else:
            self.logger.info("Coletando todos os itens encontrados.")

    def start_requests(self):
        """ Inicia a coleta fazendo a primeira requisição para a API de listagem. """
        params = {
            'draw': '1', 'start': '0', 'length': str(self.items_per_page_ajax),
            'tipo': '1', 'somenteEmTramitacao': 'false',
            'order[0][column]': '1', 'order[0][dir]': 'desc',
            'search[value]': '', 'search[regex]': 'false',
        }
        if self.data_inicio:
            params['autuacaoI'] = self.data_inicio
        if self.data_fim:
            params['autuacaoF'] = self.data_fim

        headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': 'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/IndexProjeto'}
        yield scrapy.FormRequest(url=self.ajax_url, formdata=params, headers=headers, callback=self.parse, meta={'params_template': params.copy()})


    def parse(self, response, **kwargs):
        """ Processa a lista de proposições e dispara requisições para os PDFs. """
        data_json = json.loads(response.text)
        proposicoes_ajax = data_json.get('data', [])

        for ajax_data in proposicoes_ajax:
            if self.total_items_limit and self.items_processed_count >= self.total_items_limit:
                self.logger.info(f"Limite de {self.total_items_limit} itens atingido. Encerrando.")
                return

            self.items_processed_count += 1
            
            # Cria um item com os dados do JSON da lista
            item = self.create_item_from_ajax(ajax_data, response)
            if not item:
                continue

            yield item
        
        # Lógica de Paginação: continua se não houver limite ou se ele não foi atingido
        if not self.total_items_limit or self.items_processed_count < self.total_items_limit:
            yield self.get_next_page_request(response, data_json)

    def create_item_from_ajax(self, ajax_data, response):
        """ Cria e preenche um item parcial com os dados da listagem AJAX. """
        codigo_processo = ajax_data.get('codigo')
        if not codigo_processo:
            return None

        item = ProposicaoItem()
        item['house'] = self.house
        item['title'] = ajax_data.get('texto', '').strip()
        item['type'] = ajax_data.get('sigla', '').strip()
        item['number'] = ajax_data.get('numero')
        item['year'] = ajax_data.get('ano')
        item['author'] = [p.get('texto', '').strip() for p in ajax_data.get('promoventes', [])]
        item['subject'] = ajax_data.get('ementa', '').strip()
        item['scraped_at'] = datetime.now().isoformat()
        item['meta'] = {'source_json_codigo': codigo_processo}
        
        pdf_link_template = "/ArquivoProcesso/GerarArquivoProcessoPorID/{codigo}?referidas=true" if ajax_data.get('natodigital') else "/ArquivoProcesso/GerarArquivoProcessoPorID/{codigo}?filtroAnexo=1"
        item['url'] = response.urljoin(pdf_link_template.format(codigo=codigo_processo))
        item['uuid'] = hashlib.md5(str(codigo_processo).encode('utf-8')).hexdigest()

        # Configurar para download via pipeline
        item['file_urls'] = [item['url']]

        # Caminho para .md
        normalized_type = item['type'].lower().replace(' ', '-') if item['type'] else 'unknown'
        item['md_files'] = f"{self.uf}/{self.slug}/{normalized_type}-{item['number']}-{item['year']}.md"

        return item

    def get_next_page_request(self, response, data_json):
        """ Monta a requisição para a próxima página de resultados, se houver. """
        records_filtered = data_json.get('recordsFiltered', 0)
        current_start_offset = int(response.meta.get('params_template', {}).get('start', 0))
        next_page_start_offset = current_start_offset + self.items_per_page_ajax

        if next_page_start_offset < records_filtered:
            params_template = response.meta.get('params_template')
            next_params = params_template.copy()
            next_params['draw'] = str(int(params_template.get('draw', 1)) + 1)
            next_params['start'] = str(next_page_start_offset)
            
            self.logger.info(f"Buscando próxima página. Start: {next_page_start_offset}")
            return scrapy.FormRequest(url=self.ajax_url, formdata=next_params, headers=response.request.headers, callback=self.parse, meta={'params_template': next_params})