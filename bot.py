import os
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional

from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
import aiofiles

import config

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class LogMonitorBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.last_position = 0
        self.last_check_time = None
        self.subscribers: Set[int] = set()
        
        # Регистрация обработчиков команд
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("subscribe", self.subscribe_command))
        self.application.add_handler(CommandHandler("unsubscribe", self.unsubscribe_command))
        
        # Запуск фоновой задачи для мониторинга логов
        self.application.job_queue.run_repeating(
            self.check_logs_task,
            interval=config.CHECK_INTERVAL,
            first=10
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_message = (
            "👋 *Добро пожаловать в Log Monitor Bot!*\n\n"
            "Я помогу вам отслеживать важные события в логах.\n\n"
            "*Доступные команды:*\n"
            "/subscribe - подписаться на уведомления\n"
            "/unsubscribe - отписаться от уведомлений\n"
            "/status - проверить статус мониторинга\n"
            "/help - показать это сообщение\n\n"
            f"*Отслеживаемые события:*\n"
        )
        
        # Добавляем информацию о настроенных паттернах
        for name, pattern_config in config.LOG_PATTERNS.items():
            if pattern_config['enabled']:
                welcome_message += f"{pattern_config['color']} {pattern_config['description']}\n"
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        await self.start_command(update, context)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status"""
        chat_id = update.effective_chat.id
        is_subscribed = chat_id in self.subscribers
        
        status_message = (
            f"📊 *Статус мониторинга*\n\n"
            f"🟢 Бот активен\n"
            f"📁 Файл логов: {config.LOG_FILE}\n"
            f"⏱ Интервал проверки: {config.CHECK_INTERVAL} сек\n"
            f"📝 Подписка: {'✅ активна' if is_subscribed else '❌ не активна'}\n"
            f"👥 Всего подписчиков: {len(self.subscribers)}\n\n"
            f"*Отслеживаемые паттерны:*\n"
        )
        
        for name, pattern_config in config.LOG_PATTERNS.items():
            if pattern_config['enabled']:
                status_message += f"  {pattern_config['color']} {pattern_config['description']}\n"
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
    
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /subscribe"""
        chat_id = update.effective_chat.id
        self.subscribers.add(chat_id)
        await update.message.reply_text(
            "✅ Вы успешно подписались на уведомления!\n"
            "Я буду сообщать вам о всех важных событиях в логах."
        )
    
    async def unsubscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /unsubscribe"""
        chat_id = update.effective_chat.id
        if chat_id in self.subscribers:
            self.subscribers.remove(chat_id)
            await update.message.reply_text(
                "❌ Вы отписались от уведомлений.\n"
                "Чтобы возобновить получение уведомлений, используйте /subscribe"
            )
        else:
            await update.message.reply_text(
                "Вы не подписаны на уведомления.\n"
                "Используйте /subscribe для подписки."
            )
    
    async def check_logs_task(self, context: ContextTypes.DEFAULT_TYPE):
        """Фоновая задача для проверки логов"""
        if not self.subscribers:
            return
        
        try:
            log_file = Path(config.LOG_FILE)
            if not log_file.exists():
                logger.warning(f"Файл логов {config.LOG_FILE} не найден")
                return
            
            await self.check_file_size()
            
            new_logs = await self.read_new_logs(log_file)
            
            if new_logs:
                # Фильтруем логи по паттернам
                filtered_logs = self.filter_logs(new_logs)
                
                if filtered_logs:
                    await self.send_notifications(filtered_logs, context)
        
        except Exception as e:
            logger.error(f"Ошибка при проверке логов: {e}")
    
    async def read_new_logs(self, log_file: Path) -> List[str]:
        """Читает только новые записи из файла логов"""
        try:
            # Проверяем, не был ли файл перезаписан
            if self.last_position > log_file.stat().st_size:
                self.last_position = 0
                logger.info("Файл логов был перезаписан, начинаем чтение с начала")
            
            async with aiofiles.open(log_file, 'r', encoding='utf-8') as f:
                # Перемещаемся к последней прочитанной позиции
                await f.seek(self.last_position)
                
                # Читаем новые строки
                new_content = await f.read()
                
                # Обновляем позицию
                self.last_position = await f.tell()
                
                if new_content:
                    # Разделяем на строки и фильтруем пустые
                    lines = [line.strip() for line in new_content.split('\n') if line.strip()]
                    return lines
                return []
        
        except Exception as e:
            logger.error(f"Ошибка при чтении файла: {e}")
            return []
    
    def filter_logs(self, logs: List[str]) -> Dict[str, List[str]]:
        """Фильтрует логи по заданным паттернам"""
        filtered = {}
        
        for log in logs:
            if not log or not isinstance(log, str):
                continue
            
            log_lower = log.lower()  # Для регистронезависимого поиска
            
            for name, pattern in config.COMPILED_PATTERNS.items():
                if pattern.search(log) or pattern.search(log_lower):
                    if name not in filtered:
                        filtered[name] = []
                    filtered[name].append(log)
                    break  # Лог попал в первую подходящую категорию
        
        return filtered
    
    async def send_notifications(self, filtered_logs: Dict[str, List[str]], context: ContextTypes.DEFAULT_TYPE):
        """Отправляет уведомления подписчикам"""
        if not filtered_logs or not self.subscribers:
            return
        
        # Формируем сообщение
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"📨 *Новые события в логах*\n"
        message += f"🕐 {timestamp}\n"
        message += f"📊 Всего событий: {sum(len(logs) for logs in filtered_logs.values())}\n\n"
        
        for name, logs in filtered_logs.items():
            if name in config.LOG_PATTERNS:
                config_entry = config.LOG_PATTERNS[name]
                emoji = config_entry['color']
                description = config_entry['description']
                
                message += f"{emoji} *{description}* ({len(logs)})\n"
                
                # Добавляем первые 3 лога каждой категории
                for i, log in enumerate(logs[:3], 1):
                    # Обрезаем слишком длинные логи
                    if len(log) > 80:
                        log = log[:77] + "..."
                    # Экранируем специальные символы для Markdown
                    log = log.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
                    message += f"  {i}. `{log}`\n"
                
                if len(logs) > 3:
                    message += f"  ... и еще {len(logs) - 3}\n"
                
                message += "\n"
        
        # Если сообщение слишком длинное, обрезаем
        if len(message) > 4000:
            message = message[:4000] + "...\n\n(Сообщение обрезано из-за длины)"
        
        # Отправляем всем подписчикам
        failed_subscribers = []
        for chat_id in self.subscribers:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"Уведомление отправлено пользователю {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {chat_id}: {e}")
                # Если пользователь заблокировал бота, удаляем его из подписчиков
                if "blocked" in str(e).lower() or "forbidden" in str(e).lower():
                    failed_subscribers.append(chat_id)
        
        # Удаляем проблемных подписчиков
        for chat_id in failed_subscribers:
            self.subscribers.discard(chat_id)
            logger.info(f"Пользователь {chat_id} удален из подписчиков")
    
    async def check_file_size(self):
        """Проверяет размер файла логов и при необходимости очищает"""
        try:
            log_file = Path(config.LOG_FILE)
            if log_file.exists() and log_file.stat().st_size > config.MAX_LOG_SIZE:
                # Создаем директорию для архивов, если её нет
                archive_dir = Path("log_archives")
                archive_dir.mkdir(exist_ok=True)
                
                # Архивируем старые логи
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                archive_name = archive_dir / f"logs_{timestamp}.log"
                
                # Копируем содержимое в архив
                async with aiofiles.open(log_file, 'r', encoding='utf-8') as source:
                    content = await source.read()
                    async with aiofiles.open(archive_name, 'w', encoding='utf-8') as target:
                        await target.write(content)
                
                # Очищаем основной файл
                async with aiofiles.open(log_file, 'w', encoding='utf-8') as f:
                    await f.write("")
                
                # Сбрасываем позицию чтения
                self.last_position = 0
                
                logger.info(f"Файл логов превысил лимит, создан архив: {archive_name}")
        
        except Exception as e:
            logger.error(f"Ошибка при проверке размера файла: {e}")
    
    def run(self):
        """Запускает бота"""
        logger.info("Запуск бота...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def generate_test_logs():
    """Генерирует тестовые логи для демонстрации"""
    import random
    from datetime import datetime, timedelta
    
    # Уровни логирования и сообщения
    log_entries = [
        ("INFO", "Пользователь user123 вошел в систему"),
        ("ERROR", "Не удалось подключиться к базе данных: timeout"),
        ("WARNING", "Высокая загрузка CPU: 95%"),
        ("CRITICAL", "Сервис payment-service недоступен"),
        ("INFO", "API запрос /api/users выполнен успешно"),
        ("DB_ERROR", "Таймаут подключения к БД (connection timeout)"),
        ("API_RATE_LIMIT", "Превышен лимит запросов для ключа abc123"),
        ("ERROR", "Ошибка валидации данных: invalid email"),
        ("WARNING", "Недостаточно места на диске: 500MB free"),
        ("INFO", "Кэш обновлен для ключа user_preferences"),
        ("ERROR", "Исключение NullPointerException в методе processOrder"),
        ("WARNING", "Медленный запрос: GET /api/products took 5.3s"),
        ("CRITICAL", "Потеря соединения с Kafka"),
        ("DB_ERROR", "Deadlock обнаружен при обновлении таблицы orders"),
        ("API_ERROR", "Ошибка авторизации: invalid token"),
    ]
    
    with open(config.LOG_FILE, 'w', encoding='utf-8') as f:
        for i in range(50):
            level, message = random.choice(log_entries)
            # Генерируем случайное время за последние 2 часа
            minutes_ago = random.randint(0, 120)
            timestamp = datetime.now() - timedelta(minutes=minutes_ago)
            
            # Форматируем запись лога
            log_entry = f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {level} - {message} [request_id={random.randint(1000, 9999)}]\n"
            f.write(log_entry)
    
    print(f"✅ Сгенерирован тестовый файл {config.LOG_FILE} с 50 записями")
    print("📁 Примеры записей:")
    with open(config.LOG_FILE, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f.readlines()[:5]):
            print(f"   {i+1}. {line.strip()}")

def main():
    env_file = Path('.env')
    if not env_file.exists():
        with open('.env', 'w') as f:
            f.write('TELEGRAM_BOT_TOKEN=your_bot_token_here\n')
        print("⚠️ Создан файл .env. Пожалуйста, добавьте ваш токен бота в этот файл.")
        print("   Получить токен можно у @BotFather в Telegram")
        return
    
    # Загружаем токен из переменных окружения
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Если токен не загрузился, читаем из файла напрямую
    if not token or token == 'your_bot_token_here':
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('TELEGRAM_BOT_TOKEN='):
                        token = line.strip().split('=')[1].strip()
                        break
        except Exception as e:
            print(f"❌ Ошибка чтения файла .env: {e}")
    
    if not token or token == 'your_bot_token_here':
        print("❌ Ошибка: Неверный или отсутствующий токен бота в файле .env")
        print("   Пожалуйста, отредактируйте файл .env и добавьте правильный токен")
        return
    
    # Генерируем тестовые логи
    generate_test_logs()
    
    print("\n🚀 Запуск бота...")
    print("📱 Нажмите Ctrl+C для остановки\n")
    
    bot = LogMonitorBot(token)
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()