import os
import json
import argparse
import logging
from assessorai_crawler.pipelines import GeminiPDFExtractionPipeline
import google.generativeai as genai

from dotenv import load_dotenv
load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Extrai texto de PDFs usando Gemini e salva como Markdown.")
    parser.add_argument("--jl", required=True, help="Caminho para o arquivo .jl com os itens padronizados")
    parser.add_argument("--limite", type=int, default=None, help="Limite máximo de arquivos a processar")
    parser.add_argument("--log", help="Caminho para o arquivo de log")
    args = parser.parse_args()

    logging.basicConfig(
        filename=args.log,
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    pipeline = GeminiPDFExtractionPipeline()

    with open(args.jl, "r", encoding="utf-8") as f:
        itens = [json.loads(linha) for linha in f]

    processados = 0
    for item in itens:
        if args.limite and processados >= args.limite:
            break

        tipo = item.get("tipo_documento")
        numero = item.get("numero_documento")

        caminho_pdf = item.get("caminho_arquivo_original")
        caminho_md = item.get("caminho_arquivo_texto")

        if not caminho_pdf:
            logging.warning(f"[{tipo} {numero}] Item sem 'caminho_arquivo_original'.")
            continue

        if not caminho_md:
            logging.warning(f"[{tipo} {numero}] Item sem 'caminho_arquivo_texto'.")
            continue

        pdf_path = os.path.normpath(os.path.join("storage", "downloads", "pdf", caminho_pdf))
        md_path = os.path.normpath(os.path.join("storage", "downloads", "md", caminho_md))

        if not os.path.exists(pdf_path):
            logging.warning(f"[{tipo} {numero}] PDF não encontrado: {pdf_path}.")
            continue

        if os.path.exists(md_path):
            logging.warning(f"[{tipo} {numero}] Arquivo já existe: {md_path}.")
            continue

        try:
            logging.info(f"[{tipo} {numero}] Processando: {pdf_path}")
            uploaded = genai.upload_file(pdf_path)
            resposta = pipeline.model.generate_content([
                pipeline.extraction_prompt,
                uploaded
            ])
            texto = resposta.text
            genai.delete_file(uploaded.name)

            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(texto)

            logging.info(f"[{tipo} {numero}] Texto salvo em: {md_path}")
            processados += 1

        except Exception as e:
            logging.error(f"[{tipo} {numero}] Erro ao processar {pdf_path}: {e}")
            continue

if __name__ == "__main__":
    main()
