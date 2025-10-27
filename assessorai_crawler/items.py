# Arquivo: assessorai_crawler/items.py

import scrapy

class ProposicaoItem(scrapy.Item):
    """
    Este é o "molde" para os dados brutos que o spider coleta.
    O Pipeline de Padronização usará estes campos para criar o JSON final.
    """
    
    # --- Campos de Metadados Brutos (coletados pelo spider) ---
    casa_legislativa_bruto = scrapy.Field()
    titulo_bruto = scrapy.Field()
    tipo_bruto = scrapy.Field()
    numero_bruto = scrapy.Field()
    ano_bruto = scrapy.Field()
    autores_bruto = scrapy.Field()
    ementa_bruto = scrapy.Field()
    status_bruto = scrapy.Field()
    files = scrapy.Field()
    data_raspagem_bruto = scrapy.Field()
    meta_bruto = scrapy.Field()
    url_bruto = scrapy.Field()
    uuid = scrapy.Field() 
    file_urls = scrapy.Field()
    nome_arquivo_padronizado = scrapy.Field()
    uf_bruto = scrapy.Field()
    municipio_bruto = scrapy.Field()
    slug_bruto = scrapy.Field()
    data_documento_bruto = scrapy.Field()
    assuntos_bruto = scrapy.Field()

    def missing_fields(self):
        """
        Retorna uma lista de campos brutos obrigatórios que estão vazios.
        Estes são os campos mínimos que o spider precisa coletar para que o pipeline funcione.
        """
        required = [
            'casa_legislativa_bruto',
            'tipo_bruto',
            'numero_bruto',
            'ano_bruto',
            'url_bruto'
        ]
        return [f for f in required if not self.get(f)]

    def is_complete(self):
        """Verifica se todos os campos obrigatórios foram preenchidos pelo spider."""
        return not self.missing_fields()