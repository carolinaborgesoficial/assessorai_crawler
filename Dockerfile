FROM python:3.10-slim

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Criar diretório de trabalho
WORKDIR /app

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o projeto
COPY . .

# Criar diretórios necessários
RUN mkdir -p /app/logs /app/items /app/downloads /app/dbs

# Expor portas
# 6800 - scrapyd
# 5000 - scrapydweb
EXPOSE 6800 5000

# O comando será definido no docker-compose para cada serviço
CMD ["scrapyd"]
