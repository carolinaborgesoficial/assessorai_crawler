import os
import re
import json
import time
import uuid
import argparse
import requests
from datetime import datetime
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager


# ========= ARGUMENTOS =========
parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
ITEM_LIMIT = args.limit


# ========= CONFIG =========
ENTRY_URL = "http://190.15.122.10:8080/sapl/default_index_html"

BASE_DIR = "se/aracaju"
FILES_DIR = os.path.join(BASE_DIR, "pdf")

PAGE_SLEEP = 1.5
ITEM_SLEEP = 0.3

os.makedirs(FILES_DIR, exist_ok=True)


# ========= UTIL =========
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_session(driver):
    s = requests.Session()
    for c in driver.get_cookies():
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"))
    return s


def extrair_data(texto):
    if not texto:
        return None
    m = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")


def slug_tipo(tipo):
    return (
        tipo.lower()
        .replace("á", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("ç", "c")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("ú", "u")
        .replace(" ", "-")
    )


def detectar_extensao(response):
    ct = response.headers.get("Content-Type", "").lower()
    if "pdf" in ct:
        return "pdf"
    if "officedocument" in ct:
        return "docx"
    if "msword" in ct:
        return "doc"
    return "bin"


def download_file(session, url, tipo, number, year):
    r = session.get(url, timeout=120)
    if r.status_code != 200:
        return None

    ext = detectar_extensao(r)

    ano_dir = os.path.join(FILES_DIR, year)
    os.makedirs(ano_dir, exist_ok=True)

    filename = f"{slug_tipo(tipo)}-{number}-{year}.{ext}"
    path = os.path.join(ano_dir, filename)

    with open(path, "wb") as f:
        f.write(r.content)

    return path.replace("\\", "/")


def extrair_status(html):
    soup = BeautifulSoup(html, "html.parser")
    status = []

    for b in soup.find_all("b"):
        label = b.get_text(strip=True)

        texto = ""
        if b.next_sibling:
            texto = b.next_sibling.strip()

        if label.startswith("Localização Atual"):
            status.append({
                "descricao": f"Localização Atual: {texto}",
                "data": None
            })

        elif label.startswith("Situação"):
            status.append({
                "descricao": f"Situação: {texto}",
                "data": None
            })

        elif label.startswith("Última Ação"):
            bloco = b.parent.get_text(" ", strip=True)
            data = extrair_data(bloco)

            descricao = re.sub(r"Em:\s*\d{2}/\d{2}/\d{4}", "", bloco)
            descricao = descricao.replace("Última Ação:", "").strip()

            status.append({
                "descricao": f"Última Ação: {descricao}",
                "data": data
            })

    return status


# ========= MAIN =========
def main():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    collected = 0

    try:
        driver.get(ENTRY_URL)

        log("NAVEGAÇÃO MANUAL OBRIGATÓRIA:")
        log("Menu → Matérias Legislativas → Pesquisar Matéria")
        input("Quando a LISTA aparecer, pressione ENTER...")

        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located(
                (By.XPATH, "//a[contains(@href,'materia_mostrar_proc')]")
            )
        )

        # Descobrir o ANO
        first_title = driver.find_element(
            By.XPATH, "//a[contains(@href,'materia_mostrar_proc')]/b"
        ).text
        year = re.search(r"/(\d{4})", first_title).group(1)

        json_path = os.path.join(BASE_DIR, f"aracaju{year}.json")

        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []

        existing_urls = {
            item["project_url"]
            for item in data
            if item.get("project_url")
        }

        session = get_session(driver)
        page = 1

        while True:
            log(f">>> Página {page}")

            rows = driver.find_elements(
                By.XPATH, "//tr[.//a[contains(@href,'materia_mostrar_proc')]]"
            )

            for row in rows:
                if ITEM_LIMIT and collected >= ITEM_LIMIT:
                    log("Limite atingido.")
                    return

                try:
                    html = row.get_attribute("innerHTML")

                    title = re.search(r"<b>(.*?)</b>", html).group(1).strip()
                    nm = re.search(r"(\d+)/(\d{4})", title)
                    number, year = nm.groups()

                    tipo = title.split(" - ")[-1]

                    parts = re.split(r"<br\s*/?>", html)
                    subject = re.sub(r"<.*?>", "", parts[1]).strip()

                    ma = re.search(r"<b>Autor:</b>\s*(.*?)<br>", html, re.S)
                    author = [ma.group(1).strip()] if ma else []

                    presentation_date = extrair_data(html)

                    project_url = row.find_element(
                        By.XPATH, ".//a[contains(@href,'materia_mostrar_proc')]"
                    ).get_attribute("href")

                    file_url = None
                    try:
                        file_url = row.find_element(
                            By.XPATH, ".//a[contains(@href,'texto_integral')]"
                        ).get_attribute("href")
                    except:
                        pass

                    saved_path = None
                    if file_url:
                        saved_path = download_file(
                            session, file_url, tipo, number, year
                        )
                        if saved_path:
                            collected += 1
                            log(f"Arquivo {collected}: {title}")

                    item = {
                        "number": number,
                        "year": year,
                        "type": tipo,
                        "title": title,
                        "subject": subject,
                        "presentation_date": presentation_date,
                        "author": author,
                        "url": file_url,
                        "file_urls": [file_url] if file_url else [],
                        "house": "Câmara Municipal de Aracaju",
                        "scraped_at": datetime.now().isoformat(),
                        "uuid": uuid.uuid4().hex,
                        "project_url": project_url,
                        "md_files": f"se/aracaju/{slug_tipo(tipo)}-{number}-{year}.md",
                        "status": extrair_status(html),
                        "pdf_files": [saved_path] if saved_path else []
                    }

                    if project_url not in existing_urls:
                        data.append(item)
                        existing_urls.add(project_url)

                        with open(json_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)

                    time.sleep(ITEM_SLEEP)

                except StaleElementReferenceException:
                    continue

            try:
                next_btn = driver.find_element(By.LINK_TEXT, ">>")
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(PAGE_SLEEP)
                page += 1
            except:
                break

    finally:
        log(f"Finalizado. Total coletado: {len(data)}")
        input("ENTER para fechar...")
        driver.quit()


if __name__ == "__main__":
    main()
