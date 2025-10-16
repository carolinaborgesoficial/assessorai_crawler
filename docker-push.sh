#!/bin/bash
# Script para fazer push da imagem Docker para registries

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

IMAGE_NAME="assessorai-crawler"
IMAGE_TAG="latest"

function print_usage() {
    echo "Uso: $0 [registry] [username] [version]"
    echo ""
    echo "Registries disponíveis:"
    echo "  ghcr         - GitHub Container Registry (ghcr.io) [RECOMENDADO]"
    echo "  dockerhub    - Docker Hub (docker.io)"
    echo ""
    echo "Exemplos:"
    echo "  $0 ghcr pmarkun v1.0.0              # Recomendado"
    echo "  $0 dockerhub myusername v1.0.0"
    echo "  $0 ghcr pmarkun                     # Usa 'latest' como versão"
    echo ""
}

function build_image() {
    echo -e "${BLUE}📦 Building imagem Docker...${NC}"
    docker compose build
    echo -e "${GREEN}✓ Build concluído!${NC}"
    echo ""
}

function push_dockerhub() {
    local username=$1
    local version=${2:-latest}
    
    echo -e "${BLUE}🐳 Preparando push para Docker Hub...${NC}"
    echo -e "${YELLOW}Registry: docker.io${NC}"
    echo -e "${YELLOW}Username: $username${NC}"
    echo -e "${YELLOW}Versão: $version${NC}"
    echo ""
    
    # Verificar se está logado
    if ! docker info | grep -q "Username: $username"; then
        echo -e "${YELLOW}⚠️  Você não está logado no Docker Hub${NC}"
        echo -e "${BLUE}Fazendo login...${NC}"
        docker login
    fi
    
    # Tag da imagem
    echo -e "${BLUE}🏷️  Criando tags...${NC}"
    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${username}/${IMAGE_NAME}:${version}
    
    if [ "$version" != "latest" ]; then
        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${username}/${IMAGE_NAME}:latest
    fi
    
    # Push
    echo -e "${BLUE}⬆️  Fazendo push...${NC}"
    docker push ${username}/${IMAGE_NAME}:${version}
    
    if [ "$version" != "latest" ]; then
        docker push ${username}/${IMAGE_NAME}:latest
    fi
    
    echo ""
    echo -e "${GREEN}✓ Push concluído com sucesso!${NC}"
    echo -e "${GREEN}📍 Imagem disponível em: https://hub.docker.com/r/${username}/${IMAGE_NAME}${NC}"
    echo ""
    echo -e "${BLUE}Para usar a imagem:${NC}"
    echo -e "  docker pull ${username}/${IMAGE_NAME}:${version}"
}

function push_ghcr() {
    local username=$1
    local version=${2:-latest}
    
    echo -e "${BLUE}📦 Preparando push para GitHub Container Registry...${NC}"
    echo -e "${YELLOW}Registry: ghcr.io${NC}"
    echo -e "${YELLOW}Username: $username${NC}"
    echo -e "${YELLOW}Versão: $version${NC}"
    echo ""
    
    # Verificar se está logado
    if ! docker info 2>&1 | grep -q "ghcr.io"; then
        echo -e "${YELLOW}⚠️  Você precisa fazer login no GitHub Container Registry${NC}"
        echo -e "${BLUE}Crie um Personal Access Token em: https://github.com/settings/tokens${NC}"
        echo -e "${BLUE}Permissões necessárias: write:packages, read:packages${NC}"
        echo ""
        read -p "Cole seu GitHub Token: " -s token
        echo ""
        echo "$token" | docker login ghcr.io -u "$username" --password-stdin
    fi
    
    # Tag da imagem
    echo -e "${BLUE}🏷️  Criando tags...${NC}"
    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ghcr.io/${username}/${IMAGE_NAME}:${version}
    
    if [ "$version" != "latest" ]; then
        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ghcr.io/${username}/${IMAGE_NAME}:latest
    fi
    
    # Push
    echo -e "${BLUE}⬆️  Fazendo push...${NC}"
    docker push ghcr.io/${username}/${IMAGE_NAME}:${version}
    
    if [ "$version" != "latest" ]; then
        docker push ghcr.io/${username}/${IMAGE_NAME}:latest
    fi
    
    echo ""
    echo -e "${GREEN}✓ Push concluído com sucesso!${NC}"
    echo -e "${GREEN}📍 Imagem disponível em: https://github.com/${username}/${IMAGE_NAME}/pkgs/container/${IMAGE_NAME}${NC}"
    echo ""
    echo -e "${BLUE}Para usar a imagem:${NC}"
    echo -e "  docker pull ghcr.io/${username}/${IMAGE_NAME}:${version}"
}

# Main
if [ $# -lt 2 ]; then
    print_usage
    exit 1
fi

REGISTRY=$1
USERNAME=$2
VERSION=${3:-latest}

# Build da imagem primeiro
build_image

case "$REGISTRY" in
    dockerhub)
        push_dockerhub "$USERNAME" "$VERSION"
        ;;
    ghcr)
        push_ghcr "$USERNAME" "$VERSION"
        ;;
    *)
        echo -e "${RED}❌ Registry inválido: $REGISTRY${NC}"
        echo ""
        print_usage
        exit 1
        ;;
esac
