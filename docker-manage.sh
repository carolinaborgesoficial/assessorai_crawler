#!/bin/bash
# Script auxiliar para gerenciar o ambiente Docker do Assessor AI Crawler

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

function print_usage() {
    echo "Uso: $0 [comando]"
    echo ""
    echo "Comandos disponíveis:"
    echo "  start         - Inicia os serviços"
    echo "  stop          - Para os serviços"
    echo "  restart       - Reinicia os serviços"
    echo "  logs [srv]    - Mostra logs (srv: scrapyd, scrapydweb, logparser)"
    echo "  status        - Mostra status dos serviços"
    echo "  shell         - Acessa shell do container scrapyd"
    echo "  deploy        - Faz deploy do projeto no scrapyd"
    echo "  run [spider]  - Executa um spider"
    echo "  list          - Lista os spiders disponíveis"
    echo "  build         - Reconstrói as imagens"
    echo "  clean         - Para e remove containers (mantém dados)"
    echo "  purge         - Remove tudo, incluindo volumes (CUIDADO!)"
    echo ""
}

function start_services() {
    echo -e "${GREEN}Iniciando serviços...${NC}"
    docker-compose up -d
    echo -e "${GREEN}Serviços iniciados!${NC}"
    echo -e "${YELLOW}ScrapydWeb: http://localhost${NC}"
    echo -e "${YELLOW}Scrapyd API: http://localhost/scrapyd${NC}"
    echo -e "${YELLOW}Logs: http://localhost/scrapyd/logs/${NC}"
    echo -e "${YELLOW}Items: http://localhost/scrapyd/items/${NC}"
}

function stop_services() {
    echo -e "${YELLOW}Parando serviços...${NC}"
    docker-compose down
    echo -e "${GREEN}Serviços parados!${NC}"
}

function restart_services() {
    stop_services
    start_services
}

function show_logs() {
    local service=$1
    if [ -z "$service" ]; then
        docker-compose logs -f
    else
        docker-compose logs -f "$service"
    fi
}

function show_status() {
    echo -e "${GREEN}Status dos serviços:${NC}"
    docker-compose ps
    echo ""
    echo -e "${GREEN}Verificando saúde do Scrapyd...${NC}"
    curl -s http://localhost/scrapyd/daemonstatus.json | python3 -m json.tool || echo -e "${RED}Scrapyd não está respondendo${NC}"
}

function shell_access() {
    echo -e "${GREEN}Acessando shell do container scrapyd...${NC}"
    docker exec -it assessorai-scrapyd bash
}

function deploy_project() {
    echo -e "${GREEN}Fazendo deploy do projeto...${NC}"
    docker exec -it assessorai-scrapyd scrapyd-deploy
    echo -e "${GREEN}Deploy concluído!${NC}"
}

function run_spider() {
    local spider=$1
    if [ -z "$spider" ]; then
        echo -e "${RED}Erro: Especifique o nome do spider${NC}"
        echo "Uso: $0 run [spider_name]"
        echo ""
        list_spiders
        return 1
    fi
    
    echo -e "${GREEN}Executando spider: $spider${NC}"
    curl http://localhost/scrapyd/schedule.json -d project=assessorai_crawler -d spider="$spider"
    echo ""
    echo -e "${GREEN}Spider agendado! Veja os logs em: http://localhost${NC}"
}

function list_spiders() {
    echo -e "${GREEN}Listando spiders disponíveis...${NC}"
    curl -s http://localhost/scrapyd/listspiders.json?project=assessorai_crawler | python3 -m json.tool
}

function build_images() {
    echo -e "${GREEN}Reconstruindo imagens...${NC}"
    docker-compose build
    echo -e "${GREEN}Imagens reconstruídas!${NC}"
}

function clean_containers() {
    echo -e "${YELLOW}Removendo containers...${NC}"
    docker-compose down
    echo -e "${GREEN}Containers removidos! (dados preservados)${NC}"
}

function purge_all() {
    echo -e "${RED}ATENÇÃO: Isso irá remover TODOS os dados!${NC}"
    read -p "Tem certeza? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        echo -e "${RED}Removendo tudo...${NC}"
        docker-compose down -v
        echo -e "${GREEN}Tudo removido!${NC}"
    else
        echo -e "${YELLOW}Operação cancelada${NC}"
    fi
}

# Main
case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs "$2"
        ;;
    status)
        show_status
        ;;
    shell)
        shell_access
        ;;
    deploy)
        deploy_project
        ;;
    run)
        run_spider "$2"
        ;;
    list)
        list_spiders
        ;;
    build)
        build_images
        ;;
    clean)
        clean_containers
        ;;
    purge)
        purge_all
        ;;
    *)
        print_usage
        exit 1
        ;;
esac
