# Arquivo: assessorai_crawler/spiders/proposicoescidsp.py
import scrapy
import hashlib
import json 
import re
import io
import fitz  # PyMuPDF
from datetime import datetime
from urllib.parse import urlencode 
from ..items import ProposicaoItem

class ProposicoescidspSpider(scrapy.Spider):
    """
    Coleta proposições da Câmara Municipal de São Paulo, processando os PDFs associados.
    """
    name = 'proposicoescidsp'
    house = 'Câmara Municipal de São Paulo'
    uf = 'SP'
    slug = 'proposicoescidsp'
    allowed_domains = ['splegisconsulta.saopaulo.sp.leg.br', 'splegispdarmazenamento.blob.core.windows.net']
    ajax_url = 'https://splegisconsulta.saopaulo.sp.leg.br/Pesquisa/PageDataProjeto'
    
    # O spider usará as configurações de delay e concorrência do settings.py
    
    items_per_page_ajax = 100 # Busca em pacotes de 100 para eficiência

    def __init__(self, limit=None, *args, **kwargs):
        """
        Permite limitar a coleta via linha de comando: -a limit=100
        """
        super(ProposicoescidspSpider, self).__init__(*args, **kwargs)
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
            'tipo': '0', 'somenteEmTramitacao': 'false',
            'order[0][column]': '1', 'order[0][dir]': 'desc',
            'search[value]': '', 'search[regex]': 'false',
        }
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
            
            # Cria um item parcial com os dados do JSON da lista
            item = self.create_item_from_ajax(ajax_data, response)
            if not item:
                continue

            # Dispara a requisição para o PDF, passando o item parcial
            yield scrapy.Request(url=item['url'], callback=self.parse_pdf_content, errback=self.handle_pdf_error, meta={'item': item})
        
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

    def handle_pdf_error(self, failure):
        """ Lida com falhas no download do PDF (timeout, 404, etc.). """
        item = failure.request.meta['item']
        self.logger.error(f"Falha ao baixar PDF para '{item['title']}'. URL: {item['url']}. Erro: {failure.value}")
        item['full_text'] = "[PDF_NAO_LOCALIZADO]"
        item['length'] = len(item['full_text'])
        item['presentation_date'] = None
        if item.is_complete():
            yield item

    def parse_pdf_content(self, response):
        """ Processa o conteúdo do PDF baixado para extrair o texto e a data. """
        item = response.meta['item']
        try:
            pdf_bytes = io.BytesIO(response.body)
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            texto_bruto = "".join([page.get_text("text") for page in pdf_document])
            
            if not texto_bruto.strip():
                raise ValueError("PDF vazio ou sem texto extraível.")

            corpo_bruto, sucesso = self.extrair_corpo_lei(texto_bruto)
            if sucesso:
                texto_limpo = self.limpar_texto_pdf(corpo_bruto)
                texto_formatado = self.formatar_texto_lei(texto_limpo)
                item['full_text'] = texto_formatado[:2500]
            else:
                item['full_text'] = "[PDF_ILEGIVEL]"
            
            item['presentation_date'] = self.extrair_data_apresentacao(texto_bruto)
        except Exception as e:
            self.logger.error(f"Falha ao processar conteúdo do PDF para '{item['title']}': {e}")
            item['full_text'] = "[PDF_ILEGIVEL]"
            item['presentation_date'] = None
        
        item['length'] = len(item['full_text'])
        if item.is_complete():
            yield item
        else:
            self.logger.warning(f"Item '{item['title']}' incompleto. Campos faltando: {item.missing_fields()}. Item descartado.")

    # --- Métodos Auxiliares de Processamento de Texto ---
    def extrair_corpo_lei(self, texto_bruto):
        """ Isola o corpo da lei, começando em 'Ementa:'. Retorna o texto e um booleano de sucesso. """
        match_inicio = re.search(r"Ementa:", texto_bruto, flags=re.IGNORECASE)
        if not match_inicio:
            return "", False
        start_index = match_inicio.start()
        match_fim = re.search(r"Sala das Sessões", texto_bruto, flags=re.IGNORECASE)
        if not match_fim:
            return texto_bruto[start_index:].strip(), True
        end_index = match_fim.start()
        return texto_bruto[start_index:end_index].strip(), True

    def limpar_texto_pdf(self, texto_para_limpar):
        """ Remove lixo de OCR, cabeçalhos e rodapés do bloco de texto. """
        texto_limpo = re.sub(r"^\s*Palácio Anchieta.*$", "", texto_para_limpar, flags=re.MULTILINE)
        texto_limpo = re.sub(r"^\s*PROJETO DE LEI Nº?.*$", "", texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
        texto_limpo = re.sub(r"^_+$", "", texto_limpo, flags=re.MULTILINE)
        texto_limpo = re.sub(r"Matéria PL .*? conferida em.*$", "", texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
        texto_limpo = re.sub(r"autuado por .*$", "", texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
        texto_limpo = re.sub(r"fls\.\s*\d+", "", texto_limpo, flags=re.IGNORECASE)
        texto_limpo = re.sub(r"Impresso n[oó] .*? da CMSP", "", texto_limpo, flags=re.IGNORECASE)
        texto_limpo = re.sub(r"[«»”'´`‘]", "", texto_limpo)
        texto_limpo = re.sub(r"cod\.\s*\d+", "", texto_limpo, flags=re.IGNORECASE)
        return texto_limpo.strip()

    def extrair_data_apresentacao(self, texto_bruto):
        """ Usa regex para encontrar a data de apresentação no texto bruto. """
        match = re.search(r"Sala das Sessões,?\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})", texto_bruto, flags=re.IGNORECASE)
        if match: return match.group(1).strip()
        match = re.search(r"PROJETO DE LEI.*?DE\s+(\d{2}/\d{2}/\d{4})", texto_bruto, flags=re.IGNORECASE)
        if match: return match.group(1)
        match = re.search(r"autuado por .*? em\s+(\d{2}/\d{2}/\d{4})", texto_bruto, flags=re.IGNORECASE)
        if match: return match.group(1)
        return None

    def formatar_texto_lei(self, texto_bruto):
        """ Formata o texto para uma única linha, sem quebras de linha. """
        texto_corrigido = re.sub(r'-\n', '', texto_bruto)
        texto_com_espacos = re.sub(r'\s*\n\s*', ' ', texto_corrigido)
        texto_final = re.sub(r'\s{2,}', ' ', texto_com_espacos)
        return texto_final.strip()
