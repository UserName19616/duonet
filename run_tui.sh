#!/bin/bash
# run_tui.sh - Запуск TUI клиента DuoNet (аналог run.sh из предыдущей версии)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Принудительная установка режима FULL
export DUONET_MODE=full
export DUONET_DB_PATH=duonet.db

echo -e "${GREEN}=========================================="
echo "DuoNet - TUI клиент"
echo -e "==========================================${NC}"

# Параметры
API_PORT=8443
RENDEZVOUS_PORT=9878
SSL_DIR="data/ssl"
CERT_FILE="$SSL_DIR/cert.pem"
KEY_FILE="$SSL_DIR/key.pem"
RENDEZVOUS_PID_FILE=".pids_rendezvous"
API_PID_FILE=".pids_api"

# Функция для очистки БД
clean_databases() {
    echo -e "${YELLOW}Очистка баз данных...${NC}"
    rm -f duonet.db duonet_server.db duonet_client.db
    echo -e "${GREEN}✓ Базы данных удалены${NC}"
}

# Проверка аргументов
if [[ "$1" == "--clean" ]] || [[ "$1" == "-c" ]]; then
    clean_databases
    shift
fi

# Активация виртуального окружения
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo -e "${RED}✗ Виртуальное окружение не найдено. Запустите ./setup.sh${NC}"
    exit 1
fi

# Проверка .env
if [ ! -f ".env" ]; then
    echo -e "${RED}✗ Файл .env не найден. Запустите ./setup.sh${NC}"
    exit 1
fi

# Загрузка переменных окружения
set -a
source .env
set +a

# Функция проверки порта
check_port() {
    if command -v lsof &>/dev/null; then
        lsof -i:$1 &>/dev/null && return 0 || return 1
    else
        timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$1" 2>/dev/null && return 0 || return 1
    fi
}

# Функция остановки процессов
stop_processes() {
    echo -e "${YELLOW}Остановка старых процессов...${NC}"

    # Останавливаем по PID файлам
    if [ -f "$RENDEZVOUS_PID_FILE" ]; then
        RENDEZVOUS_PID=$(cat "$RENDEZVOUS_PID_FILE")
        kill $RENDEZVOUS_PID 2>/dev/null || true
        rm -f "$RENDEZVOUS_PID_FILE"
    fi

    if [ -f "$API_PID_FILE" ]; then
        API_PID=$(cat "$API_PID_FILE")
        kill $API_PID 2>/dev/null || true
        rm -f "$API_PID_FILE"
    fi

    pkill -f "uvicorn.*src.server.api.main" 2>/dev/null || true
    pkill -f "python.*rendezvous_server" 2>/dev/null || true
    pkill -f "src.client.app" 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}✓ Процессы остановлены${NC}"
}

# Генерация SSL сертификата (если нет)
echo -e "\n${YELLOW}[1/8] Проверка SSL сертификата...${NC}"
mkdir -p "$SSL_DIR"
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "🔐 Генерация самоподписного SSL сертификата..."
    openssl req -x509 -newkey rsa:4096 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -days 365 \
        -nodes \
        -subj "/C=RU/ST=Moscow/L=Moscow/O=DuoNet/CN=localhost" \
        -addext "subjectAltName = DNS:localhost, IP:127.0.0.1" 2>/dev/null
    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
    echo -e "${GREEN}✓ SSL сертификат создан${NC}"
else
    echo -e "${GREEN}✓ SSL сертификат уже существует${NC}"
fi

# Создание баз данных если их нет
echo -e "\n${YELLOW}[2/8] Проверка баз данных...${NC}"

# Проверяем и создаём duonet.db
if [ ! -f "duonet.db" ]; then
    echo "📁 Создание duonet.db..."
    sqlite3 duonet.db "VACUUM;" 2>/dev/null || true
    chmod 600 duonet.db 2>/dev/null || true
    echo -e "${GREEN}✓ duonet.db создана${NC}"
else
    echo -e "${GREEN}✓ duonet.db уже существует${NC}"
fi

# Проверяем и создаём duonet_server.db
if [ ! -f "duonet_server.db" ]; then
    echo "📁 Создание duonet_server.db..."
    python3 -c "from src.storage.server_db import get_server_db; get_server_db()" 2>/dev/null || true
    chmod 600 duonet_server.db 2>/dev/null || true
    echo -e "${GREEN}✓ duonet_server.db создана${NC}"
else
    echo -e "${GREEN}✓ duonet_server.db уже существует${NC}"
fi

# Проверка наличия серверного аккаунта
echo -e "\n${YELLOW}[3/8] Проверка серверного аккаунта...${NC}"
if [ ! -f "duonet.db" ]; then
    echo -e "${YELLOW}⚠️ База данных duonet.db не найдена. Будет создана при первой регистрации.${NC}"
    SERVER_COUNT=0
else
    SERVER_COUNT=$(sqlite3 duonet.db "SELECT COUNT(*) FROM accounts WHERE is_server=1" 2>/dev/null || echo "0")
fi

if [ "$SERVER_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}⚠️ Серверный аккаунт не найден.${NC}"
    echo ""
    echo "   Сначала создайте серверный аккаунт через веб-интерфейс:"
    echo "   1. Запустите ./start_server.sh в другом терминале"
    echo "   2. Откройте https://localhost:$API_PORT"
    echo "   3. Пройдите регистрацию с типом аккаунта 'Сервер'"
    echo "   4. Затем запустите этот скрипт"
    echo ""
    exit 1
fi

# Остановка старых процессов
stop_processes

# Проверка портов
echo -e "\n${YELLOW}[4/8] Проверка портов...${NC}"
PORT_ERROR=0
if check_port $RENDEZVOUS_PORT; then
    echo -e "${RED}✗ Порт $RENDEZVOUS_PORT (Rendezvous) занят${NC}"
    PORT_ERROR=1
fi
if check_port $API_PORT; then
    echo -e "${RED}✗ Порт $API_PORT (API) занят${NC}"
    PORT_ERROR=1
fi
if [ $PORT_ERROR -eq 1 ]; then
    echo -e "${RED}Освободите порты и повторите запуск${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Все порты свободны${NC}"

# Проверка, не запущен ли уже Rendezvous
echo -e "\n${YELLOW}[5/8] Проверка Rendezvous...${NC}"
RENDEZVOUS_ALREADY_RUNNING=0

# Проверка по PID файлу
if [ -f "$RENDEZVOUS_PID_FILE" ]; then
    RENDEZVOUS_PID=$(cat "$RENDEZVOUS_PID_FILE")
    if kill -0 $RENDEZVOUS_PID 2>/dev/null; then
        echo -e "${GREEN}✓ Rendezvous уже запущен (PID: $RENDEZVOUS_PID)${NC}"
        RENDEZVOUS_ALREADY_RUNNING=1
    else
        rm -f "$RENDEZVOUS_PID_FILE"
    fi
fi

# Дополнительная проверка через health endpoint
if [ $RENDEZVOUS_ALREADY_RUNNING -eq 0 ] && curl -s http://127.0.0.1:$RENDEZVOUS_PORT/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Rendezvous уже запущен (health check)${NC}"
    RENDEZVOUS_ALREADY_RUNNING=1
fi

# Запуск Rendezvous сервера (если не запущен)
if [ $RENDEZVOUS_ALREADY_RUNNING -eq 0 ]; then
    echo -e "${YELLOW}Запуск Rendezvous сервера...${NC}"
    mkdir -p logs
    python3 -c "
import asyncio
import logging
from src.server.network.rendezvous.rendezvous_server import RendezvousServer

logging.basicConfig(level=logging.INFO)
async def main():
    server = RendezvousServer()
    await server.start(host='127.0.0.1', port=$RENDEZVOUS_PORT)
    print('Rendezvous server ready')
    await asyncio.Event().wait()
asyncio.run(main())
" > logs/rendezvous.log 2>&1 &
    RENDEZVOUS_PID=$!
    echo $RENDEZVOUS_PID > "$RENDEZVOUS_PID_FILE"
    sleep 2
    if kill -0 $RENDEZVOUS_PID 2>/dev/null; then
        echo -e "${GREEN}✓ Rendezvous сервер запущен (PID: $RENDEZVOUS_PID)${NC}"
    else
        echo -e "${RED}✗ Ошибка запуска Rendezvous сервера${NC}"
        cat logs/rendezvous.log
        exit 1
    fi
else
    echo -e "${GREEN}✓ Используется существующий Rendezvous${NC}"
fi

# Запуск API сервера с HTTPS
echo -e "\n${YELLOW}[6/8] Запуск API сервера (HTTPS)...${NC}"
uvicorn src.server.api.main:app \
    --host 127.0.0.1 \
    --port $API_PORT \
    --ssl-keyfile="$KEY_FILE" \
    --ssl-certfile="$CERT_FILE" \
    > logs/api.log 2>&1 &
API_PID=$!
echo $API_PID > "$API_PID_FILE"
sleep 3

if kill -0 $API_PID 2>/dev/null; then
    echo -e "${GREEN}✓ API сервер запущен (PID: $API_PID)${NC}"
else
    echo -e "${RED}✗ Ошибка запуска API сервера${NC}"
    cat logs/api.log
    exit 1
fi

# Проверка API
echo -e "\n${YELLOW}Проверка API...${NC}"
if curl -k -s https://127.0.0.1:$API_PORT/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API отвечает${NC}"
else
    echo -e "${RED}✗ API не отвечает. Проверьте logs/api.log${NC}"
fi

# Проверка Rendezvous
echo -e "${YELLOW}Проверка Rendezvous...${NC}"
if curl -s http://127.0.0.1:$RENDEZVOUS_PORT/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Rendezvous отвечает${NC}"
else
    echo -e "${RED}✗ Rendezvous не отвечает. Проверьте logs/rendezvous.log${NC}"
fi

# Регистрация NAT-сервера в Rendezvous
echo -e "\n${YELLOW}[7/8] Регистрация NAT-сервера в Rendezvous...${NC}"
python3 -c "
import sqlite3
from src.server.network.rendezvous.rendezvous_client import RendezvousClient

conn = sqlite3.connect('duonet.db')
cursor = conn.cursor()
cursor.execute('SELECT server_id FROM accounts WHERE is_server = 1 LIMIT 1')
row = cursor.fetchone()
conn.close()

if row:
    server_id = row[0]
    # Извлекаем регион из server_id
    parts = server_id.split('.')
    region = parts[1] if len(parts) >= 2 else 'ru'

    client = RendezvousClient('http://127.0.0.1:$RENDEZVOUS_PORT')
    result = client.register_server(
        public_id=server_id,
        server_type='nat',
        region=region,
        ws_url=f'wss://127.0.0.1:$API_PORT/ws',
        capacity=100,
        provides_proxy=True
    )
    if result:
        print('✅ NAT-сервер зарегистрирован в Rendezvous')
    else:
        print('⚠️ Ошибка регистрации NAT-сервера')
else:
    print('⚠️ Серверный аккаунт не найден, регистрация пропущена')
"

# Запуск TUI клиента
echo -e "\n${BLUE}[8/8] Запуск TUI клиента...${NC}"
echo ""
echo -e "${YELLOW}Информация:${NC}"
echo "  • API URL: https://127.0.0.1:$API_PORT"
echo "  • Swagger: https://127.0.0.1:$API_PORT/docs"
echo "  • Rendezvous: http://127.0.0.1:$RENDEZVOUS_PORT"
echo ""
echo -e "${YELLOW}Советы:${NC}"
echo "  • Регистрация: создайте новый аккаунт"
echo "  • Сид-фраза: можно указать email для восстановления"
echo "  • Для входа в существующий аккаунт используйте --account"
echo "  • Пример: python3 -m src.client.app --account @XXXX.ru --password yourpass"
echo "  • Выход из клиента: Ctrl+Q"
echo "  • Остановка всех серверов: Ctrl+C в этом окне"
echo ""

# Запуск TUI
python3 -m src.client.app "$@"

# Остановка серверов при выходе из TUI
echo -e "\n${YELLOW}Остановка серверов...${NC}"
stop_processes
echo -e "${GREEN}✓ Серверы остановлены${NC}"
