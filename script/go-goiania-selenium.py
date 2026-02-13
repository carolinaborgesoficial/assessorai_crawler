import os
import re
import json
import time
import argparse
import hashlib
import unicodedata
import requests
import logging

from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("go-goiania-selenium")


# ================= ARGUMENTOS =================

parser = argparse.ArgumentParser()
parser.add_argument("--year", required=True)
parser.add_argument("--limit", type=int)
args = parser.parse_args()

YEAR = args.year
LIMIT = args.limit


# ================= CONFIG =================

BASE_URL = (
    "https://suap.camaragyn.go.gov.br/camara/consulta_publica/"
    f"?classificacao=PL&assunto=projeto+de+lei&ano={YEAR}"
)
BASE_DOMAIN = "https://suap.camaragyn.go.gov.br"

UF = "GO"
SLUG = "go-goiania"
HOUSE = "Câmara Municipal de Goiânia"

OUTPUT_JSON = f"{SLUG}-{YEAR}.json"
PDF_DIR = os.path.join(SLUG, "pdf", YEAR)
os.makedirs(PDF_DIR, exist_ok=True)

logger.info("Iniciando coleta Goiânia")
logger.info("Ano: %s | Limite: %s", YEAR, LIMIT or "sem limite")
logger.info("URL base: %s", BASE_URL)


# ================= UTILITÁRIOS =================

def clean_subject(text):
    """Limpa a ementa do projeto removendo ruídos de sistema."""
    if not text:
        return ""

    # 1. Remove "X" ou quebras de linha no início
    text = re.sub(r"^[X\s\n\r]+", "", text)

    # 2. Remove prefixos repetitivos (ex: Projeto de Lei nº 123/2024 -)
    text = re.sub(
        r"^(?:P\s*\.?\s*[ELC O]+\s*\.?|Projeto de [^-\n>:]+)\s*"
        r"(?:n[ºo°.]?)?\s*[\d\s]+/[\d\s]+[-–—>:]\s*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 3. Corta o texto apenas em marcadores de fim de ementa (Processo ou Autoria)
    # Removido "PROJETO DE" do split para não cortar ementas de emendas ao meio.
    text = re.split(
        r"Processo\s*:|Autoria\s*:",
        text,
        flags=re.IGNORECASE,
    )[0]

    return text.strip().replace("\n", " ")


def slugify(text: str) -> str:
    """Cria um nome de arquivo amigável a partir de um texto."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower())
    return text.strip("-")


def identificar_tipo(text):
    """Identifica o tipo de proposição e extrai número e ano."""
    txt = text.upper()
    if "LEI COMPLEMENTAR" in txt:
        tipo = "Projeto de Lei Complementar"
    elif "EMENDA À LEI ORGÂNICA" in txt:
        tipo = "Projeto de Emenda à Lei Orgânica"
    elif "PROJETO DE LEI" in txt:
        tipo = "Projeto de Lei"
    else:
        return None, None, None

    m = re.search(r"(\d+)\s*/\s*(\d{4})", txt)
    if not m:
        return None, None, None

    return tipo, m.group(1), m.group(2)


# ================= BROWSER SETUP =================

options = Options()
options.add_argument("--start-maximized")
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--remote-allow-origins=*")
options.add_argument("--blink-settings=imagesEnabled=false")

driver = webdriver.Chrome(options=options)
session = requests.Session()
driver.get(BASE_URL)

items = []
count = 0

# ================= LOOP DE COLETA =================

while True:
    logger.info("Processando nova página de resultados")
    
    # Tenta esperar os cards carregarem (Trata anos vazios sem quebrar o script)
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.general-box")))
    except:
        logger.warning(f"Nenhum projeto encontrado para o ano {YEAR} ou fim da lista atingido.")
        break

    cards = driver.find_elements(By.CSS_SELECTOR, "div.general-box")
    main_window = driver.current_window_handle 

    # --- PASSO 1: Extrair dados da lista primeiro (Garante estabilidade da sessão) ---
    projetos_da_pagina = []
    for card in cards:
        try:
            url = card.find_element(By.CSS_SELECTOR, "h3.title a").get_attribute("href")
            raw = card.find_element(By.CSS_SELECTOR, "div.extra-info dd").text.strip()
            
            # Coleta o Status diretamente no card (mais confiável)
            status_list = [{"descricao": s.text.strip(), "data": None}
                          for s in card.find_elements(By.CSS_SELECTOR, "div.status-info span.status")
                          if s.text.strip()]
            
            authors = []
            presentation_date = None
            for dl in card.find_elements(By.CSS_SELECTOR, "dl.secondary-info div.list-item"):
                dt = dl.find_element(By.TAG_NAME, "dt").text
                dd = dl.find_element(By.TAG_NAME, "dd").text.strip()
                if "Interessados" in dt: authors = [a.strip() for a in dd.split(",")]
                if "Data de criação" in dt:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", dd)
                    if m: presentation_date = datetime.strptime(m.group(0), "%d/%m/%Y").strftime("%Y-%m-%d")

            projetos_da_pagina.append({
                "url": url, 
                "subject_raw": raw,
                "authors": authors,
                "presentation_date": presentation_date,
                "status": status_list
            })
        except:
            continue

    # --- PASSO 2: Processar detalhes e baixar PDFs ---
    for p in projetos_da_pagina:
        if LIMIT and count >= LIMIT:
            break
        
        tipo, numero, ano = identificar_tipo(p['subject_raw'])
        if not tipo or ano != YEAR:
            continue

        subject = clean_subject(p['subject_raw'])
        title = f"{tipo} nº {numero}/{ano}"
        slug_title = slugify(f"{tipo}-{numero}-{ano}")
        uuid = hashlib.md5(p['url'].encode()).hexdigest()

        logger.info(f"Processando {tipo} nº {numero}/{ano}")

        # ===== ACESSA PÁGINA DO PROCESSO (Nova Aba) =====
        pdf_url = None
        try:
            driver.execute_script("window.open(arguments[0], '_blank');", p['url'])
            driver.switch_to.window(driver.window_handles[1])
            
            # Espera o carregamento do visualizador de PDF (Timeout de 25s para arquivos pesados)
            wait = WebDriverWait(driver, 25)
            iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='visualizar_documento_digitalizado']")))
            iframe_src = iframe.get_attribute("src")
            pdf_url = BASE_DOMAIN + iframe_src if iframe_src.startswith("/") else iframe_src
        except Exception:
            logger.warning(f"Não foi possível capturar o PDF do processo {numero}. Pulando...")
        
        # Fecha aba de detalhes e retorna para a lista principal
        if len(driver.window_handles) > 1:
            driver.close()
        driver.switch_to.window(main_window)

        if not pdf_url:
            continue

        # ===== DOWNLOAD DO ARQUIVO PDF =====
        logger.info("Baixando PDF: %s", pdf_url)
        pdf_path = os.path.join(PDF_DIR, f"{slug_title}.pdf")
        headers = {"User-Agent": driver.execute_script("return navigator.userAgent"), "Referer": p['url']}

        try:
            r = session.get(pdf_url, headers=headers, timeout=30)
            if r.status_code == 200 and r.content.startswith(b"%PDF"):
                with open(pdf_path, "wb") as f:
                    f.write(r.content)
                    logger.info("PDF salvo com sucesso")
            else:
                logger.warning(f"Falha no download do PDF. Status: {r.status_code}")
        except Exception as e:
            logger.error(f"Erro na requisição do PDF: {e}")

        # ===== MONTAGEM DO OBJETO FINAL =====
        item = {
            "uuid": uuid,
            "type": tipo,
            "project_url": p['url'],
            "house": HOUSE,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "number": numero,
            "year": ano,
            "title": title,
            "author": p['authors'],
            "emenda": None,
            "subject": [subject] if subject else [],
            "presentation_date": p['presentation_date'],
            "status": p['status'],
            "url": pdf_url,
            "file_urls": [pdf_url],
            "pdf_files": [f"{SLUG}/pdf/{YEAR}/{slug_title}.pdf"],
            "md_files": f"{UF}/{SLUG}/{slug_title}.md",
        }

        items.append(item)
        count += 1
        logger.info("Item %d coletado com sucesso", count)

    # --- PAGINAÇÃO ---
    if LIMIT and count >= LIMIT:
        break

    try:
        logger.info("Navegando para a próxima página")
        next_btn = driver.find_element(By.CSS_SELECTOR, "ul.pagination li.next a")
        driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(5) # Tempo de segurança para carregamento da nova lista
    except:
        logger.info("Fim da paginação ou botão 'Próximo' não encontrado.")
        break

# ================= EXPORTAÇÃO DOS DADOS =================

with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

logger.info("Total de registros coletados: %d", len(items))
logger.info("Arquivo JSON gerado: %s", OUTPUT_JSON)

driver.quit()