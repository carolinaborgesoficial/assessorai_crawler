from .base_sapl import BaseSaplSpider

class AmManausSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de Manaus usando SAPL.
    """
    name = 'am-manaus'
    house = 'Câmara Municipal de Manaus'
    uf = 'AM'
    slug = 'am-manaus'
    domain = 'sapl.cmm.am.gov.br'
    base_url = "https://sapl.cmm.am.gov.br/materia/pesquisar-materia"

    # Tipos de documento específicos para Manaus
    TIPOS_DOCUMENTO = {
        4: "Projeto de Lei",
        6: "Projeto de Emenda à Loman",
        7: "Projeto de Decreto Legislativo",
        9: "Projeto de Lei Complementar",
    }
