# Arquivo: assessorai_crawler/spiders/proposicoespocosdecaldas.py

import scrapy
import re
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class ProposicoesPocosDeCaldasSpider(scrapy.Spider):
    """
    Coleta proposições da Câmara Municipal de Poços de Caldas, integrando-se
    à arquitetura de pipelines para padronização e download de arquivos.
    """
    # --- 1. IDENTIDADE DO SPIDER ---
    name = 'proposicoespocosdecaldas'
    slug = 'proposicoespocosdecaldas'
    casa_legislativa = 'Câmara Municipal de Poços de Caldas'
    uf = 'MG'
    esfera = 'MUNICIPAL'
    municipio = 'Poços de Caldas'
    
    # --- 2. CONFIGURAÇÕES DE COLETA ---
    allowed_domains = ['pocosdecaldas.siscam.com.br']
    custom_settings = {
        'ROBOTSTXT_OBEY': False
    }
    TIPOS_DOCUMENTO = {
        135: "Projeto de Lei",
        136: "Projeto de Lei Complementar",
    }

    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        """
        Inicializa o spider com parâmetros de data e limite.
        Ex: scrapy crawl proposicoespocosdecaldas -a data_inicio=2024-01-01 -a limite=50
        """
        super(ProposicoesPocosDeCaldasSpider, self).__init__(*args, **kwargs)
        self.limite_total_itens = int(limite) if limite else None
        self.itens_processados = 0
        self.data_inicio = datetime.strptime(data_inicio, '%Y-%m-%d') if data_inicio else None
        self.data_fim = datetime.strptime(data_fim, '%Y-%m-%d') if data_fim else None
        
        log_mensagem = f"Iniciando coleta para {self.casa_legislativa}."
        if self.data_inicio or self.data_fim:
            log_mensagem += f" Período de {data_inicio or '...'} a {data_fim or '...'}"
        if self.limite_total_itens:
            log_mensagem += f" (Limite de {limite} itens)."
        self.logger.info(log_mensagem)

    def start_requests(self):
        """ Gera as requisições iniciais para cada tipo de documento. """
        base_url = "https://pocosdecaldas.siscam.com.br/Documentos/Pesquisa"
        for codigo_tipo in self.TIPOS_DOCUMENTO.keys():
            url = f"{base_url}?id=80&pagina=1&Modulo=8&Documento={codigo_tipo}"
            yield scrapy.Request(url, callback=self.parse, meta={'page_number': 1, 'codigo_tipo': codigo_tipo})

    def parse(self, response):
        """ Processa a página de listagem, filtra por data e segue para a página de detalhes. """
        page_number = response.meta['page_number']
        codigo_tipo = response.meta['codigo_tipo']
        
        proposicoes = response.css("div.data-list-item")
        if not proposicoes:
            self.logger.info(f"Fim da paginação para o tipo {codigo_tipo}.")
            return

        continuar_paginando = True
        for prop in proposicoes:
            if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
                self.logger.info(f"Limite de {self.limite_total_itens} itens atingido.")
                return

            data_str = self._get_text_after_strong(prop, "Data:")
            if data_str:
                try:
                    data_obj = datetime.strptime(data_str, '%d/%m/%Y')
                    if self.data_inicio and data_obj < self.data_inicio:
                        self.logger.info(f"Item com data {data_str} é anterior a {self.data_inicio}. Parando a paginação.")
                        continuar_paginando = False
                        break
                    if self.data_fim and data_obj > self.data_fim:
                        continue
                except ValueError:
                    pass

            self.itens_processados += 1
            link_detalhes = prop.css("h4 a::attr(href)").get()
            if link_detalhes:
                yield response.follow(link_detalhes, callback=self.parse_detalhes)
        
        if continuar_paginando:
            next_page = page_number + 1
            next_page_url = response.urljoin(f"?id=80&pagina={next_page}&Modulo=8&Documento={codigo_tipo}")
            yield scrapy.Request(next_page_url, callback=self.parse, meta={'page_number': next_page, 'codigo_tipo': codigo_tipo})

    def parse_detalhes(self, response):
        """ Extrai todos os dados brutos da página de detalhes do projeto. """
        item = ProposicaoItem()

        # --- Extração de dados da página de detalhes ---
        titulo_completo = response.css('h3.page-header::text').get('').strip()
        match = re.search(r'^(.*?)\s+Nº\s+(\d+)/(\d{4})', titulo_completo)
        if match:
            item['tipo_bruto'] = match.group(1).strip()
            item['numero_bruto'] = match.group(2)
            item['ano_bruto'] = match.group(3)
        
        item['data_documento_bruto'] = self._get_text_after_strong(response, "Data:")
        item['ementa_bruto'] = self._get_text_after_strong(response, "Assunto:")
        item['autores_bruto'] = [self._get_text_after_strong(response, "Autoria:")]
        item['assuntos_bruto'] = [] # Este site não tem um campo separado para "assuntos"

        status_list = []
        tramitacoes = response.css('div.data-list > div.data-list-item')
        for tramitacao in tramitacoes[:3]: # Pega os 3 mais recentes
            objetivo = self._get_text_after_strong(tramitacao, "Objetivo:")
            data_envio = self._get_text_after_strong(tramitacao, "Envio:")
            if objetivo:
                status_list.append({"descricao": objetivo, "data": data_envio})
        item['status_bruto'] = status_list
        
        # --- Campos de identidade e para pipelines ---
        pdf_link = response.css('table.table a[href*="/arquivo?Id="]::attr(href)').get()
        if pdf_link:
            item['url_bruto'] = response.urljoin(pdf_link)
            nome_arquivo = f"{item.get('tipo_bruto', 'doc')}_{item.get('numero_bruto', 's_n')}_{item.get('ano_bruto', 's_a')}"
            item['file_urls'] = [item['url_bruto']]
            item['nome_arquivo_padronizado'] = nome_arquivo

        item['casa_legislativa_bruto'] = self.casa_legislativa
        item['data_raspagem_bruto'] = datetime.now().isoformat()
        item['uf_bruto'] = self.uf
        item['municipio_bruto'] = self.municipio
        item['slug_bruto'] = self.slug
        item['uuid'] = hashlib.md5(response.url.encode('utf-8')).hexdigest()
        
        yield item

    def _get_text_after_strong(self, selector, strong_text):
        """ Função auxiliar para extrair o texto que vem depois de uma tag <strong>. """
        text_nodes = selector.xpath(f".//p[strong[contains(text(), '{strong_text}')]]/text()").getall()
        if text_nodes:
            return " ".join(t.strip() for t in text_nodes if t.strip()).strip()
        return None