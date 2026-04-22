#!/bin/bash
# generate_modules_list.sh - Создание полного дампа всех модулей проекта
# Включает: Python, HTML, CSS, JS, документация (md/txt), скрипты (sh), конфиги

OUTPUT_FILE="project_dump_$(date +%Y%m%d_%H%M%S).txt"
echo "Generating modules list to $OUTPUT_FILE..."

# Очищаем файл
> "$OUTPUT_FILE"

# Добавляем заголовок
echo "================================================================================" >> "$OUTPUT_FILE"
echo "# DuoNet Project - Full Modules Dump (Python + HTML + CSS + JS + Docs + Scripts)" >> "$OUTPUT_FILE"
echo "# Generated: $(date)" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Структура каталогов
echo "================================================================================" >> "$OUTPUT_FILE"
echo "# DIRECTORY STRUCTURE" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Генерируем дерево файлов (игнорируя venv, __pycache__, logs, data, *.db, .pids, .env)
# Добавлены .css и .js
find . -type f \
    \( -name "*.py" -o \
       -name "*.html" -o \
       -name "*.css" -o \
       -name "*.js" -o \
       -name "*.md" -o \
       -name "*.txt" -o \
       -name "*.sh" -o \
       -name "*.yaml" -o \
       -name "*.yml" -o \
       -name "*.toml" -o \
       -name "*.cfg" -o \
       -name "*.ini" \) \
    | grep -v "venv" \
    | grep -v "__pycache__" \
    | grep -v "logs" \
    | grep -v "data" \
    | grep -v "\.db" \
    | grep -v "\.pids" \
    | grep -v "\.env" \
    | grep -v "node_modules" \
    | grep -v "\.git" \
    | sort >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Функция для определения типа блока кода
get_code_block_type() {
    local file="$1"
    if [[ "$file" == *.py ]]; then
        echo "python"
    elif [[ "$file" == *.html ]]; then
        echo "html"
    elif [[ "$file" == *.css ]]; then
        echo "css"
    elif [[ "$file" == *.js ]]; then
        echo "javascript"
    elif [[ "$file" == *.sh ]]; then
        echo "bash"
    elif [[ "$file" == *.yaml ]] || [[ "$file" == *.yml ]]; then
        echo "yaml"
    elif [[ "$file" == *.toml ]]; then
        echo "toml"
    elif [[ "$file" == *.cfg ]] || [[ "$file" == *.ini ]]; then
        echo "ini"
    elif [[ "$file" == *.md ]]; then
        echo "markdown"
    else
        echo "text"
    fi
}

# Обходим все найденные файлы
# Добавлены .css и .js
find . -type f \
    \( -name "*.py" -o \
       -name "*.html" -o \
       -name "*.css" -o \
       -name "*.js" -o \
       -name "*.md" -o \
       -name "*.txt" -o \
       -name "*.sh" -o \
       -name "*.yaml" -o \
       -name "*.yml" -o \
       -name "*.toml" -o \
       -name "*.cfg" -o \
       -name "*.ini" \) \
    | grep -v "venv" \
    | grep -v "__pycache__" \
    | grep -v "logs" \
    | grep -v "data" \
    | grep -v "\.db" \
    | grep -v "\.pids" \
    | grep -v "\.env" \
    | grep -v "node_modules" \
    | grep -v "\.git" \
    | sort | while read -r file; do

    echo "" >> "$OUTPUT_FILE"
    echo "================================================================================" >> "$OUTPUT_FILE"
    echo "# FILE: $file" >> "$OUTPUT_FILE"
    echo "================================================================================" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"

    # Определяем тип языка для подсветки синтаксиса
    CODE_TYPE=$(get_code_block_type "$file")
    echo '```'"$CODE_TYPE" >> "$OUTPUT_FILE"
    cat "$file" >> "$OUTPUT_FILE"
    echo '```' >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
done

echo "" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"
echo "# END OF DUMP" >> "$OUTPUT_FILE"
echo "================================================================================" >> "$OUTPUT_FILE"

echo "Done! Output saved to $OUTPUT_FILE"

# Выводим статистику
echo ""
echo "Statistics:"
echo "  Python files: $(find . -name "*.py" | grep -v "venv" | grep -v "__pycache__" | wc -l)"
echo "  HTML files: $(find . -name "*.html" | grep -v "venv" | grep -v "__pycache__" | wc -l)"
echo "  CSS files: $(find . -name "*.css" | grep -v "venv" | grep -v "__pycache__" | wc -l)"
echo "  JavaScript files: $(find . -name "*.js" | grep -v "venv" | grep -v "__pycache__" | grep -v "node_modules" | wc -l)"
echo "  Documentation (md/txt): $(find . -name "*.md" -o -name "*.txt" | grep -v "venv" | grep -v "__pycache__" | wc -l)"
echo "  Scripts (sh): $(find . -name "*.sh" | grep -v "venv" | grep -v "__pycache__" | wc -l)"
echo "  Configs: $(find . -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.cfg" -o -name "*.ini" | grep -v "venv" | grep -v "__pycache__" | wc -l)"

# Общая статистика
TOTAL=$(( $(find . -name "*.py" | grep -v "venv" | grep -v "__pycache__" | wc -l) + \
          $(find . -name "*.html" | grep -v "venv" | grep -v "__pycache__" | wc -l) + \
          $(find . -name "*.css" | grep -v "venv" | grep -v "__pycache__" | wc -l) + \
          $(find . -name "*.js" | grep -v "venv" | grep -v "__pycache__" | grep -v "node_modules" | wc -l) + \
          $(find . -name "*.md" -o -name "*.txt" | grep -v "venv" | grep -v "__pycache__" | wc -l) + \
          $(find . -name "*.sh" | grep -v "venv" | grep -v "__pycache__" | wc -l) + \
          $(find . -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.cfg" -o -name "*.ini" | grep -v "venv" | grep -v "__pycache__" | wc -l) ))
echo ""
echo "  TOTAL files: $TOTAL"
