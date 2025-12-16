from .base_sapl import BaseSaplSpider

class RnNatalSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de Natal usando SAPL.
    """
    name = 'rn-natal'
    house = 'Câmara Municipal de Natal'
    uf = 'RN'
    slug = 'rn-natal'
    domain = 'sapl.natal.rn.leg.br'
    base_url = "https://sapl.natal.rn.leg.br/materia/pesquisar-materia"

    # Tipos de documento específicos para Natal
    TIPOS_DOCUMENTO = {
        1: "Projeto de Lei",
        2: "Projeto de Emenda à Loman",
        3: "Projeto de Decreto Legislativo",
        4: "Projeto de Lei Complementar",
    }
