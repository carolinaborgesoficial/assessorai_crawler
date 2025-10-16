import argparse
import json
import weaviate
import os
import tiktoken
from datetime import datetime
from weaviate.util import generate_uuid5
import weaviate.classes.config as wc
from weaviate.classes.config import Configure
from weaviate.classes.init import Auth
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

def chunk_text(text, max_tokens=3000, overlap_tokens=150, model="text-embedding-ada-002"):
    """Divide o texto em chunks baseados em tokens do modelo OpenAI."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    chunks = []
    i = 0
    while i < len(tokens):
        end = min(i + max_tokens, len(tokens))
        chunk_tokens = tokens[i:end]
        chunk = encoding.decode(chunk_tokens)
        if end < len(tokens):
            pos = chunk.rfind(' ')
            if pos != -1:
                chunk = chunk[:pos+1]
                used = encoding.encode(chunk)
                end = i + len(used)
        chunks.append({"text": chunk, "number": len(chunks)})
        if end >= len(tokens):
            break
        i = end - overlap_tokens
        overlap = encoding.decode(tokens[i:i+overlap_tokens])
        sp = overlap.find(' ')
        if sp != -1:
            adj = sp + 1
            i += len(encoding.encode(overlap[:adj])) - overlap_tokens
    return chunks


def load_items(json_file):
    """Carrega itens do JSON de saída do Scrapy."""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def setup_schema(client, class_name, vector_config, reset=False):
    """Cria ou reseta a classe no Weaviate com propriedades incluindo chunks."""
    if reset:
        try:
            client.collections.delete(class_name)
            print(f"Coleção '{class_name}' resetada.")
        except Exception:
            pass
    if not client.collections.exists(class_name):
        props = [
            wc.Property(name='title', data_type=wc.DataType.TEXT),
            wc.Property(name='house', data_type=wc.DataType.TEXT),
            wc.Property(name='type', data_type=wc.DataType.TEXT),
            wc.Property(name='number', data_type=wc.DataType.INT),
            wc.Property(name='presentation_date', data_type=wc.DataType.TEXT),
            wc.Property(name='year', data_type=wc.DataType.INT),
            wc.Property(name='author', data_type=wc.DataType.TEXT_ARRAY),
            wc.Property(name='subject', data_type=wc.DataType.TEXT),
            wc.Property(name='full_text', data_type=wc.DataType.TEXT),
            wc.Property(name='length', data_type=wc.DataType.INT),
            wc.Property(name='url', data_type=wc.DataType.TEXT),
            wc.Property(name='scraped_at', data_type=wc.DataType.TEXT),
            # Propriedades de chunk
            wc.Property(name='chunk_text', data_type=wc.DataType.TEXT),
            wc.Property(name='chunk_number', data_type=wc.DataType.INT),
        ]
        client.collections.create(
            name=class_name,
            properties=props,
            vectorizer_config=vector_config
        )
        print(f"Coleção '{class_name}' criada com chunks.")
    else:
        print(f"Coleção '{class_name}' já existe. Pulando criação.")


def import_items(client, class_name, items, batch_size=10, dry_run=False):
    """Importa itens e seus chunks no Weaviate."""
    collection = client.collections.get(class_name)
    total = 0
    with collection.batch.fixed_size(batch_size=batch_size) as batch:
        for item in tqdm(items):
            full = item.get('full_text', '')
            chunks = chunk_text(full)
            for chunk in chunks:
                props = {
                    'title': item.get('title'),
                    'house': item.get('house'),
                    'type': item.get('type'),
                    'number': item.get('number'),
                    'presentation_date': item.get('presentation_date'),
                    'year': item.get('year'),
                    'author': item.get('author'),
                    'subject': item.get('subject'),
                    'full_text': full,
                    'length': item.get('length'),
                    'url': item.get('url'),
                    'scraped_at': item.get('scraped_at'),
                    'chunk_text': chunk['text'],
                    'chunk_number': chunk['number'],
                }
                uuid = generate_uuid5(chunk['text'])
                if dry_run:
                    print(f"DRY RUN: chunk {chunk['number']} -> UUID: {uuid}")
                else:
                    batch.add_object(properties=props, uuid=uuid)
                total += 1
                
            if batch.number_errors > 10:
                print("Batch import stopped due to excessive errors.")
                break
                    

        failed_objects = collection.batch.failed_objects
        if failed_objects:
            print(f"Number of failed imports: {len(failed_objects)}")
            print(f"First failed object: {failed_objects[0:5]}")

    print(f"Importação finalizada: {total} chunks.")


def main():
    parser = argparse.ArgumentParser(
        description="Importa JSON de proposições com chunking para o Weaviate"
    )
    parser.add_argument("--input", required=True,
                        help="Arquivo JSON (saída do Scrapy)")
    parser.add_argument("--reset", action="store_true",
                        help="Reseta a classe antes de criar")
    parser.add_argument("--dry_run", action="store_true",
                        help="Apenas imprime UUID sem inserir")
    args = parser.parse_args()
    
    #load config from .env
    config = {
        "weaviate_url": os.getenv("WEAVIATE_URL", ""),
        "weaviate_apikey": os.getenv("WEAVIATE_API_KEY", ""),
        "class_name": os.getenv("WEAVIATE_CLASS", "Bill"),
        "openai_apikey": os.getenv("OPENAI_APIKEY", ""),
    }

    headers = {"X-OpenAI-Api-Key": config.get("openai_apikey")} if config.get("openai_apikey") else {}
    auth = Auth.api_key(api_key=config.get("weaviate_apikey")) if config.get("weaviate_apikey") else None

    client = weaviate.connect_to_weaviate_cloud(
        cluster_url=config.get("weaviate_url"),
        auth_credentials=auth,
        headers=headers,
        additional_config=weaviate.config.AdditionalConfig(timeout=weaviate.config.Timeout(insert=300))
    )
    print(f"Conectado a Weaviate em {config.get('weaviate_url')}")

    vec_conf = [
        Configure.NamedVectors.text2vec_openai(
            name="chunk_vector",
            source_properties=["title","subject","chunk_text"]
        )]
    setup_schema(client, config.get("class_name"), vec_conf, reset=args.reset)

    items = load_items(args.input)
    import_items(client, config.get("class_name"), items, dry_run=args.dry_run)

    client.close()

if __name__ == '__main__':
    main()
