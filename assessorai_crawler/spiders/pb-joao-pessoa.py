from .base_sapl import BaseSaplSpider

class PbJoaoPessoaSpider(BaseSaplSpider):
    """
    Coleta proposições da Câmara Municipal de João Pessoa usando SAPL.
    """
    name = 'pb-joao-pessoa'
    house = 'Câmara Municipal de João Pessoa'
    uf = 'PB'
    slug = 'pb-joao-pessoa'
    domain = 'sapl.joaopessoa.pb.leg.br'
    base_url = "https://sapl.joaopessoa.pb.leg.br/materia/pesquisar-materia"

    # Tipos de documento específicos para João Pessoa
    TIPOS_DOCUMENTO = {
        1: "Projeto de Lei Ordinária",
        5: "Projeto de Lei Complementar",
        6: "Projeto de Decreto Legislativo",
        9: "Proposta de Emenda à Lei Orgânica",
    }
