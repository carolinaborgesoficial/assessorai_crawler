import os
import re
import json
import time
import uuid
import requests
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURAÇÕES ---
BASE_URL = "https://cmsalvador.sys.inf.br/cl/prop_interna/"
OUT_DIR = "BA/salvador"
PDF_DIR = os.path.join(OUT_DIR, "pdf")
JSON_PATH = os.path.join(OUT_DIR, "proposicoes_salvador.json")

os.makedirs(PDF_DIR, exist_ok=True)

def safe_filename(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9\-_]', '_', name)

def format_date_iso(date_str):
    if not date_str: return None
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except:
        return None

def get_session_cookies(driver):
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain'))
    return session

def wait_for_grid(driver):
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//tr[starts-with(@id,'SC_ancor')]"))
        )
        return True
    except TimeoutException:
        return False

def extract_clean_url(dirty_url):
    if not dirty_url: return None
    if dirty_url.startswith("http"): return dirty_url
    match = re.search(r"'(http[^']+)'", dirty_url)
    if match: return match.group(1)
    return None

def download_file(session, url, numero, ano, codigo_full, text_content):
    clean_url = extract_clean_url(url)
    if not clean_url: return None

    try:
        if numero and ano:
            filename = f"projeto-de-lei-{numero}-{ano}.pdf"
            save_dir = os.path.join(PDF_DIR, ano)
        else:
            filename = f"projeto-de-lei-{safe_filename(codigo_full)}.pdf"
            save_dir = os.path.join(PDF_DIR, "outros")

        os.makedirs(save_dir, exist_ok=True)
        full_path = os.path.join(save_dir, filename)

        print(f"      [BAIXANDO] '{text_content}' -> {filename}")
        
        response = session.get(clean_url, stream=True, timeout=60, verify=False)
        if response.status_code == 200:
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"      [SUCESSO] Arquivo salvo.")
            return full_path.replace("\\", "/")
        else:
            print(f"      [ERRO] HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"      [ERRO DOWNLOAD] {e}")
        return None

def scan_page_for_candidates(driver):
    """
    Lê a página atual do iframe e retorna lista de candidatos a PDF.
    """
    candidates = []
    seen_urls = set()
    
    try:
        # Pega links
        elements = driver.find_elements(By.XPATH, "//a[contains(@id, 'id_sc_field_situacao') or contains(@href, '.pdf')]")
        for el in elements:
            raw_href = el.get_attribute("href")
            text = el.text.strip()
            
            if raw_href and ".pdf" in raw_href.lower():
                clean = extract_clean_url(raw_href)
                if clean and clean not in seen_urls:
                    seen_urls.add(clean)
                    candidates.append({
                        "raw_href": raw_href,
                        "clean_url": clean,
                        "text": text,
                        "text_lower": text.lower()
                    })
    except StaleElementReferenceException:
        pass # Pode acontecer se a página atualizar durante a leitura
        
    return candidates

def process_detail_iframe(driver, session, codigo_full):
    """
    Navega dentro do iframe:
    1. Vai para a ÚLTIMA página (last_bot).
    2. Procura PDF.
    3. Se não achar, clica em VOLTAR (back_bot) e repete.
    """
    pdf_url_found = None
    saved_file_path = None
    
    numero, ano = "", ""
    if "PLE-" in codigo_full:
        try:
            parts = codigo_full.split("-")[1].split("/")
            numero = parts[0]
            ano = parts[1]
        except: pass

    print("    [DETALHE] Entrando no iframe...")
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if not iframes: return None, None

        driver.switch_to.frame(iframes[-1])
        time.sleep(1)

        # --- PASSO 1: TENTAR IR PARA A ÚLTIMA PÁGINA ---
        try:
            last_btn = driver.find_element(By.ID, "last_bot")
            # Verifica se não está desabilitado (classe disabled ou imagem dis.png)
            is_disabled = "disabled" in last_btn.get_attribute("class")
            src = last_btn.get_attribute("src") or ""
            if "dis.png" in src or "sys_format_avc_dis" in src: is_disabled = True
            
            if not is_disabled:
                print("      [NAV] Indo para a última página interna...")
                driver.execute_script("arguments[0].click();", last_btn)
                time.sleep(2) # Espera recarregar
        except:
            pass # Se não tiver botão last, assume que é página única

        # --- PASSO 2: LOOP DE BUSCA (DO FIM PARA O INÍCIO) ---
        while True:
            candidates = scan_page_for_candidates(driver)
            selected_candidate = None

            # A. Prioridade: "Anexado Integra"
            for cand in candidates:
                if "anexado integra" in cand["text_lower"]:
                    selected_candidate = cand
                    print(f"      [PRIORIDADE] Encontrado: '{cand['text']}'")
                    break
            
            # B. Fallback: Último da lista (mais antigo) que não seja Mensagem
            if not selected_candidate and candidates:
                for cand in reversed(candidates):
                    if "anexado mensagem" in cand["text_lower"] and "executivo" in cand["text_lower"]:
                        continue
                    selected_candidate = cand
                    print(f"      [CANDIDATO] '{cand['text']}' nesta página.")
                    break # Pega o primeiro válido de baixo pra cima desta página

            # Se achou um candidato válido nesta página, baixa e encerra
            if selected_candidate:
                path = download_file(
                    session, 
                    selected_candidate["raw_href"], 
                    numero, 
                    ano, 
                    codigo_full, 
                    selected_candidate["text"]
                )
                if path:
                    saved_file_path = path
                    pdf_url_found = selected_candidate["clean_url"]
                    break # Sai do loop while, achamos o arquivo

            # Se não achou nada útil nesta página, tenta voltar uma página
            try:
                back_btn = driver.find_element(By.ID, "back_bot")
                
                # Verifica se está desabilitado (chegamos no início)
                is_disabled = "disabled" in back_btn.get_attribute("class")
                src = back_btn.get_attribute("src") or ""
                if "dis.png" in src or "sys_format_avc_dis" in src: is_disabled = True

                if is_disabled:
                    print("      [NAV] Chegamos ao início da paginação interna. Nada encontrado.")
                    break # Sai do loop
                
                print("      [NAV] Voltando uma página interna...")
                driver.execute_script("arguments[0].click();", back_btn)
                time.sleep(1.5) # Espera recarregar
            except:
                # Se não tem botão de voltar, é página única e já lemos
                break

    except Exception as e:
        print(f"    [ERRO IFRAME] {e}")
    finally:
        driver.switch_to.default_content()
        try:
            fechar = driver.find_elements(By.CLASS_NAME, "tb_close")
            if fechar: fechar[0].click()
            else:
                driver.switch_to.frame(iframes[-1])
                try: driver.find_element(By.ID, "sai_top").click()
                except: pass
                driver.switch_to.default_content()
        except: pass
        
    return pdf_url_found, saved_file_path

def main():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--ignore-ssl-errors')
    chrome_options.add_argument("--log-level=3") 
    requests.packages.urllib3.disable_warnings()

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    data_collected = []

    try:
        driver.get(BASE_URL)
        print("\n" + "="*60)
        print(" MODO: 2020+ | NAV INTERNA (LAST -> BACK) | INTEGRA > FALLBACK")
        print(" 1. Faça Login/Captcha.")
        print(" 2. Pesquise.")
        print(" 3. Volte aqui e aperte ENTER.")
        print("="*60 + "\n")
        input(">>> Pressione ENTER para começar...")

        session = get_session_cookies(driver)
        page_count = 1

        while True:
            print(f"\n>>> Processando Página Principal {page_count}")
            if not wait_for_grid(driver):
                print("Tabela não encontrada.")
                break

            rows = driver.find_elements(By.XPATH, "//tr[starts-with(@id,'SC_ancor')]")
            total_rows = len(rows)
            print(f"Registros: {total_rows}")

            if total_rows == 0: break

            for i in range(total_rows):
                try:
                    wait_for_grid(driver)
                    current_rows = driver.find_elements(By.XPATH, "//tr[starts-with(@id,'SC_ancor')]")
                    if i >= len(current_rows): continue
                    row = current_rows[i]
                    
                    def get_span(tid):
                        try: return row.find_element(By.XPATH, f".//span[contains(@id,'{tid}')]").text.strip()
                        except: return ""

                    codigo_raw = get_span("id_sc_field_proposicao")
                    if not codigo_raw:
                        match = re.search(r"(PLE-\d+/\d{4})", row.text)
                        if match: codigo_raw = match.group(1)

                    if not codigo_raw or "PLE-" not in codigo_raw: continue

                    # --- PARSE E FILTRO DE ANO ---
                    numero, ano = "", ""
                    try:
                        parts = codigo_raw.split("-")[1].split("/")
                        numero = parts[0]
                        ano = parts[1]
                    except: pass

                    if ano and ano.isdigit():
                        if int(ano) < 2020:
                            print(f"[{i+1}/{total_rows}] {codigo_raw} -> [SKIP] Ano {ano} ignorado.")
                            continue

                    print(f"[{i+1}/{total_rows}] {codigo_raw}")

                    autor_raw = get_span("id_sc_field_autorproposicao")
                    ementa_raw = get_span("id_sc_field_pro_ementa")
                    data_raw = get_span("id_sc_field_tra_dt_movimentacao")
                    
                    try:
                        link = row.find_element(By.XPATH, ".//a[contains(@href, 'nm_gp_move') or contains(@id, 'id_sc_field_tramite')]")
                        driver.execute_script("arguments[0].scrollIntoView(true);", link)
                        driver.execute_script("arguments[0].click();", link)
                        time.sleep(1.5)
                        
                        url_pdf, local_file = process_detail_iframe(driver, session, codigo_raw)
                        
                        data_iso = format_date_iso(data_raw)

                        item = {
                            "uuid": uuid.uuid4().hex,
                            "type": "Projeto de Lei",
                            "project_url": None,
                            "house": "Câmara Municipal de Salvador",
                            "scraped_at": datetime.now().isoformat(),
                            "number": numero,
                            "year": ano,
                            "title": f"Projeto de Lei nº {numero}/{ano}" if numero and ano else f"Projeto de Lei {codigo_raw}",
                            "author": [autor_raw] if autor_raw else [],
                            "emenda": ementa_raw,
                            "subject": ["Sem dados informados"],
                            "presentation_date": data_iso,
                            "status": [
                                {
                                    "descricao": "Protocolado",
                                    "data": data_iso
                                }
                            ],
                            "url": None,
                            "file_urls": [url_pdf] if url_pdf else [],
                            "pdf_files": [local_file] if local_file else [],
                            "md_files": f"BA/salvador/projeto-de-lei-{numero}-{ano}.md" if numero and ano else None
                        }
                        
                        data_collected.append(item)

                    except Exception as e:
                        print(f"    Erro linha: {e}")
                        driver.switch_to.default_content()

                except StaleElementReferenceException: pass

            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data_collected, f, ensure_ascii=False, indent=2)

            print(">>> Próxima página principal...")
            clicked_next = False
            for pid in ["forward_bot", "forward_top", "sc_b_nav_top", "sc_b_nav_bot"]:
                try:
                    btn = driver.find_element(By.ID, pid)
                    if "disabled" in btn.get_attribute("class"): continue
                    src = btn.get_attribute("src") or ""
                    if "dis.png" in src or "sys_format_avc_dis" in src: continue
                    driver.execute_script("arguments[0].click();", btn)
                    clicked_next = True
                    break
                except: continue
            
            if clicked_next:
                page_count += 1
                try: WebDriverWait(driver, 10).until(EC.staleness_of(rows[0]))
                except: pass
                time.sleep(2)
            else:
                print(">>> Fim.")
                break

    except Exception as e:
        print(f"ERRO: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
