# Arquivo: assessorai_crawler/spiders/proposicoeslinhares.py

import scrapy
import re
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class ProposicoesLinharesSpider(scrapy.Spider):
    # --- IDENTIDADE DO SPIDER ---
    name = 'proposicoeslinhares'
    slug = 'proposicoeslinhares'
    casa_legislativa = 'Câmara Municipal de Linhares'
    uf = 'ES'
    esfera = 'MUNICIPAL'
    municipio = 'Linhares'
    
    # --- CONFIGURAÇÕES DE COLETA ---
    allowed_domains = ['linhares.camarasempapel.com.br']
    start_urls = ["https://linhares.camarasempapel.com.br/spl/consulta-producao.aspx?tipo=5003"]
    
    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        super(ProposicoesLinharesSpider, self).__init__(*args, **kwargs)
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

    def parse(self, response):
        """ 
        Processa a página de listagem, filtra por data e segue para os detalhes.
        """
        proposicoes = response.css("div.kt-widget5__item")
        continuar_paginando = True

        for prop in proposicoes:
            if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
                self.logger.info(f"Limite de {self.limite_total_itens} itens atingido. Encerrando.")
                return

            data_str = prop.css("span.kt-font-info:contains('Data:') + span.kt-font-info::text").get('').strip()
            if data_str:
                try:
                    data_obj = datetime.strptime(data_str, '%d/%m/%Y')
                    if self.data_inicio and data_obj < self.data_inicio:
                        self.logger.info(f"Item com data {data_str} é anterior a {self.data_inicio}. Parando a paginação.")
                        continuar_paginando = False
                        break # Para o loop desta página
                    if self.data_fim and data_obj > self.data_fim:
                        continue # Pula este item, mas continua na página
                except ValueError:
                    pass
            
            item = self._criar_item_da_lista(prop, response)
            if not item:
                continue

            link_detalhes = prop.css("a.kt-widget5__title::attr(href)").get()
            if link_detalhes:
                self.itens_processados += 1
                yield response.follow(link_detalhes, callback=self.parse_detalhes, meta={'item': item})

        # Lógica de paginação aprimorada
        if continuar_paginando:
            next_page_button = response.css('a#ContentPlaceHolder1_lbNext[href]')
            if next_page_button:
                self.logger.info("Navegando para a próxima página...")
                form_data = {
                    '__EVENTTARGET': 'ctl00$ContentPlaceHolder1$lbNext',
                    '__EVENTARGUMENT': '',
                    '__VIEWSTATE': response.css('input#__VIEWSTATE::attr(value)').get(),
                    '__VIEWSTATEGENERATOR': response.css('input#__VIEWSTATEGENERATOR::attr(value)').get(),
                    '__EVENTVALIDATION': response.css('input#__EVENTVALIDATION::attr(value)').get(),
                }
                yield scrapy.FormRequest(url=response.url, formdata=form_data, callback=self.parse)

    def _criar_item_da_lista(self, prop, response):
        """ Cria o item bruto inicial a partir do elemento da lista. """
        item = ProposicaoItem()
        titulo_tag = prop.css("a.kt-widget5__title")
        if not titulo_tag: return None
        
        item['titulo_bruto'] = titulo_tag.css('::text').get('').strip()
        match = re.search(r'^(.*?)\s+n°\s+(\d+)/(\d{4})', item['titulo_bruto'], re.IGNORECASE)
        item['tipo_bruto'], _, item['ano_bruto'] = (match.groups() if match else (None, None, None))
        protocolo_num = prop.xpath(".//span[contains(text(), 'Protocolo N°:')]/following-sibling::a[1]/text()").get()
        item['numero_bruto'] = protocolo_num.strip() if protocolo_num else (match.group(2) if match else None)
        item['ementa_bruto'] = prop.css("a.kt-widget5__desc::text").get('').strip()
        autor_bruto = ''.join(prop.css("span.kt-font-info a::text").getall()).strip()
        item['autores_bruto'] = [re.sub(r'\s+', ' ', autor_bruto)] if autor_bruto else []
        
        item['casa_legislativa_bruto'] = self.casa_legislativa
        item['data_raspagem_bruto'] = datetime.now().isoformat()
        item['uf_bruto'] = self.uf
        item['municipio_bruto'] = self.municipio
        item['slug_bruto'] = self.slug
        
        link_processo_tag = prop.css("a[href*='Digital.aspx']")
        url_processo = response.urljoin(link_processo_tag.attrib['href']) if link_processo_tag else None
        item['uuid'] = hashlib.md5(url_processo.encode('utf-8')).hexdigest() if url_processo else None
        
        return item

    def parse_detalhes(self, response):
        """ Extrai dados da página de detalhes e segue para a página de peças. """
        item = response.meta['item']
        
        item['data_documento_bruto'] = response.css('#ContentPlaceHolder1_sp_data_apresentacao::text').get('').strip()
        item['assuntos_bruto'] = response.css('#ContentPlaceHolder1_div_palavra_chave_exibicao p::text').getall()
        
        descricao_status = response.css('#ContentPlaceHolder1_p_situacao::text').get()
        if descricao_status:
            item['status_bruto'] = [{"descricao": descricao_status.strip(), "data": None}]
        else:
            item['status_bruto'] = []

        link_pecas = response.css('#ContentPlaceHolder1_btn_arvore_arquivos::attr(href)').get()
        if link_pecas:
            url_pecas = response.urljoin(link_pecas)
            yield scrapy.Request(url_pecas, callback=self.parse_pecas, meta={'item': item})
        else:
            yield item

    def parse_pecas(self, response):
        """ Encontra o link final do PDF e entrega o item completo. """
        item = response.meta['item']
        pdf_link = response.css('a[href$=".pdf"]::attr(href)').get()
        
        if pdf_link:
            item['url_bruto'] = response.urljoin(pdf_link)
            nome_arquivo = f"{item.get('tipo_bruto', 'doc')}_{item.get('numero_bruto', 's_n')}_{item.get('ano_bruto', 's_a')}"
            item['file_urls'] = [item['url_bruto']]
            item['nome_arquivo_padronizado'] = nome_arquivo
        
        yield item