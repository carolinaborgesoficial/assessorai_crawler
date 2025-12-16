import json
import time
import os
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ReportLab para PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY


# Converter data para ISO
def normalizar_data(data_str):
    try:
        # tenta dd/mm/yyyy hh:mm
        dt = datetime.strptime(data_str, "%d/%m/%Y %H:%M")
        return dt.strftime("%Y-%m-%d")
    except:
        try:
            # tenta dd/mm/yyyy
            dt = datetime.strptime(data_str, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        except:
            return None

def salvar_pdf(codigo, ano, dados, ementa, texto, justificativa, mensagem=""):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Titulo", fontSize=16, alignment=TA_CENTER,
                              spaceAfter=12, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="SubTitulo", fontSize=14, alignment=TA_CENTER,
                              spaceAfter=12, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="ProjetoLei", fontSize=14, alignment=TA_CENTER,
                              spaceBefore=24, spaceAfter=12, fontName="Helvetica-Bold"))  # mais espaço antes
    styles.add(ParagraphStyle(name="Corpo", fontSize=12, leading=18,
                              alignment=TA_JUSTIFY, firstLineIndent=20))  # espaçamento 1,5
    styles.add(ParagraphStyle(name="Ementa", fontSize=12, leading=18,
                              alignment=TA_JUSTIFY, leftIndent=200))  # começa no meio da página
    styles.add(ParagraphStyle(name="JustificativaTitulo", fontSize=12, alignment=TA_CENTER,
                              spaceBefore=12, spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="AssinaturaNome", fontSize=12, alignment=TA_CENTER,
                              fontName="Helvetica-Bold", spaceBefore=12))
    styles.add(ParagraphStyle(name="AssinaturaCargo", fontSize=12, alignment=TA_CENTER,
                              spaceAfter=12))

    pasta = f"pr-curitiba/pdf/{ano}"
    os.makedirs(pasta, exist_ok=True)
    filename = f"{pasta}/pl-{codigo.replace('.','-')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    story = []
    # Cabeçalho
    story.append(Paragraph("Câmara Municipal de Curitiba", styles["Titulo"]))
    story.append(Paragraph(f"PROPOSIÇÃO Nº {codigo}", styles["SubTitulo"]))
    story.append(Spacer(1, 12))

    # Intro
    autor = dados.get("Iniciativa", "")
    tipo = dados.get("Tipo", "")
    if autor or tipo:
        intro = f"O {autor}, no uso de suas atribuições legais, submete à apreciação da Câmara Municipal de Curitiba a seguinte proposição:"
        story.append(Paragraph(intro, styles["Corpo"]))
        if tipo:
            story.append(Paragraph(tipo, styles["ProjetoLei"]))  # centralizado e negrito
    story.append(Spacer(1, 12))

    # Ementa
    if ementa:
        story.append(Paragraph("EMENTA", styles["Ementa"]))  # título centralizado e negrito
        story.append(Paragraph(ementa, styles["Ementa"]))  # conteúdo indentado, sem negrito
        story.append(Spacer(1, 12))


    # Texto da Lei (sem título)
    if texto:
        for linha in texto.split("\n"):
            if linha.strip():
                story.append(Paragraph(linha.strip(), styles["Corpo"]))
        story.append(Spacer(1, 12))

    # Assinatura - pode haver mais de um vereador
    autores = dados.get("Iniciativa", "")
    if autores:
        nomes = [nome.strip() for nome in autores.split(",") if nome.strip()]
        if len(nomes) == 1:
            # Apenas um vereador
            story.append(Paragraph(nomes[0], styles["AssinaturaNome"]))
            story.append(Paragraph("Vereador", styles["AssinaturaCargo"]))
        else:
            # Mais de um vereador: lado a lado
            from reportlab.platypus import Table, TableStyle
            tabela = []
            linha_nomes = [Paragraph(nome, styles["AssinaturaNome"]) for nome in nomes]
            linha_cargos = [Paragraph("Vereador", styles["AssinaturaCargo"]) for _ in nomes]
            tabela.append(linha_nomes)
            tabela.append(linha_cargos)
            t = Table(tabela, hAlign="CENTER")
            t.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER")]))
            story.append(t)
        story.append(Spacer(1, 12))


    # Justificativa
    if justificativa:
        story.append(Paragraph("JUSTIFICATIVA", styles["JustificativaTitulo"]))
        for linha in justificativa.split("\n"):
            if linha.strip():
                story.append(Paragraph(linha.strip(), styles["Corpo"]))
        story.append(Spacer(1, 12))

    # Mensagem
    if mensagem:
        story.append(Paragraph("MENSAGEM", styles["JustificativaTitulo"]))
        for linha in mensagem.split("\n"):
            if linha.strip():
                story.append(Paragraph(linha.strip(), styles["Corpo"]))

    doc.build(story)
    return filename


# Selenium setup
options = Options()
options.add_argument("--start-maximized")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Página inicial
url = "https://www.cmc.pr.gov.br/wspl/relatorios/ProposicaoConsultaResultadoForm.jsp"
driver.get(url)

input("Resolva o captcha no navegador e pressione ENTER aqui para continuar...")

# Coletar links de todas as páginas
all_urls = []
offset = 0
while True:
    page_url = f"https://www.cmc.pr.gov.br/wspl/sistema/ProposicaoConsultaResultadoForm.jsp?bl_report_Proposicoes_consulta.offset={offset}&pesquisa="
    driver.get(page_url)
    time.sleep(2)

    links = driver.find_elements(By.XPATH, "//a[contains(@href,'pro_id=')]")
    if not links:
        break

    page_urls = [link.get_attribute("href") for link in links]
    all_urls.extend(page_urls)

    offset += 25

print(f"Total de links coletados: {len(all_urls)}")

proposicoes = []

for u in all_urls:
    if "pro_id=" in u:
        # aqui continua o processamento normal

        pro_id = u.split("pro_id=")[1].split("&")[0]
        detalhe_url = f"https://www.cmc.pr.gov.br/wspl/relatorios/ProposicaoDetalhesTudoReport.do?select_action=&pro_id={pro_id}"

        driver.get(detalhe_url)
        time.sleep(2)

        # Metadados
        labels = driver.find_elements(By.CLASS_NAME, "formLabel")
        fields = driver.find_elements(By.CLASS_NAME, "formField")

        dados = {}
        for i in range(min(len(labels), len(fields))):
            chave = labels[i].text.strip().replace(":", "")
            valor = fields[i].text.strip()
            dados[chave] = valor

        # Ementa
        try:
            ementa = driver.find_element(
                By.XPATH,
                "//span[normalize-space(text())='Ementa:']/ancestor::tr/following-sibling::tr[1]//div"
            ).text.strip()
        except:
            ementa = ""

        # Texto da Lei
        try:
            texto = driver.find_element(
                By.XPATH,
                "//span[normalize-space(text())='Texto:']/ancestor::tr/following-sibling::tr[1]//div"
            ).text.strip()
        except:
            texto = ""

        # Justificativa ou Mensagem
        try:
            justificativa = driver.find_element(
                By.XPATH,
                "//span[contains(normalize-space(text()),'Justificativa')]/ancestor::tr/following-sibling::tr[1]//div"
            ).text.strip()
        except:
            justificativa = ""

        codigo = dados.get("Código", "")
        numero = codigo.split(".")[1] if codigo else ""
        ano = codigo.split(".")[-1] if codigo else ""

        # Gerar PDF
        pdf_filename = salvar_pdf(codigo, ano, dados, ementa, texto, justificativa)

        # JSON
        proposicao = {
            "number": numero,
            "year": ano,
            "type": dados.get("Tipo", ""),
            "title": f"{dados.get('Tipo', '')} nº {numero}/{ano}" if numero and ano else f"{dados.get('Tipo', '')} nº {codigo}",
            "subject": ementa,
            "presentation_date": normalizar_data(dados.get("Data de envio ao protocolo", "")),
            "author": [{"nome": nome.strip()} for nome in dados.get("Iniciativa", "").split(",") if nome.strip()],
            "url": detalhe_url,
            "file_urls": [pdf_filename],
            "house": "Câmara Municipal de Curitiba",
            "scraped_at": datetime.now().isoformat(),
            "uuid": f"curitiba-{pro_id}",
            "project_url": u,
            "md_files": f"PR/curitiba/{(dados.get('Tipo','') or 'projeto').lower().replace(' ','-')}-{numero}-{ano}.md",
            "status": [
                {"descricao": f"Localização Atual: {dados.get('Localização','')}", "data": None},
                {"descricao": f"Status: {dados.get('Estado','')}", "data": None},
                {"descricao": "Data da última Tramitação", "data": normalizar_data(dados.get("Último trâmite",""))}
            ]
        }

        proposicoes.append(proposicao)

# Salvar em JSON
with open("proposicoes_curitiba.json", "w", encoding="utf-8") as f:
    json.dump(proposicoes, f, ensure_ascii=False, indent=2)

driver.quit()


