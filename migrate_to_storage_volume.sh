#!/bin/bash

# Script para migrar dados locais para o volume storage do Docker
# Execute este script após iniciar os containers pela primeira vez

echo "========================================"
echo "Migração de dados para volume storage"
echo "========================================"

# Nome do container do scrapyd
CONTAINER_NAME="assessorai-scrapyd"

# Verificar se o container está rodando
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "Erro: Container $CONTAINER_NAME não está rodando."
    echo "Execute 'docker compose up -d' primeiro."
    exit 1
fi

# Função para copiar dados se o diretório existir
copy_if_exists() {
    local source_dir=$1
    local target_path=$2
    
    if [ -d "$source_dir" ] && [ "$(ls -A $source_dir)" ]; then
        echo "Copiando $source_dir..."
        docker exec $CONTAINER_NAME mkdir -p "/app/storage/$target_path"
        docker cp "$source_dir/." "$CONTAINER_NAME:/app/storage/$target_path/"
        echo "✓ $source_dir copiado com sucesso"
    else
        echo "⊘ $source_dir não existe ou está vazio, pulando..."
    fi
}

echo ""
echo "Iniciando cópia de dados..."
echo ""

# Copiar logs
copy_if_exists "./logs" "logs"

# Copiar items
copy_if_exists "./items" "items"

# Copiar dbs
copy_if_exists "./dbs" "dbs"

# Copiar downloads
copy_if_exists "./downloads" "downloads"

echo ""
echo "========================================"
echo "Migração concluída!"
echo "========================================"
echo ""
echo "Próximos passos:"
echo "1. Verifique se os dados foram copiados: docker exec $CONTAINER_NAME ls -la /app/storage/"
echo "2. Se tudo estiver OK, você pode remover os diretórios locais antigos (faça backup primeiro!):"
echo "   mv logs logs.backup"
echo "   mv items items.backup"
echo "   mv dbs dbs.backup"
echo "   mv downloads downloads.backup"
echo "3. Reinicie os containers: docker compose restart"
echo ""
