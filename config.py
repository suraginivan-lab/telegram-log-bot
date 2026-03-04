import re
from pathlib import Path

# Конфигурация с регулярными выражениями для фильтрации логов
LOG_PATTERNS = {
    'errors': {
        'pattern': r'ERROR|CRITICAL|FATAL',
        'description': 'Критические ошибки',
        'color': '🔴',
        'enabled': True
    },
    'warnings': {
        'pattern': r'WARNING|WARN',
        'description': 'Предупреждения',
        'color': '🟡',
        'enabled': True
    },
    'database': {
        'pattern': r'DB_ERROR|CONNECTION_FAILED|TIMEOUT',
        'description': 'Ошибки базы данных',
        'color': '🔵',
        'enabled': True
    },
    'api': {
        'pattern': r'API_*|RATE_LIMIT|UNAUTHORIZED',
        'description': 'API события',
        'color': '🟣',
        'enabled': True
    }
}

# Путь к файлу логов
LOG_FILE = "logs.log"

# Настройки бота
CHECK_INTERVAL = 60  # Интервал проверки логов в секундах
MAX_LOG_SIZE = 1024 * 1024  # Максимальный размер файла логов (1 МБ)

COMPILED_PATTERNS = {
    name: re.compile(config['pattern'], re.IGNORECASE)
    for name, config in LOG_PATTERNS.items()
    if config['enabled']
}