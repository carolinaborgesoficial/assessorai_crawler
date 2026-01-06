from .base_sapl import BaseSaplSpider

class RoPortoVelhoSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de Porto Velho usando SAPL.
    """
    name = 'ro-porto-velho'
    house = 'Câmara Municipal de Porto Velho'
    uf = 'RO'
    slug = 'ro-porto-velho'
    domain = 'sapl.portovelho.ro.leg.br'
    base_url = "https://sapl.portovelho.ro.leg.br/materia/pesquisar-materia"

    # Tipos de documento específicos para Porto Velho
    TIPOS_DOCUMENTO = {
        5: "Projeto de Lei",
        12: "Projeto de Lei Complementar",
        6: "Projeto de Decreto Legislativo",
        13: "Proposta de Emenda à Lei Orgânica",
    }
