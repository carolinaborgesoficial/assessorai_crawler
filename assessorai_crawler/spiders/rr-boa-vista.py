from .base_sapl import BaseSaplSpider

class RrBoaVistaSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de Boa Vista usando SAPL.
    """
    name = 'rr-boa-vista'
    house = 'Câmara Municipal de Boa Vista'
    uf = 'RR'
    slug = 'rr-boa-vista'
    domain = 'sapl.boavista.rr.leg.br'
    base_url = "https://sapl.boavista.rr.leg.br/materia/pesquisar-materia"

    # Tipos de documento específicos para Boa Vista
    TIPOS_DOCUMENTO = {
        1: "Projeto de Lei do Legislativo",
        5: "Projeto de Lei Complementar",
        6: "Projeto de Decreto Legislativo",
        9: "Projeto de Lei do Executivo",
        15: "Proposta de Emenda à Lei Orgânica",
    }