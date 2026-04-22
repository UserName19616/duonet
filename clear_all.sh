#!/bin/bash
# clear_all.sh - Полная очистка проекта
# Использование: ./clear_all.sh [--full] [--no-archive] [--yes]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

FULL_CLEAN=false
CREATE_ARCHIVE=true
NO_CONFIRM=false
ARCHIVE_NAME="duonet.tar.gz"

while [[ $# -gt 0 ]]; do
    case $1 in
        --full) FULL_CLEAN=true; shift ;;
        --no-archive) CREATE_ARCHIVE=false; shift ;;
        --yes|-y) NO_CONFIRM=true; shift ;;
        --archive-name) ARCHIVE_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Очистка проекта DuoNet"
            echo "  --full               Полная очистка (включая .env, сертификаты)"
            echo "  --no-archive         Не создавать архив"
            echo "  --archive-name NAME  Имя архива"
            echo "  --yes, -y            Автоматически подтверждать"
            exit 0
            ;;
        *) echo -e "${RED}Неизвестная опция: $1${NC}"; exit 1 ;;
    esac
done

echo "=========================================="
echo "DuoNet - Очистка проекта"
echo "=========================================="

# 1. Остановка процессов
echo -e "\n${YELLOW}[1/5] Остановка процессов...${NC}"
for pidfile in .pids_rendezvous .pids_api .pids_web .pids_tui; do
    [ -f "$pidfile" ] && kill $(cat "$pidfile") 2>/dev/null || true
    rm -f "$pidfile"
done
pkill -f "rendezvous_server" 2>/dev/null || true
pkill -f "uvicorn.*src.server.api.main" 2>/dev/null || true
pkill -f "src.client.app" 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Процессы остановлены${NC}"

# 2. Создание архива
if [ "$CREATE_ARCHIVE" = true ]; then
    echo -e "\n${BLUE}[2/5] Создание архива...${NC}"
    ARCHIVE_ITEMS=()
    [ -d "src" ] && ARCHIVE_ITEMS+=("src")
    [ -d "tests" ] && ARCHIVE_ITEMS+=("tests")
    [ -d "docs" ] && ARCHIVE_ITEMS+=("docs")
    [ -f "requirements.txt" ] && ARCHIVE_ITEMS+=("requirements.txt")
    [ -f "pytest.ini" ] && ARCHIVE_ITEMS+=("pytest.ini")

    # Все скрипты кроме clear_all.sh и install.sh
    for script in *.sh; do
        [ -f "$script" ] && [ "$script" != "clear_all.sh" ] && [ "$script" != "install.sh" ] && ARCHIVE_ITEMS+=("$script")
    done

    if [ ${#ARCHIVE_ITEMS[@]} -gt 0 ]; then
        tar -czf "$ARCHIVE_NAME" "${ARCHIVE_ITEMS[@]}" 2>/dev/null
        echo -e "${GREEN}✓ Архив создан: $ARCHIVE_NAME ($(du -h "$ARCHIVE_NAME" | cut -f1))${NC}"
    fi
fi

# 3. Подтверждение
if [ "$NO_CONFIRM" = false ]; then
    echo ""
    echo -e "${RED}ВНИМАНИЕ! Будут удалены:${NC}"
    echo "  • Виртуальное окружение (venv/)"
    echo "  • Базы данных (*.db)"
    echo "  • Логи (logs/)"
    echo "  • Кэш Python"
    [ "$FULL_CLEAN" = true ] && echo "  • .env, SSL сертификаты, PID файлы"
    echo ""
    read -p "Введите 'yes' для подтверждения: " confirmation
    [ "$confirmation" != "yes" ] && echo "Операция отменена." && exit 0
fi

# 4. Удаление
echo -e "\n${BLUE}[3/5] Удаление venv и БД...${NC}"
[ -d "venv" ] && rm -rf venv && echo -e "${GREEN}✓ venv/ удалён${NC}"
for db in *.db duonet.db duonet_server.db test.db; do
    [ -f "$db" ] && rm -f "$db" && echo -e "${GREEN}✓ $db удалён${NC}"
done
for tempfile in *.db-journal *.db-wal *.db-shm; do
    [ -f "$tempfile" ] && rm -f "$tempfile" && echo -e "${GREEN}✓ $tempfile удалён${NC}"
done

echo -e "\n${BLUE}[4/5] Удаление временных файлов...${NC}"
[ -d "logs" ] && rm -rf logs && echo -e "${GREEN}✓ logs/ удалён${NC}"
[ -d "data" ] && [ "$FULL_CLEAN" = true ] && rm -rf data && echo -e "${GREEN}✓ data/ удалён${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo -e "${GREEN}✓ Кэш Python очищен${NC}"

if [ "$FULL_CLEAN" = true ]; then
    [ -f ".env" ] && rm -f .env && echo -e "${GREEN}✓ .env удалён${NC}"
    for pidfile in .pids_*; do
        [ -f "$pidfile" ] && rm -f "$pidfile" && echo -e "${GREEN}✓ $pidfile удалён${NC}"
    done
    [ -d "scripts" ] && rm -rf scripts && echo -e "${GREEN}✓ scripts/ удалён${NC}"
fi

# 5. Удаление скриптов (кроме себя и install.sh)
if [ "$FULL_CLEAN" = true ]; then
    echo -e "\n${BLUE}[5/5] Удаление скриптов...${NC}"
    for script in *.sh; do
        if [ -f "$script" ] && [ "$script" != "clear_all.sh" ] && [ "$script" != "install.sh" ]; then
            rm -f "$script"
            echo -e "${GREEN}✓ $script удалён${NC}"
        fi
    done
fi

echo ""
echo -e "${GREEN}=========================================="
echo "✅ Очистка завершена!"
echo -e "==========================================${NC}"
if [ "$CREATE_ARCHIVE" = true ] && [ -f "$ARCHIVE_NAME" ]; then
    echo -e "\n${BLUE}📦 Архив сохранён: $ARCHIVE_NAME${NC}"
    echo -e "${YELLOW}Для восстановления: tar -xzf $ARCHIVE_NAME && ./install.sh${NC}"
fi
echo -e "\n${YELLOW}Для установки: ./install.sh${NC}"
