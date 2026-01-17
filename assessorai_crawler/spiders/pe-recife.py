import scrapy
import hashlib
import unicodedata
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlencode
from bs4 import BeautifulSoup
from ..items import ProposicaoItem

BASE = "https://e-processo.recife.pe.leg.br"


def slugify(text: str) -> str:
    if not text:
        return "unknown"
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower())
    return text.strip("-")


class PeRecifeSpider(scrapy.Spider):
    name = "pe-recife"
    house = "Câmara Municipal do Recife"
    uf = "PE"
    slug = "pe-recife"
    allowed_domains = ["e-processo.recife.pe.leg.br"]

    def __init__(self, year=None, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = year
        self.limit = int(limit) if limit else None
        self.items_count = 0

        self.logger.info(f"Ano: {self.year}")
        if self.limit:
            self.logger.info(f"Limite ativo: {self.limit}")

        self.base_params = {
            "lst_tip_materia": [14, 28, 10, 11],
            "txt_numero": "",
            "txt_ano": self.year,
            "txt_num_protocolo": "",
            "txt_num_processo": "",
            "dt_apres": "",
            "dt_apres2": "",
            "hdn_cod_autor": "",
            "txt_assunto": "",
            "lst_tramitou": "",
            "lst_localizacao": "",
            "lst_status": "",
            "rad_tramitando": "",
            "rd_ordenacao": 1,
            "incluir": "",
            "existe_ocorrencia": 0,
            "txt_relator": "",
            "lst_cod_partido": "",
            "lst_tip_autor": "",
            "hdn_txt_autor": "",
            "chk_coautor": "",
            "dt_public": "",
            "dt_public2": "",
        }

    def start_requests(self):
        params = self.base_params | {"page": 1, "step": 10}
        url = (
            f"{BASE}/consultas/materia/materia_pesquisar_proc?"
            f"{urlencode(params, doseq=True)}"
        )
        yield scrapy.Request(url, callback=self.parse, meta={"page": 1})

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")
        itens = soup.select("ul.list-group.list-group-flush li.list-group-item")

        current_page = response.meta["page"]
        self.logger.info(f"Página {current_page} | Itens: {len(itens)}")

        if not itens:
            self.logger.info("Nenhum item encontrado. Encerrando spider.")
            return

        for li in itens:
            if self.limit and self.items_count >= self.limit:
                self.logger.info("Limite atingido. Encerrando spider.")
                return

            item = self.parse_item(li)
            if item:
                self.items_count += 1
                yield item

        # === critério de parada: só continua se existir link para a PRÓXIMA página ===
        next_page_str = f"page={current_page + 1}"
        has_next = soup.select_one(
            f"ul.pagination a.page-link[href*='{next_page_str}']"
        )

        if not has_next:
            self.logger.info(
                f"Página {current_page} é a última. Encerrando paginação."
            )
            return

        next_page = current_page + 1
        params = self.base_params | {"page": next_page, "step": 10}
        next_url = (
            f"{BASE}/consultas/materia/materia_pesquisar_proc?"
            f"{urlencode(params, doseq=True)}"
        )

        yield scrapy.Request(
            next_url,
            callback=self.parse,
            meta={"page": next_page},
        )

    def parse_item(self, li):
        title_el = li.select_one("span.h6")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)

        raw_type, number, year = "", "", ""
        if "nº" in title:
            before, after = title.split("nº", 1)
            raw_type = before.strip()
            number, year = after.strip().split("/", 1)

        TYPE_MAP = {
            "Projeto de Lei Ordinária": "PL",
            "Projeto de Emenda à Lei Orgânica": "PLO",
            "Projeto de Lei Complementar": "PLC",
            "Projeto de Lei do Executivo": "PLE"
        }

        doc_type = TYPE_MAP.get(raw_type, slugify(raw_type))

        subject = (
            li.find("p")
            .get_text(strip=True)
            .replace("Ementa:", "")
            .strip()
        )

        authors = []
        for b in li.find_all("b"):
            if "Autoria:" in b.get_text():
                authors.append(b.next_sibling.strip())
                break

        presentation_date = ""
        for b in li.find_all("b"):
            if "Data de Apresentação:" in b.get_text():
                presentation_date = datetime.strptime(
                    b.next_sibling.strip(), "%d/%m/%Y"
                ).strftime("%Y-%m-%d")
                break

        file_urls = []
        project_url = ""

        pdf = li.select_one("a[href*='download_materia']")
        if pdf:
            pdf_url = urljoin(BASE, pdf["href"])
            file_urls.append(pdf_url)

            m = re.search(r"cod_materia=([^&]+)", pdf["href"])
            if m:
                project_url = (
                    f"{BASE}/consultas/materia/materia_mostrar_proc"
                    f"?cod_materia={m.group(1)}"
                )

        status_list = []
        for row in li.select("div.row"):
            col = row.select_one("div.col-12")
            if not col:
                continue

            b = col.find("b")
            if not b:
                continue

            label = b.get_text(strip=True)
            text = col.get_text(" ", strip=True)

            if label.startswith("Localização Atual"):
                valor = text.replace(label, "").strip(": ").strip()
                status_list.append(
                    {"descricao": f"Localização Atual: {valor}", "data": ""}
                )

            elif label.startswith("Situação em"):
                m = re.search(r"(\d{2}/\d{2}/\d{4})", label)
                data_fmt = ""
                if m:
                    data_fmt = datetime.strptime(
                        m.group(1), "%d/%m/%Y"
                    ).strftime("%Y-%m-%d")

                status_list.append({"descricao": text, "data": data_fmt})

                for p in col.select("div.tram_mat p"):
                    t = p.get_text(strip=True)
                    if not t:
                        continue
                    datas = re.findall(r"\d{2}/\d{2}/\d{4}", t)
                    d = ""
                    if datas:
                        d = datetime.strptime(
                            datas[-1], "%d/%m/%Y"
                        ).strftime("%Y-%m-%d")
                    status_list.append({"descricao": t, "data": d})

        item = ProposicaoItem()
        item["uuid"] = hashlib.md5(
            f"{doc_type}-{number}-{year}".encode()
        ).hexdigest()
        item["type"] = doc_type
        item["number"] = number
        item["year"] = year
        item["title"] = title
        item["subject"] = subject
        item["presentation_date"] = presentation_date
        item["author"] = authors
        item["house"] = self.house
        item["scraped_at"] = datetime.now(timezone.utc).isoformat()
        item["url"] = project_url
        item["project_url"] = project_url
        item["file_urls"] = file_urls

        tipo_slug = slugify(doc_type)

        item["pdf_files"] = [
            f"{self.slug}/pdf/{year}/{tipo_slug}-{number}-{year}.pdf"
        ]

        item["md_files"] = (
            f"{self.uf}/{self.slug}/{tipo_slug}-{number}-{year}.md"
        )

        item["status"] = status_list

        return item
