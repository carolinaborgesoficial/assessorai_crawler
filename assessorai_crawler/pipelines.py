# Arquivo: assessorai_crawler/pipelines.py

import json
import os
import re
import google.generativeai as genai
from unidecode import unidecode
from scrapy import Request
from scrapy.exceptions import DropItem
from scrapy.pipelines.files import FilesPipeline
from datetime import datetime
from scrapy.utils.project import get_project_settings

class PipelinePadronizacao:
    """
    Recebe o item bruto, padroniza os dados e gera os caminhos dos arquivos.
    """

    def _slugify(self, text):
        """Converte um texto como "São Paulo" para "sao-paulo"."""
        if not text: return ""
        text = unidecode(str(text))
        text = text.lower()
        text = re.sub(r'[\s\W_]+', '-', text)
        return text.strip('-')

    def process_item(self, item, spider):
        autores_final = []
        for autor_raw in item.get('autores_bruto', []):
            nome, partido = self._extrair_nome_partido(autor_raw)
            autores_final.append({"nome": nome, "partido": partido})

        data_formatada = self._formatar_data(item.get('data_documento_bruto'))
        
        numero = item.get("numero_bruto")
        ano = item.get("ano_bruto")
        tipo = item.get("tipo_bruto", "projeto-de-lei").lower().replace(" ", "-")

        if numero and ano:
            nome_arquivo = f"{tipo}-{numero}-{ano}"
        else:
            nome_arquivo = "arquivo-sem-nome"

        uf_slug = self._slugify(spider.uf)
        municipio_slug = self._slugify(spider.municipio)
        caminho_base = f"{uf_slug}/{municipio_slug}/{spider.slug}/{nome_arquivo}"

        # só define caminho do PDF se realmente houver PDF
        tem_pdf = bool(item.get("url_documento_original")) or bool(item.get("file_urls"))
        caminho_pdf = (
            item.get("caminho_arquivo_original")
            if item.get("caminho_arquivo_original") and tem_pdf
            else (f"{caminho_base}.pdf" if tem_pdf else None)
        )

        caminho_md = item.get("caminho_arquivo_texto") or f"{caminho_base}.md"


        item_padronizado = {
            "localidade": {"esfera": spider.esfera, "municipio": spider.municipio, "estado": spider.uf},
            "casa_legislativa": spider.casa_legislativa,
            "tipo_documento": item.get('tipo_bruto'),
            "numero_documento": str(item.get('numero_bruto')),
            "data_documento": data_formatada,
            "autores": autores_final,
            "ementa": item.get('ementa_bruto'),
            "assuntos": item.get('assuntos_bruto', []),
            "status_tramitacao": [
                {
                    "descricao": s.get("descricao"),
                    "data": self._formatar_data(s.get("data"))
                }
                for s in item.get('status_bruto', [])
            ],
            "url_documento_original": item.get("url_documento_original"),
            "caminho_arquivo_original": caminho_pdf,
            "caminho_arquivo_texto": caminho_md,

            "data_raspagem": item.get('data_raspagem_bruto')
        }
        
        return {'item_bruto': item, 'item_padronizado': item_padronizado}

    def _extrair_nome_partido(self, texto_autor):
        match = re.search(r'\((.*?)\)', texto_autor)
        if match:
            partido = match.group(1).strip().upper()
            nome = re.sub(r'^\s*Ver\.\s*', '', texto_autor).replace(f"({match.group(1)})", "").strip()
            return nome, partido
        return texto_autor.strip(), None

    def _formatar_data(self, data_texto):
        if not data_texto:
            return None
        formatos = [
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%d/%m/%Y',
            '%Y-%m-%d',   # já normalizado no spider
            '%m/%d/%Y'    # caso venha invertido
        ]
        for fmt in formatos:
            try:
                return datetime.strptime(data_texto.strip(), fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        # tenta "27 de outubro de 2025"
        match = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', data_texto, re.IGNORECASE)
        if match:
            dia, mes_nome, ano = match.groups()
            meses = {
                'janeiro': '01','fevereiro': '02','março': '03','abril': '04',
                'maio': '05','junho': '06','julho': '07','agosto': '08',
                'setembro': '09','outubro': '10','novembro': '11','dezembro': '12'
            }
            mes = meses.get(mes_nome.lower())
            if mes:
                return f"{ano}-{mes}-{int(dia):02d}"
        return data_texto



class ProposicaoFilesPipeline(FilesPipeline):
    """Baixa e salva os PDFs dentro de FILES_STORE/pdf/..."""

    def get_media_requests(self, item, info):
        item_bruto = item.get("item_bruto", {})
        urls = item_bruto.get("file_urls", [])
        for url in urls:
            yield Request(url, meta={"item": item})

    def file_path(self, request, response=None, info=None, *, item=None):
        item_padronizado = item.get("item_padronizado", {})
        caminho_relativo = item_padronizado.get("caminho_arquivo_original")
        # força salvar dentro de pdf/
        return os.path.join("pdf", caminho_relativo)

class JsonWriterSinglePipeline:
    """Salva cada item padronizado como uma linha em um arquivo .jl."""
    def open_spider(self, spider):
        output_dir = f'output'
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f'{spider.slug}_proposicoes.jl')
        self.file = open(file_path, 'w', encoding='utf-8')

    def process_item(self, item, spider):
        item_padronizado = item['item_padronizado']
        # Escreve uma única linha, sem indentação ---
        line = json.dumps(dict(item_padronizado), ensure_ascii=False) + "\n"
        self.file.write(line)
        return item

    def close_spider(self, spider):
        self.file.close()

class ValidationPipeline:
    """Valida se o spider coletou os dados brutos mínimos necessários."""
    def process_item(self, item, spider):
        item_bruto = item['item_bruto']
        if hasattr(item_bruto, 'missing_fields'):
            missing = item_bruto.missing_fields()
            if missing:
                raise DropItem(f"Item bruto descartado, campos faltando: {missing}")
        return item

class GeminiPDFExtractionPipeline:
    """Pipeline que usa Google Gemini para extrair texto de PDFs"""
    
    def __init__(self):
        # Configurar API do Gemini
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY não encontrada no arquivo .env")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        
        # Prompt para extração de texto legislativo
        self.extraction_prompt = """
Você é um assistente especializado em extrair texto de documentos legislativos brasileiros.

Extraia o texto completo deste documento PDF, preservando:
- A estrutura de artigos, parágrafos e incisos
- Numeração e formatação legal
- Texto de justificativas e ementas

Retorne apenas o texto extraído em formato markdown, sem comentários adicionais.
Organize o texto de forma clara e estruturada.
"""
    
    def process_item(self, item, spider):
        """Processa PDFs baixados e extrai texto usando Gemini"""
        files = item.get('files', [])
        
        if not files:
            spider.logger.warning(f"Item {item.get('title')} não possui arquivos para processar")
            return item
        
        extracted_texts = []
        files_dir = spider.settings.get('FILES_STORE', 'downloads')
        
        for file_path in files:
            full_path = os.path.join(files_dir, file_path)
            
            if not os.path.exists(full_path):
                spider.logger.warning(f"Arquivo não encontrado: {full_path}")
                continue
            
            try:
                # Upload do arquivo para o Gemini
                spider.logger.info(f"Processando PDF: {file_path}")
                uploaded_file = genai.upload_file(full_path)
                
                # Extrair texto usando o modelo
                response = self.model.generate_content([
                    self.extraction_prompt,
                    uploaded_file
                ])
                
                extracted_text = response.text
                extracted_texts.append(extracted_text)
                
                spider.logger.info(f"Texto extraído com sucesso de {file_path} ({len(extracted_text)} caracteres)")
                
                # Limpar arquivo do Gemini
                genai.delete_file(uploaded_file.name)
                
            except Exception as e:
                spider.logger.error(f"Erro ao processar {file_path}: {str(e)}")
                continue
        
        # Combinar todos os textos extraídos
        if extracted_texts:
            item['full_text'] = "\n\n---\n\n".join(extracted_texts)
            item['length'] = len(item['full_text'])
            spider.logger.info(f"Texto completo extraído: {item['length']} caracteres")
        else:
            spider.logger.warning(f"Nenhum texto foi extraído para {item.get('title')}")
            item['full_text'] = ""
            item['length'] = 0
        
        return item


class GeminiAssuntosPipeline:
    """Pipeline que usa Gemini para identificar os assuntos principais do texto em Markdown."""

    def __init__(self):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY não encontrada no ambiente ou no .env")

        genai.configure(api_key=api_key)
        # Use o modelo mais estável disponível
        self.model = genai.GenerativeModel("gemini-2.5-pro")

        # Prompt mais rígido para forçar JSON puro
        self.prompt_assuntos = """
Você é um assistente especializado em análise legislativa.

Receberá o texto integral de um projeto de lei em formato Markdown.
Sua tarefa é identificar os principais assuntos/temas tratados no documento.

Regras:
- Liste de 3 a 8 assuntos principais.
- Cada assunto deve ser curto (1 a 5 palavras).
- Apenas a primeira letra da primeira palavra  é maiúscula.
- Use substantivos claros, sem frases longas.
- A resposta deve ser exatamente uma lista com um assunto por linha, sem numeração, sem texto extra.
Exemplo de saída:
["Trânsito de caminhões",
 "Infraestrutura urbana",
 "Segurança viária",
 "Educação básica",
 "Saúde pública",
 "Meio ambiente",
 "Direitos do consumidor",
 "Gestão orçamentária",
 "Transporte coletivo",
 "Habitação popular",
 "Cultura e lazer",
 "Segurança pública",
 "Serviços de saneamento",
 "Tecnologia e inovação",
 "Maternidade",
 "Juventude",
 "Administração pública"]
 """

    def process_item(self, item, spider):
        # Só roda para o spider do Rio
        if spider.name != "proposicoescidrj":
            return item
        
        if "item_padronizado" in item:
            texto_md = item.get("item_bruto", {}).get("conteudo_markdown", "")
            if not texto_md:
                item["item_padronizado"]["assuntos"] = []
                return item

            try:
                resposta = self.model.generate_content(f"{self.prompt_assuntos}\n\n{texto_md}")
                raw = getattr(resposta, "text", None) or str(resposta)

                # Parser para linhas simples (sem JSON)
                lines = [ln.strip() for ln in raw.splitlines()]
                # remove linhas vazias e lixo
                linhas_validas = [
                    re.sub(r'^[\-\*\d\.\)\s]+', '', ln).strip(' "\'')
                    for ln in lines
                    if ln and not ln.lower().startswith("exemplo")
                ]

                # Normalização: primeira letra maiúscula, resto minúsculo; limita tamanho e quantidade
                def norm(s):
                    s = re.sub(r'\s+', ' ', s).strip()
                    # apenas primeira letra da primeira palavra maiúscula
                    words = s.split()
                    if not words:
                        return ""
                    words[0] = words[0][:1].upper() + words[0][1:].lower()
                    for i in range(1, len(words)):
                        words[i] = words[i].lower()
                    s = " ".join(words)
                    # até 7 palavras por assunto
                    return " ".join(s.split()[:7])

                assuntos = [norm(a) for a in linhas_validas if a]
                # mantém entre 3 e 8 itens
                if len(assuntos) < 3:
                    spider.logger.warning("[GeminiAssuntosPipeline] Poucos assuntos gerados; mantendo lista vazia.")
                    assuntos = []
                else:
                    assuntos = assuntos[:8]

                item["item_padronizado"]["assuntos"] = assuntos

            except Exception as e:
                spider.logger.error(f"[GeminiAssuntosPipeline] Erro ao gerar/parsear assuntos: {e}", exc_info=True)
                item["item_padronizado"]["assuntos"] = []

        return item




    def _formatar_data(self, data_texto):
        if not data_texto:
            return None
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            pass
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y %H:%M').strftime('%Y-%m-%d')
        except ValueError:
            pass
        try:
            return datetime.strptime(data_texto.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
        except ValueError:
            pass
        match = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', data_texto or "", re.IGNORECASE)
        if match:
            dia, mes_nome, ano = match.groups()
            meses = {
                'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
                'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
                'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
            }
            mes = meses.get(mes_nome.lower())
            if mes:
                return f"{ano}-{mes}-{int(dia):02d}"
        return data_texto
        
class SalvarMarkdownPipeline:
    """Salva o conteúdo em Markdown dentro de FILES_STORE/md/..."""

    def process_item(self, item, spider):
        settings = get_project_settings()
        files_dir = settings.get("FILES_STORE", "downloads")

        item_bruto = item.get("item_bruto", {})
        conteudo = item_bruto.get("conteudo_markdown")
        caminho = None

        if "item_padronizado" in item:
            caminho = item["item_padronizado"].get("caminho_arquivo_texto")

        if conteudo and caminho:
            # monta caminho final usando FILES_STORE
            caminho_final = os.path.join(files_dir, caminho)
            os.makedirs(os.path.dirname(caminho_final), exist_ok=True)
            with open(caminho_final, "w", encoding="utf-8") as f:
                f.write(conteudo)

            #spider.logger.info(f"Arquivo Markdown salvo em {caminho_final}")

            # atualiza o item para refletir o caminho relativo
            item["item_padronizado"]["caminho_arquivo_texto"] = os.path.relpath(
                caminho_final, files_dir
            )

        return item

