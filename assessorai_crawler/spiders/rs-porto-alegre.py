import scrapy
import re
import hashlib
from bs4 import BeautifulSoup
from datetime import datetime
from ..items import ProposicaoItem


class RsPortoAlegreSpider(scrapy.Spider):
    """
    Coleta proposições da Câmara Municipal de Porto Alegre, processando os PDFs associados.
    """
    name = "rs-porto-alegre"
    house = "Câmara Municipal de Porto Alegre"
    uf = "RS"
    slug = "rs-porto-alegre"
    allowed_domains = ["camarapoa.rs.gov.br"]

    BASE_URL = "https://www.camarapoa.rs.gov.br"
    ajax_url_template = BASE_URL + "/projetos?andamento=todos&busca=%2F{ano}&tipo=PLL&page={page}"

    def __init__(self, ano=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not ano:
            raise ValueError("É necessário passar o parâmetro -a ano=YYYY")
        self.ano = ano
        self.limit = int(limit) if limit else None
        self.count = 0

    def start_requests(self):
        url = self.ajax_url_template.format(ano=self.ano, page=1)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest"
        }
        yield scrapy.Request(
            url,
            headers=headers,
            callback=self.parse_list,
            meta={"page": 1},
            dont_filter=True
        )

    def parse_list(self, response):
        match = re.search(r"\$\('.view'\)\.replaceWith\('(.*)'\);", response.text, re.DOTALL)
        if not match:
            self.logger.warning("Não consegui extrair fragmento da página %s", response.url)
            return

        raw = match.group(1)
        html_fragment = raw.replace("\\/", "/").replace('\\"', '"')
        soup = BeautifulSoup(html_fragment, "html.parser")

        artigos = soup.select("article.item h2.header a")
        if not artigos:
            self.logger.info("Nenhum artigo encontrado na página %s. Encerrando paginação.", response.url)
            return

        for artigo in artigos:
            if self.limit and self.count >= self.limit:
                return

            titulo = artigo.get_text(strip=True)
            if "PLL" not in titulo:
                continue  # descarta se não for Projeto de Lei do Legislativo

            link = self.BASE_URL + artigo["href"]
            uid = hashlib.md5(link.encode()).hexdigest()
            self.count += 1

            yield scrapy.Request(
                link,
                callback=self.parse_detail,
                meta={"uuid": uid, "titulo": titulo, "link": link}
            )

        # Paginação
        if not self.limit or self.count < self.limit:
            page = response.meta["page"]
            next_page = page + 1
            next_url = self.ajax_url_template.format(ano=self.ano, page=next_page)
            headers = {
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest"
            }
            yield scrapy.Request(
                next_url,
                headers=headers,
                callback=self.parse_list,
                meta={"page": next_page}
            )

    def parse_detail(self, response):
        uid = response.meta["uuid"]
        titulo = response.meta["titulo"]
        link = response.meta["link"]

        item = ProposicaoItem()
        item["uuid"] = uid
        item["type"] = "Projeto de Lei"
        item["project_url"] = link
        item["house"] = self.house
        item["scraped_at"] = datetime.now().isoformat()

        # Número e ano
        m = re.search(r"PLL\s+(\d+)/(\d+)", titulo)
        if m:
            item["number"] = m.group(1)
            year_raw = m.group(2)
            if len(year_raw) == 2:
                item["year"] = "20" + year_raw
            else:
                item["year"] = year_raw
            item["title"] = f"Projeto de Lei nº {item['number']}/{item['year']}"

            # filtro de ano: descarta se não for o ano solicitado
            if item["year"] != self.ano:
                self.logger.info(f"Descartando proposição de outro ano: {item['title']}")
                return

        # Autores
        autores = response.css("dl.dados dt:contains('Autores') + dd::text").get()
        if autores:
            item["author"] = [a.strip() for a in autores.split(",")]

        # Ementa
        emenda = response.xpath("//dl[@class='dados']/dt[contains(text(),'Ementa')]/following-sibling::dd/text()").get()
        if not emenda:
            # fallback: pega o texto do <p class="ui sub header">
            emenda = response.css("p.ui.sub.header::text").get()

        if emenda:
            # remove número de protocolo no início
            emenda = re.sub(r"^\s*\d+\.\d+/\d{4}-\d+\s*-?\s*", "", emenda).strip()
            item["emenda"] = emenda
        else:
            item["emenda"] = "Sem dados informados"




        # Assuntos
        subjects = response.css("dl.dados dt:contains('Assunto') + dd::text").get()
        if subjects:
            item["subject"] = [s.strip() for s in subjects.split(",")]
        else:
            # garante que o campo exista, mesmo sem assunto
            item["subject"] = ["Sem dados informados"]

        # Data de apresentação
        data_abertura = response.css("dl.dados dt:contains('Data da Abertura') + dd::text").get()
        if data_abertura:
            try:
                dt = datetime.strptime(data_abertura.strip(), "%d/%m/%Y")
                item["presentation_date"] = dt.strftime("%Y-%m-%d")
            except:
                item["presentation_date"] = data_abertura.strip()

        # Status / tramitações
        status = []
        for tr in response.css("div[data-tab=tramitacoes] table tbody tr"):
            cols = tr.css("td::text").getall()
            if len(cols) >= 4:
                data_raw = cols[1].strip()
                data_iso = None
                try:
                    dt = datetime.strptime(data_raw, "%d/%m/%Y")
                    data_iso = dt.strftime("%Y-%m-%d")
                except:
                    data_iso = data_raw
                status.append({
                    "descricao": cols[3].strip(),
                    "data": data_iso
                })
        item["status"] = status

        # PDF principal
        pdf_url = None
        for a in response.css("div[data-tab=documentos] a[target=_blank]::attr(href)").getall():
            if a.lower().endswith(".pdf"):
                pdf_url = response.urljoin(a)
                break

        if pdf_url:
            item["url"] = pdf_url
            item["file_urls"] = [pdf_url]
            if "year" in item and "number" in item:
                item["pdf_files"] = [
                    f"{self.slug}/pdf/{item['year']}/projeto-de-lei-{item['number']}-{item['year']}.pdf"
                ]
                item["md_files"] = f"{self.uf}/{self.slug}/projeto-de-lei-{item['number']}-{item['year']}.md"
        else:
            # fallback: usa o link da proposição
            item["url"] = link
            item["file_urls"] = []
            item["pdf_files"] = []
            item["md_files"] = f"{self.uf}/{self.slug}/projeto-de-lei-{item['number']}-{item['year']}.md"


        yield item