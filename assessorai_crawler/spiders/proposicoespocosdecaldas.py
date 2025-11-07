# Arquivo: assessorai_crawler/spiders/proposicoespocosdecaldas.py

import scrapy
import re
from datetime import datetime
import hashlib
from ..items import ProposicaoItem

class ProposicoesPocosDeCaldasSpider(scrapy.Spider):
    """
    Spider para coleta de proposições da Câmara Municipal de Poços de Caldas (MG).
    Padronizado para manter consistência com outros spiders (SP, Fortaleza, Linhares, SJC).
    """
    # --- IDENTIDADE DO SPIDER ---
    name = 'proposicoespocosdecaldas'
    slug = 'proposicoespocosdecaldas'
    casa_legislativa = 'Câmara Municipal de Poços de Caldas'
    uf = 'MG'
    esfera = 'MUNICIPAL'
    municipio = 'Poços de Caldas'
    
    # --- CONFIGURAÇÕES DE COLETA ---
    allowed_domains = ['pocosdecaldas.siscam.com.br']
    custom_settings = {
        'ROBOTSTXT_OBEY': False
    }
    TIPOS_DOCUMENTO = {
        135: "Projeto de Lei",
        136: "Projeto de Lei Complementar",
    }

    # --- INIT PADRONIZADO ---
    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.data_inicio = self._validar_data(data_inicio)
        self.data_fim = self._validar_data(data_fim)

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
        """Gera as requisições iniciais para cada tipo de documento."""
        base_url = "https://pocosdecaldas.siscam.com.br/Documentos/Pesquisa"
        for codigo_tipo in self.TIPOS_DOCUMENTO.keys():
            url = f"{base_url}?id=80&pagina=1&Modulo=8&Documento={codigo_tipo}"
            yield scrapy.Request(url, callback=self.parse, meta={'page_number': 1, 'codigo_tipo': codigo_tipo})

    def parse(self, response):
        """Processa a página de listagem, filtra por data e segue para a página de detalhes."""
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

            data_str = self._get_text_after_strong(prop, "Data:") or ''
            data_str = data_str.strip()
            data_obj = None
            if data_str:
                for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
                    try:
                        data_obj = datetime.strptime(data_str, fmt)
                        break
                    except ValueError:
                        continue

            # --- Filtro de intervalo ---
            if data_obj and (self.data_inicio or self.data_fim):
                di = datetime.strptime(self.data_inicio, '%Y-%m-%d') if self.data_inicio else None
                df = datetime.strptime(self.data_fim, '%Y-%m-%d') if self.data_fim else None

                if di and data_obj < di:
                    self.logger.info(f"Item com data {data_str} é anterior a {self.data_inicio}. Parando paginação.")
                    continuar_paginando = False
                    break
                if df and data_obj > df:
                    continue

            self.itens_processados += 1
            link_detalhes = prop.css("h4 a::attr(href)").get()
            if link_detalhes:
                yield response.follow(link_detalhes, callback=self.parse_detalhes)

        if continuar_paginando:
            next_page = page_number + 1
            next_page_url = response.urljoin(f"?id=80&pagina={next_page}&Modulo=8&Documento={codigo_tipo}")
            yield scrapy.Request(next_page_url, callback=self.parse, meta={'page_number': next_page, 'codigo_tipo': codigo_tipo})

    def parse_detalhes(self, response):
        """Extrai todos os dados brutos da página de detalhes do projeto e aplica filtro final de data."""
        item = ProposicaoItem()

        titulo_completo = response.css('h3.page-header::text').get('').strip()
        match = re.search(r'^(.*?)\s+Nº\s+(\d+)/(\d{4})', titulo_completo)
        if match:
            item['tipo_bruto'] = match.group(1).strip()
            item['numero_bruto'] = match.group(2)
            item['ano_bruto'] = match.group(3)
        
        data_str = self._get_text_after_strong(response, "Data:") or ''
        item['data_documento_bruto'] = data_str.strip()

        # --- Filtro final de data ---
        data_obj = None
        if data_str:
            for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
                try:
                    data_obj = datetime.strptime(data_str, fmt)
                    break
                except ValueError:
                    continue

        if data_obj and (self.data_inicio or self.data_fim):
            di = datetime.strptime(self.data_inicio, '%Y-%m-%d') if self.data_inicio else None
            df = datetime.strptime(self.data_fim, '%Y-%m-%d') if self.data_fim else None

            if di and data_obj < di:
                self.logger.info(f"Descartando por data: {data_str} < {self.data_inicio} ({titulo_completo})")
                return
            if df and data_obj > df:
                self.logger.info(f"Descartando por data: {data_str} > {self.data_fim} ({titulo_completo})")
                return

        item['ementa_bruto'] = self._get_text_after_strong(response, "Assunto:")
        item['autores_bruto'] = [self._get_text_after_strong(response, "Autoria:")]
        item['assuntos_bruto'] = []

        status_list = []
        tramitacoes = response.css('div.data-list > div.data-list-item')
        for tramitacao in tramitacoes[:3]:
            objetivo = self._get_text_after_strong(tramitacao, "Objetivo:")
            data_envio = self._get_text_after_strong(tramitacao, "Envio:")
            if objetivo:
                status_list.append({"descricao": objetivo, "data": data_envio})
        item['status_bruto'] = status_list
        
        pdf_link = response.css('table.table a[href*="/arquivo?Id="]::attr(href)').get()
        if pdf_link:
            item['url_bruto'] = response.urljoin(pdf_link)
            nome_arquivo = f"{item.get('tipo_bruto', 'doc')}_{item.get('numero_bruto', 's_n')}_{item.get('ano_bruto', 's_a')}"
            item['file_urls'] = [item['url_bruto']]
            item['nome_arquivo_padronizado'] = nome_arquivo
            
            # salva também a URL original no campo padronizado
            item['url_documento_original'] = item['url_bruto']

        item['casa_legislativa_bruto'] = self.casa_legislativa
        item['data_raspagem_bruto'] = datetime.now().isoformat()
        item['uf_bruto'] = self.uf
        item['municipio_bruto'] = self.municipio
        item['slug_bruto'] = self.slug
        item['uuid'] = hashlib.md5(response.url.encode('utf-8')).hexdigest()
        
        yield item

    def _get_text_after_strong(self, selector, strong_text):
        """Função auxiliar para extrair o texto que vem depois de uma tag <strong>."""
        text_nodes = selector.xpath(f".//p[strong[contains(text(), '{strong_text}')]]/text()").getall()
        if text_nodes:
            return " ".join(t.strip() for t in text_nodes if t.strip()).strip()
        return None

    def _validar_data(self, data_texto):
        """Valida e formata uma data no formato YYYY-MM-DD."""
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(
                f"Formato de data inválido: '{data_texto}'. Use o formato YYYY-MM-DD."
            )
