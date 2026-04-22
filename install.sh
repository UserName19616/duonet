#!/bin/bash
# install.sh - Установка DuoNet (распаковка на месте)

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ARCHIVE="duonet.tar.gz"

echo -e "${GREEN}=========================================="
echo "DuoNet - Установка"
echo -e "==========================================${NC}"

# ============================================
# 1. РАСПАКОВКА (если нужно)
# ============================================
echo -e "\n${YELLOW}[1/6] Проверка файлов проекта...${NC}"

# Если проект уже распакован
if [ -f "start_server.sh" ] && [ -d "src" ]; then
    echo -e "${GREEN}✓ Проект уже распакован${NC}"
else
    # Проверяем наличие архива
    if [ ! -f "$ARCHIVE" ]; then
        echo -e "${RED}✗ Архив $ARCHIVE не найден!${NC}"
        exit 1
    fi

    echo -e "${BLUE}ℹ Распаковка архива...${NC}"
    tar -xzf "$ARCHIVE"

    # Если архив содержит папку DuoNet/ - перемещаем содержимое
    if [ -d "DuoNet" ]; then
        echo -e "${BLUE}ℹ Перемещение файлов из DuoNet/ ...${NC}"
        for item in DuoNet/* DuoNet/.[!.]*; do
            [ -e "$item" ] && mv "$item" . 2>/dev/null || true
        done
        rm -rf DuoNet
    fi

    echo -e "${GREEN}✓ Архив распакован${NC}"
fi

# ============================================
# 2. ПРОВЕРКА СТРУКТУРЫ
# ============================================
echo -e "\n${YELLOW}[2/6] Проверка структуры проекта...${NC}"

# Проверяем наличие Устава (правильный путь!)
if [ ! -f "src/common/charter/templates/charter_ru.txt" ]; then
    echo -e "${RED}✗ Устав не найден в src/common/charter/templates/${NC}"
    echo -e "${YELLOW}Проверяем альтернативные пути...${NC}"

    # Ищем в распакованных файлах
    FOUND=$(find . -name "charter_ru.txt" -type f 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        echo -e "${BLUE}ℹ Найден: $FOUND${NC}"
        mkdir -p src/common/charter/templates
        cp "$FOUND" src/common/charter/templates/
        echo -e "${GREEN}✓ Устав скопирован${NC}"
    else
        echo -e "${RED}✗ Устав отсутствует в архиве! Архив поврежден.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Устав найден${NC}"
fi

# Создаем необходимые директории
for dir in logs data/ssl; do
    [ ! -d "$dir" ] && mkdir -p "$dir" && echo -e "${GREEN}✓ Создана директория: $dir${NC}"
done

# ============================================
# 3. ПРОВЕРКА ЗАВИСИМОСТЕЙ
# ============================================
echo -e "\n${YELLOW}[3/6] Проверка зависимостей...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 не установлен${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $(python3 --version)${NC}"

if ! command -v openssl &> /dev/null; then
    echo -e "${RED}✗ OpenSSL не установлен${NC}"
    exit 1
fi
echo -e "${GREEN}✓ OpenSSL${NC}"

# ============================================
# 4. ВИРТУАЛЬНОЕ ОКРУЖЕНИЕ
# ============================================
echo -e "\n${YELLOW}[4/6] Настройка окружения Python...${NC}"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ Виртуальное окружение создано${NC}"
fi

source venv/bin/activate

# Установка зависимостей
if [ -f "requirements.txt" ]; then
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo -e "${GREEN}✓ Зависимости установлены${NC}"
fi

# ============================================
# 5. КОНФИГУРАЦИЯ
# ============================================
echo -e "\n${YELLOW}[5/6] Настройка конфигурации...${NC}"

# .env файл
if [ ! -f ".env" ]; then
    JWT_SECRET=$(openssl rand -base64 32)
    cat > .env << EOF
JWT_SECRET_KEY=$JWT_SECRET
API_HOST=127.0.0.1
API_PORT=8443
RENDEZVOUS_URL=http://127.0.0.1:9878
DUONET_DB_PATH=duonet.db
LOG_LEVEL=INFO
EOF
    chmod 600 .env
    echo -e "${GREEN}✓ .env создан${NC}"
fi

# SSL сертификат
if [ ! -f "data/ssl/cert.pem" ]; then
    openssl req -x509 -newkey rsa:4096 -keyout data/ssl/key.pem -out data/ssl/cert.pem -days 365 -nodes \
        -subj "/C=RU/ST=Moscow/L=Moscow/O=DuoNet/CN=localhost" \
        -addext "subjectAltName = DNS:localhost, IP:127.0.0.1" 2>/dev/null
    chmod 600 data/ssl/key.pem
    chmod 644 data/ssl/cert.pem
    echo -e "${GREEN}✓ SSL сертификат создан${NC}"
fi

# ============================================
# 6. ПРАВА ДОСТУПА
# ============================================
echo -e "\n${YELLOW}[6/6] Настройка прав...${NC}"

# Даём права на выполнение всем .sh скриптам
for script in *.sh; do
    if [ -f "$script" ]; then
        chmod +x "$script"
        echo -e "${GREEN}✓ $script${NC}"
    fi
done

echo -e "${GREEN}✓ Права настроены${NC}"

# ============================================
# ЗАВЕРШЕНИЕ
# ============================================
echo ""
echo -e "${GREEN}=========================================="
echo "✅ Установка завершена!"
echo -e "==========================================${NC}"
echo ""
echo -e "${BLUE}Запуск сервера:  ./start_server.sh${NC}"
echo -e "${BLUE}TUI клиент:      ./run_tui.sh${NC}"
echo -e "${BLUE}Веб-клиент:      ./run_web.sh${NC}"
echo ""
echo -e "${YELLOW}⚠️  При первом запуске сервера может потребоваться время${NC}"
