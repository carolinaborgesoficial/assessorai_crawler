import scrapy

class ProposicaoItem(scrapy.Item):
    title = scrapy.Field()
    house = scrapy.Field()
    type = scrapy.Field()
    number = scrapy.Field()
    presentation_date = scrapy.Field()
    year = scrapy.Field()
    author = scrapy.Field()
    subject = scrapy.Field()
    meta = scrapy.Field()
    url = scrapy.Field()
    uuid = scrapy.Field()
    scraped_at = scrapy.Field()
    emenda = scrapy.Field()
    file_urls = scrapy.Field()  # URLs dos arquivos para download
    pdf_files = scrapy.Field()  # Metadados dos arquivos baixados pelo FilesPipeline
    md_files = scrapy.Field()  # Caminho para o arquivo .md com texto extraído
    project_url = scrapy.Field()  # URL da página de detalhes do projeto
    full_text = scrapy.Field()  # Texto completo da proposição
    length = scrapy.Field()  # Comprimento do texto
    status = scrapy.Field() 
    
    def missing_fields(self):
        """Retorna lista de campos obrigatórios que estão vazios ou None"""
        required = [
            'title', 'house', 'subject', 'url'
        ]
        return [f for f in required if not self.get(f)]

    def is_complete(self):
        """Verifica se todos os campos obrigatórios estão preenchidos"""
        return not self.missing_fields()