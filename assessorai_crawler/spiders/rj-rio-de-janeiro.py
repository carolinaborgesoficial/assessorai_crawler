import scrapy
import re
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from ..items import ProposicaoItem


class RjProposicoesSpider(scrapy.Spider):
    """
    Spider para coletar proposições da Câmara Municipal do Rio de Janeiro.
    Saída: ementa limpa, autores normalizados, status (últimos 3 registros).
    """

    name = "rj-rio-de-janeiro"
    house = "Câmara Municipal do Rio de Janeiro"
    uf = "RJ"
    slug = "rj-rio-de-janeiro"
    municipio = "Rio de Janeiro"

    allowed_domains = ["aplicnt.camara.rj.gov.br"]
    start_urls = [
        "https://aplicnt.camara.rj.gov.br/APL/Legislativos/scpro.nsf/Internet/LeiInt?OpenForm"
    ]
    custom_settings = {"ROBOTSTXT_OBEY": False}

    def __init__(self, data_inicio=None, data_fim=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_inicio = self._validar_data(data_inicio)
        self.data_fim = self._validar_data(data_fim)
        self.total_items_limit = int(limit) if limit else None
        self.items_processed_count = 0

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")
        linhas = soup.select('table[cellpadding="2"] tr[valign="top"]')

        for linha in linhas:
            if self.total_items_limit and self.items_processed_count >= self.total_items_limit:
                return

            cols = linha.find_all("td")
            if len(cols) < 6:
                continue

            link_tag = cols[0].find("a")
            if not link_tag:
                continue

            url_detalhes = response.urljoin(link_tag["href"])
            numero_ano = link_tag.get_text(strip=True)
            try:
                numero, ano = numero_ano.split("/")
            except ValueError:
                continue

            ementa = cols[3].get_text(strip=True)
            data_publicacao = cols[4].get_text(strip=True)
            autores = cols[5].get_text(strip=True)

            data_obj = self._parse_data(data_publicacao)
            data_fmt = data_obj.strftime("%Y-%m-%d") if data_obj else None

            # Filtro de datas
            if data_obj and (self.data_inicio or self.data_fim):
                di = datetime.strptime(self.data_inicio, "%Y-%m-%d") if self.data_inicio else None
                df = datetime.strptime(self.data_fim, "%Y-%m-%d") if self.data_fim else None
                if di and data_obj < di:
                    continue
                if df and data_obj > df:
                    continue

            item = ProposicaoItem()
            item["house"] = self.house
            item["title"] = f"PL {numero}/{ano}"
            item["type"] = "PL"
            item["number"] = int(numero)
            item["year"] = int(ano)
            item["subject"] = ementa.split("=>")[0].split("AUTOR:")[0].strip()
            item["author"] = [a.strip() for a in autores.split(",") if a.strip()]
            item["presentation_date"] = data_fmt
            item["scraped_at"] = datetime.now().isoformat()
            item["uuid"] = hashlib.md5(url_detalhes.encode("utf-8")).hexdigest()
            item["project_url"] = url_detalhes
            item["meta"] = {"uf": self.uf, "municipio": self.municipio, "slug": self.slug}

            self.items_processed_count += 1
            yield scrapy.Request(url_detalhes, callback=self.parse_detalhes, meta={"item": item})

        # Paginação
        match = re.search(r"Start=(\d+)", response.url)
        start_val = int(match.group(1)) if match else 0
        next_start = start_val + 100
        next_url = f"https://aplicnt.camara.rj.gov.br/APL/Legislativos/scpro.nsf/Internet/LeiInt?OpenForm&Start={next_start}"
        if linhas:
            yield scrapy.Request(next_url, callback=self.parse)

    def parse_detalhes(self, response):
        item = response.meta["item"]
        soup = BeautifulSoup(response.text, "html.parser")

        # Captura tramitação (últimos 3 registros)
        status_list = []
        tramitacao_header = soup.find("font", string=re.compile("TRAMITAÇÃO DO PROJETO"))
        if tramitacao_header:
            tabela_tramitacao = tramitacao_header.find_next("table")
            if tabela_tramitacao:
                trs = tabela_tramitacao.find_all("tr")[1:]  # ignora cabeçalho
                for tr in trs[-3:]:  # pega últimos 3
                    # pega toda a linha como texto
                    descricao = " ".join(td.get_text(" ", strip=True) for td in tr.find_all("td")).strip()
                    # tenta extrair data (se houver)
                    data_status = None
                    data_match = re.search(r"(\d{2}/\d{2}/\d{4})", descricao)
                    if data_match:
                        data_status = self._formatar_data(data_match.group(1))
                    status_list.append({"descricao": descricao, "data": data_status})

        item["status"] = status_list

        # PDF
        pdf_link_tag = soup.find("a", href=lambda href: href and ".pdf" in href.lower())
        if pdf_link_tag:
            url_pdf = response.urljoin(pdf_link_tag["href"])
            item["url"] = url_pdf
            item["file_urls"] = [url_pdf]
        else:
            item["url"] = ""
            item["file_urls"] = []

        yield item


    # --- Funções auxiliares ---
    def _formatar_data(self, data_texto):
        try:
            return datetime.strptime(data_texto.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _validar_data(self, data_texto):
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _parse_data(self, data_texto):
        if not data_texto:
            return None
        for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(data_texto.strip(), fmt)
            except ValueError:
                continue
        return None

    def _limpar_status(self, status_bruto):
        status_list = []
        for status in status_bruto:
            descricao = status.get("descricao", "").strip()
            data = status.get("data", None)
            if "=>" in descricao:
                descricao = descricao.split("=>")[0].strip()
            descricao = re.sub(r"\s+", " ", descricao)
            status_list.append({"descricao": descricao, "data": data})
        return status_list
