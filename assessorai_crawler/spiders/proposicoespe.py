from .proposicoeslegislapi import ProposicoesLegislapi
from ..utils import clean_json_text

class ProposicoesPESpider(ProposicoesLegislapi):
    name = 'proposicoespe'
    house = 'Assembleia Legislativa de Pernambuco'
    uf = 'pe'
    slug = name.replace(' ', '_').lower()

    def build_url(self, entry, meta):
        raw_title = entry.get('Titulo', '').strip()
        tipo = raw_title.split()[0].upper()
        numero = raw_title.split()[1].split("/")[0].strip()
        ano = raw_title.split()[1].split("/")[1].strip() if '/' in raw_title.split()[1] else ''
        
        if tipo and numero and ano:
            url = f'https://www.al.ba.gov.br/atividade-legislativa-nova/proposicao/{tipo}.-{numero}-{ano}'
            return url
        return ''
        