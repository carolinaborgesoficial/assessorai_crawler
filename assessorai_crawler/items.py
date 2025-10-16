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
    full_text = scrapy.Field()
    length = scrapy.Field()
    meta = scrapy.Field()
    url = scrapy.Field()
    uuid = scrapy.Field()
    scraped_at = scrapy.Field()
    file_urls = scrapy.Field()  # URLs dos arquivos para download
    files = scrapy.Field()  # Metadados dos arquivos baixados pelo FilesPipeline

    def missing_fields(self):
        """Retorna lista de campos obrigatórios que estão vazios ou None"""
        required = [
            'title', 'house', 'subject', 'full_text', 'url'
        ]
        return [f for f in required if not self.get(f)]

    def is_complete(self):
        """Verifica se todos os campos obrigatórios estão preenchidos"""
        return not self.missing_fields()