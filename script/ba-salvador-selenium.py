import os, re, json, time, uuid, argparse, requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# Desativar avisos de segurança de certificados (para verify=False)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://cmsalvador.sys.inf.br/cl/prop_interna/"
OUT_DIR = "ba/salvador"
PDF_DIR = os.path.join(OUT_DIR, "pdf")
os.makedirs(PDF_DIR, exist_ok=True)

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def safe_filename(name: str) -> str: return re.sub(r"[^a-zA-Z0-9\-]+", "-", name.lower()).strip("-")

def format_date_iso(date_str):
    if not date_str: return None
    try: return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except: return None

def normalize_tipo(sigla: str) -> str:
    sigla = sigla.upper().strip()
    mapa = {"PLE": "Projeto de Lei", "PLC": "Projeto de Lei Complementar", "PEL": "Projeto de Emenda à LOM"}
    return mapa.get(sigla, sigla)

def slug_tipo(tipo: str) -> str: return safe_filename(tipo)

def extract_clean_url(raw):
    if not raw:
        return None

    # PDF direto
    if raw.startswith("http") and ".pdf" in raw.lower():
        return raw

    # ScriptCase: nm_gp_submit5('URL_DO_PDF', ...)
    m = re.search(r"nm_gp_submit5\(\s*'([^']+\.pdf)'", raw, re.IGNORECASE)
    if m:
        return m.group(1)

    return None


def get_session(driver):
    session = requests.Session()
    for c in driver.get_cookies(): session.cookies.set(c["name"], c["value"])
    return session

def extrair_status_detalhe(driver):
    status = []
    rows = driver.find_elements(By.XPATH, "//tr[starts-with(@id,'SC_ancor')]")[:3]
    for r in rows:
        try:
            data_raw = r.find_element(By.XPATH, ".//span[contains(@id,'tra_dt_movimentacao')]").text.strip()
            desc = r.find_element(By.XPATH, ".//td[contains(@class,'css_situacao_grid_line')]").text.strip()
            obs = ""
            try: obs = r.find_element(By.XPATH, ".//span[contains(@id,'tra_observacao')]").text.strip()
            except: pass
            descricao = f"{desc} ({obs})" if obs else desc
            status.append({"descricao": descricao, "data": format_date_iso(data_raw)})
        except: continue
    return status

def baixar_pdf(session, url, tipo, numero, ano):
    if not url: return None
    tipo_slug = slug_tipo(tipo)
    ano_dir = os.path.join(PDF_DIR, ano)
    os.makedirs(ano_dir, exist_ok=True)
    filename = f"{tipo_slug}-{numero}-{ano}.pdf"
    path = os.path.join(ano_dir, filename)
    try:
        r = session.get(url, stream=True, timeout=60, verify=False)
        if r.status_code == 200:
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192): f.write(chunk)
            return path.replace("\\", "/")
    except Exception as e:
        log(f"      [Erro Download] {e}")
    return None

def processar_detalhe(driver, session):
    pdf_url = None
    status = []

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "iframe"))
    )

    iframe = driver.find_elements(By.TAG_NAME, "iframe")[-1]
    driver.switch_to.frame(iframe)
    time.sleep(1)

    # tenta ir para a última página
    try:
        last = driver.find_element(By.ID, "last_bot")
        if "dis.png" not in (last.get_attribute("src") or ""):
            driver.execute_script("arguments[0].click()", last)
            time.sleep(1.5)
    except Exception:
        pass

    tentativas = 0
    while tentativas < 5:
        tentativas += 1

        anchors = driver.find_elements(By.TAG_NAME, "a")
        candidatos = []

        for a in anchors:
            raw = a.get_attribute("href") or ""
            texto = (a.text or "").lower()
            url = extract_clean_url(raw)
            if url:
                candidatos.append((texto, url))

        for texto, url in candidatos:
            if "integra" in texto or "íntegra" in texto:
                pdf_url = url
                break

        if not pdf_url and candidatos:
            pdf_url = candidatos[-1][1]

        if pdf_url:
            break

        # tenta voltar
        try:
            back = driver.find_element(By.ID, "back_bot")
            if "dis.png" in (back.get_attribute("src") or ""):
                break
            driver.execute_script("arguments[0].click()", back)
            time.sleep(1.5)
        except Exception:
            break

    status = extrair_status_detalhe(driver)
    driver.switch_to.default_content()
    return pdf_url, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        driver.get(BASE_URL)
        input("Faça login, pesquise e pressione ENTER...")
        session = get_session(driver)
        page, total_coletado = 1, 0
        paginas_sem_novos = 0



        while True:
            log(f">>> Página {page}")
            novos_na_pagina = 0

            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//tr[starts-with(@id,'SC_ancor')]")))
            
            i = 0
            while True:
                rows = driver.find_elements(By.XPATH, "//tr[starts-with(@id,'SC_ancor')]")
                if i >= len(rows): break
                if args.limit and total_coletado >= args.limit: 
                    log(f"Limite de {args.limit} atingido.")
                    return

                row = rows[i]

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(0.3)

                try:
                    codigo = row.find_element(By.XPATH, ".//span[contains(@id,'proposicao')]").text.strip()
                    m = re.match(r"([A-Z]{2,3})-(\d+)/(\d{4})", codigo)
                    if not m: 
                        i += 1
                        continue
                    sigla, numero, ano = m.groups()
                    tipo = normalize_tipo(sigla)
                    log(f"[P{page}] {tipo} {numero}/{ano} ({i+1}/{len(rows)})")

                    json_path = os.path.join(OUT_DIR, f"salvador{ano}.json")
                    data = []
                    if os.path.exists(json_path):
                        with open(json_path, "r", encoding="utf-8") as f: data = json.load(f)
                    
                    if any(f"{d['type']}-{d['number']}-{d['year']}" == f"{tipo}-{numero}-{ano}" for d in data):
                        log("   [SKIP] Já existe")
                        i += 1
                        total_coletado += 1
                        continue

                    autor = row.find_element(By.XPATH, ".//span[contains(@id,'autorproposicao')]").text.strip()
                    subject = row.find_element(By.XPATH, ".//span[contains(@id,'pro_ementa')]").text.strip()
                    data_raw = row.find_element(By.XPATH, ".//span[contains(@id,'tra_dt_movimentacao')]").text.strip()
                    
                    links = row.find_elements(By.TAG_NAME, "a")
                    if links:
                        driver.execute_script("arguments[0].click()", links[0])
                        time.sleep(1.5)
                        pdf_url, status = processar_detalhe(driver, session)
                        
                        local_pdf = baixar_pdf(session, pdf_url, tipo, numero, ano)
                        
                        item = {
                            "uuid": uuid.uuid4().hex, "type": tipo, "house": "Câmara Municipal de Salvador",
                            "scraped_at": datetime.now().isoformat(), "number": numero, "year": ano,
                            "title": f"{tipo} nº {numero}/{ano}", "author": [autor] if autor else [],
                            "subject": subject, "presentation_date": format_date_iso(data_raw),
                            "status": status, "file_urls": [pdf_url] if pdf_url else [],
                            "pdf_files": [local_pdf] if local_pdf else [],
                            "md_files": f"ba/salvador/{slug_tipo(tipo)}-{numero}-{ano}.md"
                        }
                        data.append(item)
                        with open(json_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
                        log(f"   [+] Salvo{' (com PDF)' if local_pdf else ' (SEM PDF)'}")
                        total_coletado += 1
                        novos_na_pagina += 1

                    i += 1
                except StaleElementReferenceException: continue
                except Exception as e: 
                    log(f"Erro no item: {e}")
                    i += 1

            # Próxima Página
            log(f"Fim da página {page}.")

            if novos_na_pagina == 0:
                paginas_sem_novos += 1
                log("Nenhum item novo nesta página.")
            else:
                paginas_sem_novos = 0

            if paginas_sem_novos >= 2:
                log("Duas páginas seguidas sem itens novos. Encerrando.")
                break

            driver.switch_to.default_content()
            try:
                next_btns = driver.find_elements(By.ID, "forward_bot")
                if next_btns and "dis.png" not in (next_btns[0].get_attribute("src") or ""):
                    driver.execute_script("arguments[0].click();", next_btns[0])
                    time.sleep(4)
                    page += 1
                else:
                    log("Botão avançar desativado. Encerrando.")
                    break
            except:
                break

    finally: driver.quit()

if __name__ == "__main__": main()