import scrapy
import re
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from ..items import ProposicaoItem


class ProposicoesCIDRJSpider(scrapy.Spider):
    """
    Spider para coleta de proposições da Câmara Municipal do Rio de Janeiro.
    Segue o padrão: só gera item_bruto.
    """

    name = "proposicoescidrj"
    slug = "proposicoescidrj"
    casa_legislativa = "Câmara Municipal do Rio de Janeiro"
    uf = "RJ"
    esfera = "MUNICIPAL"
    municipio = "Rio de Janeiro"

    allowed_domains = ["aplicnt.camara.rj.gov.br"]
    start_urls = [
        "https://aplicnt.camara.rj.gov.br/APL/Legislativos/scpro.nsf/Internet/LeiInt?OpenForm"
    ]
    custom_settings = {"ROBOTSTXT_OBEY": False}

    def __init__(self, data_inicio=None, data_fim=None, limite=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_inicio = self._validar_data(data_inicio)
        self.data_fim = self._validar_data(data_fim)
        self.limite_total_itens = int(limite) if limite else None
        self.itens_processados = 0

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")
        linhas = soup.select('table[cellpadding="2"] tr[valign="top"]')

        for linha in linhas:
            if self.limite_total_itens and self.itens_processados >= self.limite_total_itens:
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

            ementa_bruta = cols[3].get_text(strip=True)
            data_publicacao = cols[4].get_text(strip=True)
            autores_bruto = cols[5].get_text(strip=True)

            # Normaliza a data já no spider
            data_obj = self._parse_data(data_publicacao)  # datetime ou None
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
            item["titulo_bruto"] = f"Projeto de Lei {numero}/{ano}"
            item["tipo_bruto"] = "Projeto de Lei"
            item["numero_bruto"] = numero
            item["ano_bruto"] = ano
            item["ementa_bruto"] = ementa_bruta.split("=>")[0].split("AUTOR:")[0].strip()
            item["autores_bruto"] = [a.strip() for a in autores_bruto.split(",") if a.strip()]
            item["data_documento_bruto"] = data_fmt
            item["casa_legislativa_bruto"] = self.casa_legislativa
            item["data_raspagem_bruto"] = datetime.now().isoformat()
            item["uf_bruto"] = self.uf
            item["municipio_bruto"] = self.municipio
            item["slug_bruto"] = self.slug
            item["uuid"] = hashlib.md5(url_detalhes.encode("utf-8")).hexdigest()

            self.itens_processados += 1
            yield scrapy.Request(url_detalhes, callback=self.parse_detalhes, meta={"item": item})

    def parse_detalhes(self, response):
        item = response.meta["item"]
        soup = BeautifulSoup(response.text, "html.parser")

        # --- CAPTURA DA DATA NO DETALHE ---
        if not item.get("data_documento_bruto"):
            data_detalhe = soup.find(string=re.compile(r"\d{1,2}/\d{1,2}/\d{4}"))
            if data_detalhe:
                item["data_documento_bruto"] = data_detalhe.strip()

        # Converte para dict para poder adicionar campos extras sem erro
        item_dict = dict(item)

        # Nome base padronizado
        numero = item.get("numero_bruto")
        ano = item.get("ano_bruto")
        tipo = item.get("tipo_bruto", "projeto-de-lei").lower().replace(" ", "-")

        item_dict = dict(item)
        if numero and ano:
            nome_arquivo = f"{tipo}-{numero}-{ano}"
        else:
            nome_arquivo = "sem-identificacao"

        caminho_base = f"rj/rio-de-janeiro/{self.slug}/{nome_arquivo}"

        # PDF (se existir)
        pdf_link_tag = soup.find("a", href=lambda href: href and ".pdf" in href.lower())
        if pdf_link_tag:
            url_pdf = response.urljoin(pdf_link_tag["href"])
            item_dict["url_documento_original"] = url_pdf
            item_dict["file_urls"] = [url_pdf]
            item_dict["caminho_arquivo_original"] = f"{caminho_base}.pdf"
        else:
            item_dict["url_documento_original"] = None
            item_dict["file_urls"] = []
            item_dict["caminho_arquivo_original"] = None


        # Markdown
        item_dict["caminho_arquivo_texto"] = f"md/{caminho_base}.md"

        # Tramitação
        status_bruto = []
        tramitacao_header = soup.find("font", string=re.compile("TRAMITAÇÃO DO PROJETO"))
        if tramitacao_header:
            tabela_tramitacao = tramitacao_header.find_next("table")
            if tabela_tramitacao:
                trs = tabela_tramitacao.find_all("tr")[1:]  # ignora cabeçalho
                for tr in trs[-3:]:  # pega últimos 3
                    descricao = " ".join(td.get_text(strip=True) for td in tr.find_all("td")).strip()
                    data_status = None
                    data_match = re.search(r"(\d{2}/\d{2}/\d{4})", descricao)
                    if data_match:
                        data_status = self._formatar_data(data_match.group(1))
                    if descricao:
                        status_bruto.append({"descricao": descricao, "data": data_status})
        item_dict["status_bruto"] = self.limpar_status(status_bruto)

        # Conteúdo em Markdown
        div_texto_inicial = soup.find("div", id="xSec2")
        item_dict["conteudo_markdown"] = self._limpar_html_para_markdown(div_texto_inicial)

        # Ajusta data do documento para ISO
        item_dict["data_documento"] = item.get("data_documento_bruto")
        yield item_dict

    # --- FUNÇÕES AUXILIARES ---
    def _formatar_data(self, data_texto):
        """Converte dd/mm/yyyy para YYYY-MM-DD"""
        if not data_texto:
            return None
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

    def limpar_status(self, status_bruto):
        status_list = []
        for status in status_bruto[1:]:
            descricao = status.get("descricao", "").strip()
            data = status.get("data", None)
            if "=>" in descricao:
                descricao = descricao.split("=>")[0].strip()
            descricao = re.sub(r"\s+", " ", descricao)
            status_list.append({"descricao": descricao, "data": data})
        return status_list

    def _parse_data(self, data_texto):
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), "%d/%m/%Y")
        except ValueError:
            return None

    def _limpar_html_para_markdown(self, div_conteudo):
        if not div_conteudo:
            return "Conteúdo não encontrado."

        # Quebra de linha
        for br in div_conteudo.find_all("br"):
            br.replace_with("\n")

        # Negrito: <b> e <strong>
        for tag in div_conteudo.find_all(["b", "strong"]):
            content = tag.get_text(strip=True)
            if content:
                tag.replace_with(f"**{content}**")

        # Sublinhado vira negrito (para não perder destaque)
        for tag in div_conteudo.find_all("u"):
            content = tag.get_text(strip=True)
            if content:
                tag.replace_with(f"**{content}**")

        # Cabeçalhos comuns (se existirem)
        for h_tag, prefix in [("h1", "# "), ("h2", "## "), ("h3", "### ")]:
            for tag in div_conteudo.find_all(h_tag):
                content = tag.get_text(strip=True)
                if content:
                    tag.replace_with(f"{prefix}{content}\n")

        # Listas simples (transforma <li> em linha com "- ")
        for li in div_conteudo.find_all("li"):
            content = li.get_text(" ", strip=True)
            if content:
                li.replace_with(f"- {content}\n")

        # Links: [texto](url), ignorando javascript:
        for a in div_conteudo.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href")
            if href and not href.lower().startswith("javascript:"):
                a.replace_with(f"[{text}]({href})")
            else:
                a.replace_with(text)


        # Remove scripts e estilos
        for tag in div_conteudo.find_all(["script", "style"]):
            tag.decompose()

        # Extrai texto com quebras
        texto = div_conteudo.get_text(separator="\n", strip=True)

        # Normalizações
        texto = re.sub(r"[ \t]+", " ", texto)         # espaços múltiplos -> 1
        texto = re.sub(r"\n{3,}", "\n\n", texto)      # >2 quebras -> 2
        texto = re.sub(r"\s+\n", "\n", texto)         # espaço antes de \n
        texto = re.sub(r"\n\s+", "\n", texto)         # espaço depois de \n

        return texto.strip()
