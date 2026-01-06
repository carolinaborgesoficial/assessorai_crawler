from .base_sapl import BaseSaplSpider

class AcRioBrancoSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de Rio Branco usando SAPL.
    """
    name = 'ac-rio-branco'
    house = 'Câmara Municipal de Rio Branco'
    uf = 'AC'
    slug = 'ac-rio-branco'
    domain = 'sapl.riobranco.ac.leg.br'
    base_url = "https://sapl.riobranco.ac.leg.br/materia/pesquisar-materia"

    # Tipos de documento seguindo os números do HTML de Rio Branco
    TIPOS_DOCUMENTO = {
        1: "Projeto de Lei Ordinária",
        5: "Projeto de Lei Complementar",
        6: "Projeto de Decreto Legislativo",
        19: "Proposta de Emenda à Lei Orgânica",
    }
