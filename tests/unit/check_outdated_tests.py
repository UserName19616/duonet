# scripts/check_outdated_tests.py
#!/usr/bin/env python3
"""
Скрипт для анализа пропущенных тестов и генерации плана обновления.
"""

import re
import subprocess
from pathlib import Path
from collections import defaultdict

def parse_test_log(log_path: str = "test_log.txt"):
    """Парсит лог тестов и группирует пропущенные."""
    if not Path(log_path).exists():
        print(f"Log file {log_path} not found")
        return

    skipped_by_file = defaultdict(list)
    current_file = None

    with open(log_path, 'r') as f:
        for line in f:
            # Ищем название файла
            file_match = re.match(r'tests/unit/([^.]+\.py)::', line)
            if file_match:
                current_file = file_match.group(1)

            # Ищем пропущенные тесты
            if 'SKIPPED' in line and current_file:
                test_match = re.search(r'::(\w+)', line)
                if test_match:
                    test_name = test_match.group(1)
                    skipped_by_file[current_file].append(test_name)

    # Выводим отчёт
    print("\n" + "="*60)
    print("SKIPPED TESTS BY FILE")
    print("="*60)

    for file_name, tests in sorted(skipped_by_file.items()):
        print(f"\n📄 {file_name}: {len(tests)} skipped")
        for test in tests[:5]:  # Показываем первые 5
            print(f"   - {test}")
        if len(tests) > 5:
            print(f"   ... and {len(tests) - 5} more")

    print("\n" + "="*60)
    print(f"TOTAL SKIPPED: {sum(len(t) for t in skipped_by_file.values())}")
    print("="*60)

    return skipped_by_file

def generate_update_plan(skipped_by_file):
    """Генерирует план обновления."""
    print("\n📋 RECOMMENDED UPDATE ORDER:\n")

    # Приоритет по количеству пропущенных
    sorted_files = sorted(
        skipped_by_file.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for i, (file_name, tests) in enumerate(sorted_files, 1):
        priority = "🔴 HIGH" if len(tests) > 10 else "🟡 MEDIUM" if len(tests) > 3 else "🟢 LOW"
        print(f"{i}. {priority} - {file_name} ({len(tests)} tests)")

if __name__ == "__main__":
    skipped = parse_test_log()
    if skipped:
        generate_update_plan(skipped)
