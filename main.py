"""
Тренажер азбуки Морзе
Flet 0.70.0
Генерація звуку через numpy/scipy
"""
import flet as ft
import time
import random
import threading
import numpy as np
from scipy.io import wavfile
from pathlib import Path
import tempfile
import json
import os
import atexit
import warnings
import base64
import io
import sqlite3
import hashlib
from datetime import datetime
import logging

# Налаштування логування
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('morse_trainer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константи
INITIAL_AUDIO_DELAY = 0.3  # Затримка для перших символів (браузер ініціалізується)
NORMAL_AUDIO_DELAY = 0.15  # Звичайна затримка між символами
INPUT_POLL_INTERVAL = 0.05  # Інтервал перевірки вводу (50мс)
CHARACTER_SPACE_PAUSE = 0.25  # Пауза між символами в звичайному режимі
WORD_SYMBOL_PAUSE = 0.1  # Пауза між символами в слові
AUDIO_SAMPLE_RATE = 44100  # Частота дискретизації
AUDIO_FREQUENCY = 800  # Частота тону (Hz)
AUDIO_VOLUME = 0.5  # Гучність (50%)
AUDIO_FADE_SAMPLES = 0.01  # Тривалість затухання (10мс)
BASE_DIT_DURATION = 0.08  # Базова тривалість крапки
CHALLENGE_STREAK_THRESHOLD = 5  # Кількість правильних для нового рівня
CHALLENGE_SPEED_STEP = 0.1  # Крок збільшення швидкості
MAX_SPEED_MULTIPLIER = 2.0  # Максимальна швидкість
WEAK_SYMBOLS_LIMIT = 10  # Максимум проблемних символів для тренування


class Database:
    """Клас для роботи з базою даних"""
    def __init__(self, db_name="morse_trainer.db"):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self):
        """Отримати з'єднання з БД"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row  # Для зручності роботи з рядками
        return conn
    
    def init_database(self):
        """Ініціалізація бази даних - створення таблиць"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблиця користувачів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблиця досягнень
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                wpm REAL DEFAULT 0,
                accuracy REAL DEFAULT 0,
                time_taken REAL DEFAULT 0,
                symbols_completed INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                incorrect_answers INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        conn.commit()
        
        # Створюємо адміна, якщо його ще немає
        cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
        admin_exists = cursor.fetchone()
        if not admin_exists:
            admin_password_hash = self.hash_password("admin")
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                ("admin", admin_password_hash)
            )
            conn.commit()
            logger.info("✅ Створено адміністратора: логін 'admin', пароль 'admin'")
        
        conn.close()
    
    def hash_password(self, password):
        """Хешування пароля"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register_user(self, username, password):
        """Реєстрація нового користувача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            password_hash = self.hash_password(password)
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash)
            )
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            return True, user_id, "Користувача успішно зареєстровано!"
        except sqlite3.IntegrityError:
            conn.close()
            return False, None, "Користувач з таким ім'ям вже існує!"
        except Exception as e:
            conn.close()
            return False, None, f"Помилка реєстрації: {str(e)}"
    
    def login_user(self, username, password):
        """Вхід користувача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = self.hash_password(password)
        cursor.execute(
            "SELECT id, username FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return True, dict(user), "Вхід успішний!"
        else:
            return False, None, "Невірний логін або пароль!"
    
    def save_achievement(self, user_id, mode, score=0, wpm=0, accuracy=0, time_taken=0, 
                        symbols_completed=0, correct_answers=0, incorrect_answers=0):
        """Збереження досягнення користувача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO achievements 
            (user_id, mode, score, wpm, accuracy, time_taken, symbols_completed, 
             correct_answers, incorrect_answers)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, mode, score, wpm, accuracy, time_taken, symbols_completed, 
              correct_answers, incorrect_answers))
        conn.commit()
        conn.close()
    
    def get_user_stats(self, user_id, mode=None):
        """Отримати статистику користувача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if mode:
            cursor.execute("""
                SELECT * FROM achievements 
                WHERE user_id = ? AND mode = ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id, mode))
        else:
            cursor.execute("""
                SELECT * FROM achievements 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    
    def get_best_result(self, user_id, mode):
        """Отримати найкращий результат користувача для режиму"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if mode == "speed_test":
            cursor.execute("""
                SELECT * FROM achievements 
                WHERE user_id = ? AND mode = ?
                ORDER BY wpm DESC, accuracy DESC
                LIMIT 1
            """, (user_id, mode))
        elif mode == "time_attack":
            cursor.execute("""
                SELECT * FROM achievements 
                WHERE user_id = ? AND mode = ?
                ORDER BY score DESC, accuracy DESC
                LIMIT 1
            """, (user_id, mode))
        else:
            cursor.execute("""
                SELECT * FROM achievements 
                WHERE user_id = ? AND mode = ?
                ORDER BY score DESC
                LIMIT 1
            """, (user_id, mode))
        
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    def get_all_users(self):
        """Отримати всіх користувачів (для адміна)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, created_at FROM users ORDER BY created_at DESC")
        users = cursor.fetchall()
        conn.close()
        return [dict(user) for user in users]
    
    def update_user(self, user_id, new_username=None, new_password=None):
        """Оновити дані користувача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if new_username:
                cursor.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
            if new_password:
                password_hash = self.hash_password(new_password)
                cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            conn.commit()
            conn.close()
            return True, "Користувача успішно оновлено!"
        except sqlite3.IntegrityError:
            conn.close()
            return False, "Користувач з таким ім'ям вже існує!"
        except Exception as e:
            conn.close()
            return False, f"Помилка оновлення: {str(e)}"
    
    def delete_user(self, user_id):
        """Видалити користувача та всі його досягнення"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Спочатку видаляємо досягнення
            cursor.execute("DELETE FROM achievements WHERE user_id = ?", (user_id,))
            # Потім видаляємо користувача
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True, "Користувача успішно видалено!"
        except Exception as e:
            conn.close()
            return False, f"Помилка видалення: {str(e)}"
    
    def is_admin(self, username):
        """Перевірка чи користувач є адміном"""
        return username.lower() == "admin"


class MorseTrainer:
    def __init__(self):
        # Ініціалізуємо базу даних
        self.db = Database()
        
        # Поточний користувач
        self.current_user = None  # {"id": int, "username": str}
        self.is_logged_in = False
        
        # Завантажуємо дані з JSON
        self.load_morse_data()
        
        # Цифри та літери для тренування
        self.digits = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
        self.letters = [
            "А", "Б", "В", "Г", "Д", "Е", "Ж", "З", "И", "Й",
            "К", "Л", "М", "Н", "О", "П", "Р", "С", "Т", "У",
            "Ф", "Х", "Ц", "Ш", "Щ", "Ы", "Ь", "Э", "Ю", "Я"
        ]
    
    def clear_all_dialogs(self):
        """Очистити всі діалоги з overlay"""
        if not hasattr(self, 'page') or self.page is None:
            return
        # Видаляємо всі AlertDialog з overlay
        all_dialogs = [d for d in self.page.overlay if isinstance(d, ft.AlertDialog)]
        for dialog in all_dialogs:
            dialog.open = False
            # Видаляємо всі входження діалогу з overlay (може бути кілька копій)
            while dialog in self.page.overlay:
                try:
                    self.page.overlay.remove(dialog)
                except (ValueError, AttributeError):
                    break  # Якщо діалог вже видалено або overlay порожній
        self.page.update()
        
    def load_morse_data(self):
        """Завантажує дані морзянки з JSON файлу"""
        try:
            with open('morse_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Розбиваємо на окремі словники
            self.morse_codes = {}
            self.mnemonics = {}
            
            for symbol, info in data.items():
                self.morse_codes[symbol] = info['code']
                self.mnemonics[symbol] = info['mnemonic']
                
            print(f"✅ Завантажено {len(self.morse_codes)} символів з morse_data.json")
        except FileNotFoundError:
            print("⚠️ Файл morse_data.json не знайдено!")
            self.morse_codes = {}
            self.mnemonics = {}
        except Exception as e:
            print(f"⚠️ Помилка завантаження morse_data.json: {e}")
            self.morse_codes = {}
            self.mnemonics = {}
    
        # Маппінг клавіш: англійська клавіша → російська літера
        # Стандартна російська розкладка ЙЦУКЕН
        self.key_mapping = {
            # Верхній ряд
            'Q': 'Й', 'W': 'Ц', 'E': 'У', 'R': 'К', 'T': 'Е', 'Y': 'Н',
            'U': 'Г', 'I': 'Ш', 'O': 'Щ', 'P': 'З', '[': 'Х', ']': 'Ъ',
            # Середній ряд
            'A': 'Ф', 'S': 'Ы', 'D': 'В', 'F': 'А', 'G': 'П', 'H': 'Р',
            'J': 'О', 'K': 'Л', 'L': 'Д', ';': 'Ж', "'": 'Э',
            # Нижній ряд
            'Z': 'Я', 'X': 'Ч', 'C': 'С', 'V': 'М', 'B': 'И', 'N': 'Т',
            'M': 'Ь', ',': 'Б', '.': 'Ю',
            # Цифри залишаються як є
            '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
            '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
        }
        
        # Зворотній маппінг для зручності
        self.reverse_key_mapping = {}
        for eng, rus in self.key_mapping.items():
            if rus not in self.reverse_key_mapping:
                self.reverse_key_mapping[rus] = []
            self.reverse_key_mapping[rus].append(eng)
        
        # Словники для чекбоксів (стан)
        self.digit_checkboxes = {}
        self.letter_checkboxes = {}
        
        # Словники для контейнерів (візуальні елементи)
        self.digit_containers = {}
        self.letter_containers = {}
        
        # Аудіо контроли для відтворення
        self.audio_controls = []
        self.current_audio_index = 0
        self.is_playing = False
        
        # Синхронізація потоків
        self.input_event = threading.Event()  # Подія для очікування вводу
        
        # Тимчасові файли для очищення
        self.temp_audio_files = []
        self.temp_files_lock = threading.Lock()
        
        # Використовуємо data URI замість файлів для веб-хостингу
        # На веб-хостингу (Render, Railway тощо) тимчасові файли недоступні через браузер
        # Тому використовуємо data URI для веб-режиму
        import os
        is_web_hosting = os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORT")
        self.use_data_uri = bool(is_web_hosting)  # True для веб-хостингу, False для локального запуску
        
        # Режими роботи
        self.training_mode = False  # False = просте відтворення, True = режим тренування
        self.training_type = "normal"  # normal, words, challenge, weak_spots
        
        # Швидкість відтворення (коефіцієнт для пауз)
        self.speed_multiplier = 1.0  # 0.5 = повільно, 1.0 = нормально, 2.0 = швидко
        
        # Частота звуку (Hz)
        self.audio_frequency = 800  # За замовчуванням 800 Гц
        
        # Статистика
        self.correct_answers = 0
        self.incorrect_answers = 0
        self.current_symbol = None  # Символ що зараз очікується
        self.current_word = None  # Слово що зараз очікується (для режиму Слова)
        
        # Статистика по символах (для режиму Слабкі місця)
        self.symbol_stats = {}  # {symbol: {"correct": 0, "incorrect": 0}}
        
        # Режим Виклик
        self.challenge_correct_streak = 0  # Серія правильних відповідей
        self.challenge_level = 1  # Поточний рівень швидкості
        
        # Режим Швидкість (Speed Test)
        self.speed_test_target = 20  # Цільова кількість символів
        self.speed_test_completed = 0  # Поточна кількість пройдених символів
        self.speed_test_start_time = None  # Час початку тесту
        self.speed_test_wpm = 0  # Words Per Minute
        
        # Режим Таймер (Time Attack)
        self.time_attack_duration = 60  # Тривалість в секундах
        self.time_attack_start_time = None  # Час початку
        self.time_attack_remaining_time = 60  # Залишок часу
        self.time_attack_timer_running = False
        
        # Слова для тренування
        self.training_words = [
            "СОС", "МАМА", "ПАПА", "ДОМ", "КІТ", "СОБАКА", "МОРЕ", "СОНЦЕ",
            "ВОДА", "ЗЕМЛЯ", "НЕБО", "ДЕРЕВО", "КВІТКА", "ПТАХ", "РИБА",
            "АВТО", "ПОЇЗД", "ЛІТАК", "КОРАБЕЛЬ", "МІСТО", "СЕЛО", "ШКОЛА",
            "УЧИТЕЛЬ", "УЧЕНЬ", "КНИГА", "ОЛІВЕЦЬ", "СТІЛ", "СТІЛЕЦЬ",
            "ВІКНО", "ДВЕРІ", "СТІНА", "ПІДЛОГА", "СТЕЛЯ", "ЛЮСТРА", "ЛАМПА"
        ]
        
        # UI елементи
        self.main_content = None
        self.table_content = None
        self.show_table = False
        
        # Реєструємо очищення при виході
        atexit.register(self.cleanup_temp_files)
        
    def get_selected_symbols(self):
        """Отримати список вибраних символів"""
        selected = []
        
        # Додаємо вибрані цифри
        for digit, checkbox in self.digit_checkboxes.items():
            if checkbox.value:
                selected.append(digit)
        
        # Додаємо вибрані літери
        for letter, checkbox in self.letter_checkboxes.items():
            if checkbox.value:
                selected.append(letter)
        
        return selected
    
    def get_weak_symbols(self):
        """Отримати символи з найбільшою кількістю помилок"""
        selected = self.get_selected_symbols()
        
        if not self.symbol_stats:
            return selected
        
        # Рахуємо помилковість для кожного символу
        error_rates = {}
        for symbol, stats in self.symbol_stats.items():
            total = stats.get("correct", 0) + stats.get("incorrect", 0)
            if total > 0:
                error_rate = stats.get("incorrect", 0) / total
                error_rates[symbol] = error_rate
        
        # Сортуємо за помилковістю
        sorted_symbols = sorted(error_rates.items(), key=lambda x: x[1], reverse=True)
        
        # Беремо топ проблемних символів
        weak_symbols = [sym for sym, rate in sorted_symbols[:WEAK_SYMBOLS_LIMIT]]
        
        # Якщо є вибрані символи - фільтруємо тільки їх
        if selected:
            weak_symbols = [s for s in weak_symbols if s in selected]
        
        # Якщо немає проблемних - повертаємо всі вибрані
        return weak_symbols if weak_symbols else selected
    
    def get_random_word(self):
        """Отримати рандомне слово для тренування"""
        return random.choice(self.training_words)
    
    def time_attack_timer(self):
        """Таймер для режиму Time Attack"""
        while self.time_attack_timer_running and self.is_playing:
            if self.time_attack_start_time:
                elapsed = time.time() - self.time_attack_start_time
                self.time_attack_remaining_time = max(0, self.time_attack_duration - elapsed)
                
                # Оновлюємо статистику кожну секунду
                if int(self.time_attack_remaining_time) != int(self.time_attack_remaining_time + 0.1):
                    self.update_stats_display()
                    self.page.update()
                
                if self.time_attack_remaining_time <= 0:
                    # Час вийшов - зупиняємо відтворення
                    self.is_playing = False
                    self.time_attack_timer_running = False
                    self.input_event.set()  # Пробуджуємо потік
                    self.update_stats_display()
                    self.page.update()
                    break
            
            time.sleep(0.1)  # Оновлюємо кожні 100мс
    
    def save_test_result(self):
        """Збереження результату тесту в БД"""
        if not self.is_logged_in or not self.current_user:
            return
        
        user_id = self.current_user['id']
        mode = self.training_type
        
        # Розраховуємо параметри залежно від режиму
        if mode == "speed_test":
            if self.speed_test_start_time:
                elapsed = time.time() - self.speed_test_start_time
                wpm = (self.speed_test_completed / 5) / (elapsed / 60) if elapsed > 0 else 0
                accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                self.db.save_achievement(
                    user_id=user_id,
                    mode=mode,
                    score=self.speed_test_completed,
                    wpm=wpm,
                    accuracy=accuracy,
                    time_taken=elapsed,
                    symbols_completed=self.speed_test_completed,
                    correct_answers=self.correct_answers,
                    incorrect_answers=self.incorrect_answers
                )
        elif mode == "time_attack":
            accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
            self.db.save_achievement(
                user_id=user_id,
                mode=mode,
                score=self.correct_answers,
                wpm=0,  # Для time_attack WPM не застосовується
                accuracy=accuracy,
                time_taken=self.time_attack_duration,
                symbols_completed=self.correct_answers + self.incorrect_answers,
                correct_answers=self.correct_answers,
                incorrect_answers=self.incorrect_answers
            )
        elif mode in ["challenge", "normal", "words", "weak_spots"]:
            accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
            self.db.save_achievement(
                user_id=user_id,
                mode=mode,
                score=self.correct_answers,
                wpm=0,
                accuracy=accuracy,
                time_taken=0,
                symbols_completed=self.correct_answers + self.incorrect_answers,
                correct_answers=self.correct_answers,
                incorrect_answers=self.incorrect_answers
            )
    
    def on_start_stop_click(self, e):
        """Обробник кнопки Старт/Стоп"""
        if not self.is_playing:
            # СТАРТ - почати відтворення
            selected = self.get_selected_symbols()
            
            if not selected:
                # Показуємо повідомлення, якщо нічого не вибрано
                self.status_text.value = "⚠️ Виберіть хоча б один символ!"
                self.page.update()
                return
            
            # Ініціалізуємо режими перед стартом
            if self.training_mode:
                if self.training_type == "speed_test":
                    self.speed_test_start_time = time.time()
                    self.speed_test_completed = 0
                    self.speed_test_wpm = 0
                elif self.training_type == "time_attack":
                    self.time_attack_start_time = time.time()
                    self.time_attack_remaining_time = self.time_attack_duration
                    self.time_attack_timer_running = True
                    # Запускаємо таймер в окремому потоці
                    timer_thread = threading.Thread(target=self.time_attack_timer, daemon=True)
                    timer_thread.start()
            
            # Починаємо відтворення
            self.is_playing = True
            self.input_event.clear()  # Скидаємо подію
            self.status_text.value = f"▶️ Відтворюю ({len(selected)} символів)..."
            self.start_button.text = "⏹️ СТОП"
            self.start_button.bgcolor = "#F44336"  # червона кнопка
            self.page.update()
            
            # Запускаємо відтворення в окремому потоці
            play_thread = threading.Thread(target=self.play_symbols_loop, args=(selected,), daemon=True)
            play_thread.start()
        else:
            # СТОП - зупинити відтворення
            self.is_playing = False
            self.input_event.set()  # Пробуджуємо потік якщо він чекає
            
            # Зупиняємо таймер для режиму Time Attack
            if self.training_type == "time_attack":
                self.time_attack_timer_running = False
            
            # Показуємо результати для режимів з тестами
            if self.training_type == "speed_test" and self.speed_test_start_time:
                elapsed = time.time() - self.speed_test_start_time
                if elapsed > 0:
                    wpm = (self.speed_test_completed / 5) / (elapsed / 60)
                    accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                    self.status_text.value = f"✅ Тест завершено! WPM: {wpm:.1f} | Точність: {accuracy:.1f}% | Час: {elapsed:.1f}с"
                    # Зберігаємо результат якщо користувач залогінений
                    if self.is_logged_in:
                        self.save_test_result()
                else:
                    self.status_text.value = "⏸️ Відтворення зупинено"
            elif self.training_type == "time_attack":
                accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                self.status_text.value = f"✅ Час вийшов! Правильних: {self.correct_answers} | Точність: {accuracy:.1f}%"
                # Зберігаємо результат якщо користувач залогінений
                if self.is_logged_in:
                    self.save_test_result()
            else:
                self.status_text.value = "⏸️ Відтворення зупинено"
                # Зберігаємо результат для інших режимів якщо є статистика
                if self.is_logged_in and (self.correct_answers > 0 or self.incorrect_answers > 0):
                    self.save_test_result()
            
            self.start_button.text = "▶️ СТАРТ"
            self.start_button.bgcolor = "#2196F3"  # синя кнопка
            
            # Очищаємо всі аудіо контролі після зупинки
            for audio in self.audio_controls:
                if audio in self.page.overlay:
                    self.page.overlay.remove(audio)
            self.audio_controls.clear()
            
            # Очищаємо тимчасові файли
            self.cleanup_temp_files()
            
            self.page.update()
    
    def play_symbols_loop(self, symbols):
        """Нескінченне рандомне відтворення звуків"""
        # Очищаємо старі аудіо контроли тільки при старті
        for audio in self.audio_controls:
            if audio in self.page.overlay:
                self.page.overlay.remove(audio)
        self.audio_controls.clear()
        self.page.update()
        
        # Лічильник символів (для діагностики)
        symbol_count = 0
        
        # Нескінченний цикл
        while self.is_playing:
            # Перевірка завершення тестів
            if self.training_mode:
                if self.training_type == "speed_test":
                    # Перевіряємо чи досягнуто цільову кількість символів
                    if self.speed_test_completed >= self.speed_test_target:
                        self.is_playing = False
                        elapsed = time.time() - self.speed_test_start_time if self.speed_test_start_time else 0
                        if elapsed > 0:
                            wpm = (self.speed_test_completed / 5) / (elapsed / 60)
                            accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                            self.status_text.value = f"✅ Тест завершено! WPM: {wpm:.1f} | Точність: {accuracy:.1f}% | Час: {elapsed:.1f}с"
                        self.page.update()
                        break
                elif self.training_type == "time_attack":
                    # Перевіряємо чи вийшов час
                    if self.time_attack_remaining_time <= 0:
                        self.is_playing = False
                        self.time_attack_timer_running = False
                        accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                        self.status_text.value = f"✅ Час вийшов! Правильних: {self.correct_answers} | Точність: {accuracy:.1f}%"
                        self.page.update()
                        break
            
            # Вибираємо що відтворювати залежно від режиму
            if self.training_mode and self.training_type == "words":
                # Режим Слова
                word = self.get_random_word()
                self.current_word = word
                self.current_symbol = None
                self.play_word(word)
                # Після play_word вже чекаємо на ввід, тому просто продовжуємо цикл
                continue
            else:
                # Режим Символи (normal, challenge, weak_spots, speed_test, time_attack)
                if self.training_mode and self.training_type == "weak_spots":
                    # Режим Слабкі місця - вибираємо проблемні символи
                    available_symbols = self.get_weak_symbols()
                    if not available_symbols:
                        available_symbols = symbols  # Fallback на всі вибрані
                else:
                    available_symbols = symbols
                
                symbol = random.choice(available_symbols)
                self.current_symbol = symbol
                self.current_word = None
                symbol_count += 1
                
                # Генеруємо звук програмно
                audio_file = self.generate_morse_audio(symbol)
                
                if audio_file:
                    # Отримуємо довжину згенерованого файлу
                    duration = self.calculate_symbol_duration(symbol)
                    
                    # Якщо режим тренування - активуємо ввід одразу і оновлюємо статистику
                    if self.training_mode:
                        self.input_event.clear()  # Скидаємо подію перед очікуванням вводу
                        self.update_stats_display()
                        self.page.update()
                
                    # Створюємо аудіо контрол
                    # Для веб-хостингу використовуємо data URI, для локального - файли
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=DeprecationWarning)
                        if self.use_data_uri and isinstance(audio_file, str) and audio_file.startswith("data:"):
                            # Використовуємо data URI для веб-хостингу
                            audio = ft.Audio(
                                src=audio_file,  # data URI рядок
                                autoplay=True,
                            )
                        else:
                            # Використовуємо файл для локального запуску
                            audio = ft.Audio(
                                src=str(audio_file),
                                autoplay=True,
                            )
                    self.page.overlay.append(audio)
                    self.audio_controls.append(audio)
                    self.page.update()
                    
                    # Затримка щоб аудіо встигло запуститися
                    # Для перших 2-3 символів трохи більша затримка (браузер ініціалізується)
                    if symbol_count <= 3:
                        time.sleep(INITIAL_AUDIO_DELAY)
                    else:
                        time.sleep(NORMAL_AUDIO_DELAY)
                    
                    # Якщо режим тренування - чекаємо на ввід користувача
                    if self.training_mode:
                        # Чекаємо поки користувач не введе відповідь (через Event для безпечної синхронізації)
                        if self.is_playing:
                            self.input_event.wait(timeout=None)  # Чекаємо поки не буде встановлено
                        # Без паузи - одразу наступний символ!
                    else:
                        # Звичайний режим (без перевірки)
                        # Звук вже згенерований з правильною швидкістю
                        # Додаємо фіксовану паузу між символами (character space)
                        pause = duration + CHARACTER_SPACE_PAUSE
                        time.sleep(pause)
            
            # Перевіряємо чи не зупинили
            if not self.is_playing:
                break
    
    def on_audio_state_changed(self, e):
        """Обробник зміни стану аудіо"""
        pass
    
    def play_word(self, word):
        """Відтворення слова посимвольно"""
        for i, symbol in enumerate(word):
            if not self.is_playing:
                break
            
            audio_file = self.generate_morse_audio(symbol)
            if audio_file:
                duration = self.calculate_symbol_duration(symbol)
                
                # Приховуємо попередження про deprecation
                # Для веб-хостингу використовуємо data URI, для локального - файли
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning)
                    if self.use_data_uri and isinstance(audio_file, str) and audio_file.startswith("data:"):
                        # Використовуємо data URI для веб-хостингу
                        audio = ft.Audio(src=audio_file, autoplay=True)
                    else:
                        # Використовуємо файл для локального запуску
                        audio = ft.Audio(src=str(audio_file), autoplay=True)
                self.page.overlay.append(audio)
                self.audio_controls.append(audio)
                self.page.update()
                
                # Затримка між символами в слові
                if i < len(word) - 1:
                    time.sleep(duration + WORD_SYMBOL_PAUSE)
        
        # Після відтворення всього слова - чекаємо на ввід
        if self.is_playing:
            self.input_event.clear()  # Скидаємо подію перед очікуванням вводу
            self.update_stats_display()
            # Фокусуємо поле вводу
            if hasattr(self, 'word_input_field'):
                self.word_input_field.focus()
            self.page.update()
            
            # Чекаємо на ввід (через Event для безпечної синхронізації)
            if self.is_playing:
                self.input_event.wait(timeout=None)
    
    def check_word_answer(self, input_text):
        """Перевірка відповіді для режиму Слова"""
        if not self.current_word or not input_text:
            return False
        
        # Валідація та нормалізація вводу
        input_text = str(input_text).strip().upper().replace(" ", "")
        if not input_text:
            return False
        
        # Порівнюємо без урахування регістру та пробілів
        correct = input_text == self.current_word.upper()
        
        if correct:
            self.correct_answers += 1
            self.update_stats_display()
        else:
            self.incorrect_answers += 1
            self.stats_text.value = f"📊 Слова: Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers} | ❌ Було: {self.current_word}"
        
        self.page.update()
        return correct
    
    def handle_correct_answer(self):
        """Обробка правильної відповіді (винесено для уникнення дублювання)"""
        self.correct_answers += 1
        if self.current_symbol:
            if self.current_symbol not in self.symbol_stats:
                self.symbol_stats[self.current_symbol] = {"correct": 0, "incorrect": 0}
            self.symbol_stats[self.current_symbol]["correct"] += 1
        
        # Режим Швидкість - збільшуємо лічильник пройдених символів
        if self.training_type == "speed_test":
            self.speed_test_completed += 1
        
        # Режим Виклик - збільшуємо рівень
        if self.training_type == "challenge":
            self.challenge_correct_streak += 1
            if self.challenge_correct_streak >= CHALLENGE_STREAK_THRESHOLD:
                self.challenge_level += 1
                self.challenge_correct_streak = 0
                # Збільшуємо швидкість (крок 0.1, максимум 2.0)
                self.speed_multiplier = min(1.0 + (self.challenge_level - 1) * CHALLENGE_SPEED_STEP, MAX_SPEED_MULTIPLIER)
                # Оновлюємо слайдер якщо він існує
                if hasattr(self, 'speed_slider'):
                    self.speed_slider.value = self.speed_multiplier
                    self.page.update()
        
        self.update_stats_display()
        self.page.update()
    
    def handle_incorrect_answer(self, pressed_key, mapped_key):
        """Обробка неправильної відповіді"""
        self.incorrect_answers += 1
        if self.current_symbol:
            if self.current_symbol not in self.symbol_stats:
                self.symbol_stats[self.current_symbol] = {"correct": 0, "incorrect": 0}
            self.symbol_stats[self.current_symbol]["incorrect"] += 1
        
        # Режим Виклик - скидаємо все при помилці (рівень, швидкість, серія)
        if self.training_type == "challenge":
            self.challenge_correct_streak = 0
            self.challenge_level = 1
            self.speed_multiplier = 1.0
            # Оновлюємо слайдер якщо він існує
            if hasattr(self, 'speed_slider'):
                self.speed_slider.value = 1.0
                self.page.update()
        
        display_key = mapped_key if mapped_key else pressed_key
        self.stats_text.value = f"📊 Статистика: Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers} | ❌ Було: {self.current_symbol}"
        self.page.update()
    
    def on_keyboard_event(self, e: ft.KeyboardEvent):
        """Обробник натискання клавіш"""
        # Перевіряємо тільки подію натискання (key down), ігноруємо відпускання
        if e.shift or not self.training_mode:
            return
        
        # Перевіряємо чи чекаємо на ввід (через Event)
        if self.input_event.is_set():
            return  # Вже оброблено
        
        # Режим Слова - ввід через TextField, тут нічого не робимо
        if self.training_type == "words":
            return
        
        # Режим Символи
        if not self.current_symbol:
            return
        
        # Отримуємо натиснуту клавішу
        pressed_key = e.key.upper() if e.key else None
        
        if not pressed_key or len(pressed_key) != 1:
            return
        
        # Встановлюємо подію щоб уникнути повторної обробки
        self.input_event.set()
        
        # Оновлюємо статистику по символах
        if self.current_symbol not in self.symbol_stats:
            self.symbol_stats[self.current_symbol] = {"correct": 0, "incorrect": 0}
        
        # Спочатку перевіряємо пряме співпадіння (якщо натиснули російську букву)
        if pressed_key == self.current_symbol:
            self.handle_correct_answer()
            return
        
        # Якщо не співпало - перевіряємо через маппінг (англійська → російська)
        mapped_key = self.key_mapping.get(pressed_key)
        if mapped_key and mapped_key == self.current_symbol:
            self.handle_correct_answer()
            return
        
        # Якщо і це не співпало - помилка
        self.handle_incorrect_answer(pressed_key, mapped_key)
    
    def toggle_training_mode(self, e):
        """Перемикання режиму тренування"""
        self.training_mode = e.control.value
        if self.training_mode:
            # Скидаємо статистику при увімкненні режиму
            self.correct_answers = 0
            self.incorrect_answers = 0
            self.challenge_correct_streak = 0
            self.challenge_level = 1
            self.symbol_stats = {}
            # Показуємо віджет статистики
            self.stats_text.visible = True
            # Показуємо радіобатони вибору типу тренування
            if hasattr(self, 'training_type_container'):
                self.training_type_container.visible = True
            # Показуємо поле вводу для режиму Слова
            if self.training_type == "words":
                self.word_input_field.visible = True
            self.update_stats_display()
        else:
            # Ховаємо віджет статистики
            self.stats_text.visible = False
            self.word_input_field.visible = False
            # Ховаємо радіобатони
            if hasattr(self, 'training_type_container'):
                self.training_type_container.visible = False
        self.page.update()
    
    def on_training_type_change(self, e):
        """Зміна типу тренування"""
        self.training_type = e.control.value
        # Скидаємо статистику при зміні режиму
        if self.training_mode:
            self.correct_answers = 0
            self.incorrect_answers = 0
            self.challenge_correct_streak = 0
            self.challenge_level = 1
            # Скидаємо швидкість для режиму Виклик
            if self.training_type == "challenge":
                self.speed_multiplier = 1.0
                if hasattr(self, 'speed_slider'):
                    self.speed_slider.value = 1.0
                    self.speed_slider.disabled = True  # Блокуємо слайдер в режимі Виклик
            else:
                if hasattr(self, 'speed_slider'):
                    self.speed_slider.disabled = False  # Розблоковуємо для інших режимів
            
            # Скидаємо параметри нових режимів
            if self.training_type == "speed_test":
                self.speed_test_completed = 0
                self.speed_test_start_time = None
                self.speed_test_wpm = 0
            elif self.training_type == "time_attack":
                self.time_attack_remaining_time = self.time_attack_duration
                self.time_attack_start_time = None
                self.time_attack_timer_running = False
            
            # Показуємо/ховаємо поле вводу слова та параметри режимів
            self.word_input_field.visible = (self.training_type == "words")
            if hasattr(self, 'speed_test_params'):
                self.speed_test_params.visible = (self.training_type == "speed_test")
            if hasattr(self, 'time_attack_params'):
                self.time_attack_params.visible = (self.training_type == "time_attack")
            
            self.update_stats_display()
        self.page.update()
    
    def on_word_submit(self, e):
        """Обробник вводу слова"""
        if not self.training_mode or not self.current_word:
            return
        
        # Перевіряємо чи чекаємо на ввід (через Event)
        if self.input_event.is_set():
            return  # Вже оброблено
        
        input_text = e.control.value
        if not input_text:
            return
        
        # Встановлюємо подію перед обробкою
        self.input_event.set()
        
        # Перевіряємо слово
        correct = self.check_word_answer(input_text)
        
        # Очищаємо поле
        e.control.value = ""
        self.page.update()
    
    def update_stats_display(self):
        """Оновлення відображення статистики"""
        if self.training_type == "challenge":
            self.stats_text.value = f"📊 Рівень: {self.challenge_level} | Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers}"
        elif self.training_type == "words":
            self.stats_text.value = f"📊 Слова: Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers}"
        elif self.training_type == "speed_test":
            if self.speed_test_start_time:
                elapsed = time.time() - self.speed_test_start_time
                if elapsed > 0:
                    # WPM = (символи / 5) / (хвилини) - стандартна формула
                    self.speed_test_wpm = (self.speed_test_completed / 5) / (elapsed / 60)
                else:
                    self.speed_test_wpm = 0
                self.stats_text.value = f"⚡ Швидкість: {self.speed_test_completed}/{self.speed_test_target} | WPM: {self.speed_test_wpm:.1f} | Час: {elapsed:.1f}с"
            else:
                self.stats_text.value = f"⚡ Швидкість: {self.speed_test_completed}/{self.speed_test_target} | Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers}"
        elif self.training_type == "time_attack":
            if self.time_attack_timer_running and self.time_attack_remaining_time > 0:
                self.stats_text.value = f"⏱️ Таймер: {int(self.time_attack_remaining_time)}с | Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers}"
            else:
                accuracy = (self.correct_answers / (self.correct_answers + self.incorrect_answers) * 100) if (self.correct_answers + self.incorrect_answers) > 0 else 0
                self.stats_text.value = f"⏱️ Таймер: Завершено! | Правильних: {self.correct_answers} | Точність: {accuracy:.1f}%"
        else:
            self.stats_text.value = f"📊 Статистика: Правильних: {self.correct_answers} | Помилок: {self.incorrect_answers}"
    
    def on_speed_change(self, e):
        """Зміна швидкості відтворення"""
        self.speed_multiplier = float(e.control.value)
    
    def on_frequency_change(self, e):
        """Зміна частоти звуку"""
        self.audio_frequency = int(e.control.value)
    
    def show_alphabet_table(self, e):
        """Показати таблицю азбуки Морзе"""
        print("DEBUG: Відкриваємо таблицю")
        self.show_table = True
        self.main_content.visible = False
        self.table_content.visible = True
        self.page.update()
    
    def hide_alphabet_table(self, e):
        """Сховати таблицю азбуки Морзе"""
        self.show_table = False
        self.table_content.visible = False
        self.main_content.visible = True
        self.page.update()
    
    def calculate_symbol_duration(self, symbol):
        """Розрахунок тривалості символу"""
        morse_code = self.morse_codes.get(symbol, "")
        if not morse_code:
            return 0.5
        
        dit_duration = BASE_DIT_DURATION / self.speed_multiplier
        total_duration = 0
        
        for i, char in enumerate(morse_code):
            if char == '.':
                total_duration += dit_duration
            elif char == '-':
                total_duration += dit_duration * 3
            
            # Пауза між елементами
            if i < len(morse_code) - 1:
                total_duration += dit_duration
        
        return total_duration
    
    def cleanup_temp_files(self):
        """Очищення тимчасових аудіо файлів"""
        with self.temp_files_lock:
            for file_path in self.temp_audio_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as e:
                    print(f"⚠️ Помилка видалення тимчасового файлу {file_path}: {e}")
            self.temp_audio_files.clear()
    
    def generate_morse_audio(self, symbol):
        """Генерація звуку морзянки програмно
        
        Повертає:
        - Якщо use_data_uri=True: data URI рядок (base64)
        - Якщо use_data_uri=False: шлях до тимчасового файлу
        """
        # Швидкість впливає на тривалість крапки!
        dit_duration = BASE_DIT_DURATION / self.speed_multiplier  # Швидше = коротша крапка
        
        # Морзянка для символу
        morse_code = self.morse_codes.get(symbol, "")
        if not morse_code:
            return None
        
        # Масив для зберігання звуку
        audio_data = []
        
        for i, char in enumerate(morse_code):
            if char == '.':
                duration = dit_duration
            elif char == '-':
                duration = dit_duration * 3
            else:
                continue
            
            # Генеруємо синусоїду
            t = np.linspace(0, duration, int(AUDIO_SAMPLE_RATE * duration))
            tone = np.sin(2 * np.pi * self.audio_frequency * t)
            
            # Плавне затухання на початку та кінці (envelope) - усуває клацання!
            fade_samples = int(AUDIO_SAMPLE_RATE * AUDIO_FADE_SAMPLES)
            if len(tone) > fade_samples * 2:  # Перевіряємо що звук достатньо довгий
                fade_in = np.linspace(0, 1, fade_samples)
                fade_out = np.linspace(1, 0, fade_samples)
                tone[:fade_samples] *= fade_in
                tone[-fade_samples:] *= fade_out
            
            audio_data.extend(tone)
            
            # Пауза між елементами (крім останнього)
            if i < len(morse_code) - 1:
                silence = np.zeros(int(AUDIO_SAMPLE_RATE * dit_duration))
                audio_data.extend(silence)
        
        # Конвертуємо в int16 для WAV
        audio_array = np.array(audio_data)
        audio_array = np.int16(audio_array * 32767 * AUDIO_VOLUME)
        
        if self.use_data_uri:
            # Створюємо WAV в пам'яті та конвертуємо в base64 data URI
            wav_buffer = io.BytesIO()
            wavfile.write(wav_buffer, AUDIO_SAMPLE_RATE, audio_array)
            wav_buffer.seek(0)
            
            # Конвертуємо в base64
            wav_base64 = base64.b64encode(wav_buffer.read()).decode('utf-8')
            data_uri = f"data:audio/wav;base64,{wav_base64}"
            
            return data_uri
        else:
            # Використовуємо тимчасовий файл (для сумісності з ft.Audio)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_file_path = temp_file.name
            wavfile.write(temp_file_path, AUDIO_SAMPLE_RATE, audio_array)
            temp_file.close()
            
            # Додаємо до списку для очищення
            with self.temp_files_lock:
                self.temp_audio_files.append(temp_file_path)
                # Обмежуємо кількість файлів (видаляємо старі якщо більше 50)
                if len(self.temp_audio_files) > 50:
                    old_file = self.temp_audio_files.pop(0)
                    try:
                        if os.path.exists(old_file):
                            os.remove(old_file)
                    except Exception:
                        pass
            
            return temp_file_path
    
    def select_all_digits(self, e):
        """Вибрати всі цифри"""
        for digit in self.digits:
            self.digit_checkboxes[digit].value = True
            self.digit_containers[digit].bgcolor = "#2196F3"
            self.digit_containers[digit].border = ft.border.all(2, "#2196F3")
        self.page.update()
    
    def deselect_all_digits(self, e):
        """Зняти вибір з усіх цифр"""
        for digit in self.digits:
            self.digit_checkboxes[digit].value = False
            self.digit_containers[digit].bgcolor = "transparent"
            self.digit_containers[digit].border = ft.border.all(2, "#2196F3")
        self.page.update()
    
    def select_all_letters(self, e):
        """Вибрати всі літери"""
        for letter in self.letters:
            self.letter_checkboxes[letter].value = True
            self.letter_containers[letter].bgcolor = "#2196F3"
            self.letter_containers[letter].border = ft.border.all(2, "#2196F3")
        self.page.update()
    
    def deselect_all_letters(self, e):
        """Зняти вибір з усіх літер"""
        for letter in self.letters:
            self.letter_checkboxes[letter].value = False
            self.letter_containers[letter].bgcolor = "transparent"
            self.letter_containers[letter].border = ft.border.all(2, "#2196F3")
        self.page.update()
    
    def deselect_all(self, e):
        """Зняти вибір з усіх символів"""
        for digit in self.digits:
            self.digit_checkboxes[digit].value = False
            self.digit_containers[digit].bgcolor = "transparent"
            self.digit_containers[digit].border = ft.border.all(2, "#2196F3")
        for letter in self.letters:
            self.letter_checkboxes[letter].value = False
            self.letter_containers[letter].bgcolor = "transparent"
            self.letter_containers[letter].border = ft.border.all(2, "#2196F3")
        self.page.update()
    
    def toggle_symbol(self, e, symbol):
        """Перемикання стану чекбоксу"""
        container = e.control
        # Знаходимо чекбокс для цього символу
        if symbol in self.digit_checkboxes:
            checkbox_state = self.digit_checkboxes[symbol]
        else:
            checkbox_state = self.letter_checkboxes[symbol]
        
        # Перемикаємо стан
        checkbox_state.value = not checkbox_state.value
        
        # Оновлюємо вигляд контейнера
        if checkbox_state.value:
            container.bgcolor = "#2196F3"  # синій фон
            container.border = ft.border.all(2, "#2196F3")
        else:
            container.bgcolor = "transparent"  # прозорий фон
            container.border = ft.border.all(2, "#2196F3")
        
        self.page.update()
    
    def create_symbol_checkbox(self, symbol, is_digit):
        """Створює кастомний чекбокс з символом всередині"""
        # Створюємо об'єкт для збереження стану
        class CheckboxState:
            def __init__(self):
                self.value = False
        
        checkbox_state = CheckboxState()
        
        # Створюємо контейнер-кнопку
        container = ft.Container(
            content=ft.Text(
                symbol,
                size=16,
                weight=ft.FontWeight.BOLD,
                color="#2196F3",
                text_align=ft.TextAlign.CENTER,
            ),
            width=40,
            height=40,
            border=ft.border.all(1, "#2196F3"),
            border_radius=5,
            bgcolor="transparent",
            alignment=ft.alignment.center,
            on_click=lambda e: self.toggle_symbol(e, symbol),
        )
        
        # Зберігаємо в відповідні словники
        if is_digit:
            self.digit_checkboxes[symbol] = checkbox_state
            self.digit_containers[symbol] = container
        else:
            self.letter_checkboxes[symbol] = checkbox_state
            self.letter_containers[symbol] = container
        
        return container
    
    def on_login_click(self, e):
        """Обробник кнопки Вхід"""
        username = self.login_username_field.value.strip()
        password = self.login_password_field.value
        
        if not username or not password:
            self.login_status_text.value = "⚠️ Введіть логін та пароль!"
            self.login_status_text.color = "#F44336"
            self.page.update()
            return
        
        success, user, message = self.db.login_user(username, password)
        if success:
            # СПОЧАТКУ очищаємо всі діалоги перед показом головного контенту
            self.clear_all_dialogs()
            
            # Зберігаємо логін та пароль тільки якщо увімкнено "Запам'ятати мене"
            remember_me = self._remember_me_checkbox_value.value if hasattr(self, '_remember_me_checkbox_value') else False
            self.page.client_storage.set("remember_me", remember_me)
            
            if remember_me:
                self.page.client_storage.set("saved_username", username)
                self.page.client_storage.set("saved_password", password)
            else:
                # Видаляємо збережені дані якщо чекбокс вимкнено
                self.page.client_storage.remove("saved_username")
                self.page.client_storage.remove("saved_password")
            
            self.current_user = user
            self.is_logged_in = True
            self.login_content.visible = False
            self.main_content.visible = True
            # Оновлюємо індикатор користувача та кнопку виходу
            if hasattr(self, 'user_indicator'):
                self.user_indicator.value = f"👤 {username}"
                self.user_indicator.visible = True
            if hasattr(self, 'logout_btn'):
                self.logout_btn.visible = True
            # Показуємо кнопку адмін панелі тільки для адміна
            if hasattr(self, 'admin_btn'):
                self.admin_btn.visible = self.db.is_admin(username)
            self.status_text.value = f"👤 Вітаємо, {username}!"
            self.page.update()
        else:
            self.login_status_text.value = message
            self.login_status_text.color = "#F44336"
            self.page.update()
    
    def on_register_click(self, e):
        """Обробник кнопки Реєстрація"""
        username = self.register_username_field.value.strip()
        password = self.register_password_field.value
        password_confirm = self.register_password_confirm_field.value
        
        if not username or not password:
            self.register_status_text.value = "⚠️ Введіть логін та пароль!"
            self.register_status_text.color = "#F44336"
            self.page.update()
            return
        
        if len(username) < 3:
            self.register_status_text.value = "⚠️ Логін має бути мінімум 3 символи!"
            self.register_status_text.color = "#F44336"
            self.page.update()
            return
        
        if len(password) < 4:
            self.register_status_text.value = "⚠️ Пароль має бути мінімум 4 символи!"
            self.register_status_text.color = "#F44336"
            self.page.update()
            return
        
        if password != password_confirm:
            self.register_status_text.value = "⚠️ Паролі не співпадають!"
            self.register_status_text.color = "#F44336"
            self.page.update()
            return
        
        success, user_id, message = self.db.register_user(username, password)
        if success:
            self.register_status_text.value = "✅ " + message + " Тепер увійдіть!"
            self.register_status_text.color = "#4CAF50"
            self.page.update()
        else:
            self.register_status_text.value = message
            self.register_status_text.color = "#F44336"
            self.page.update()
    
    def on_logout_click(self, e):
        """Обробник кнопки Вийти"""
        self.current_user = None
        self.is_logged_in = False
        self.main_content.visible = False
        self.login_content.visible = True
        
        # Очищаємо поля логіну тільки якщо не увімкнено "Запам'ятати мене"
        remember_me = self.page.client_storage.get("remember_me") or False
        if not remember_me:
            self.login_username_field.value = ""
            self.login_password_field.value = ""
        else:
            # Завантажуємо збережені дані
            saved_username = self.page.client_storage.get("saved_username") or ""
            saved_password = self.page.client_storage.get("saved_password") or ""
            self.login_username_field.value = saved_username
            self.login_password_field.value = saved_password
        
        self.login_status_text.value = ""
        # Ховаємо індикатор користувача та кнопку виходу
        if hasattr(self, 'user_indicator'):
            self.user_indicator.visible = False
        if hasattr(self, 'logout_btn'):
            self.logout_btn.visible = False
        if hasattr(self, 'admin_btn'):
            self.admin_btn.visible = False
        self.page.update()
    
    def show_register_dialog(self, e=None):
        """Показати діалог реєстрації"""
        logger.info("=== show_register_dialog ВИКЛИКАНО ===")
        logger.info(f"Подія: {e}")
        # Очищаємо поля перед відкриттям діалогу
        self.register_username_field.value = ""
        self.register_password_field.value = ""
        self.register_password_confirm_field.value = ""
        self.register_status_text.value = ""
        self.register_status_text.color = "#90CAF9"
        
        # Створюємо діалог спочатку (як змінну для замикання)
        register_dialog = None
        
        def close_dialog(e):
            logger.info("Закриваємо діалог реєстрації")
            if register_dialog is not None:
                register_dialog.open = False
            # Оновлюємо сторінку, щоб діалог закрився
            self.page.update()
            # Використовуємо універсальну функцію очищення
            self.clear_all_dialogs()
            # Переконуємося, що login_content видимий після закриття діалогу
            if hasattr(self, 'login_content'):
                self.login_content.visible = True
            if hasattr(self, 'main_content'):
                self.main_content.visible = self.is_logged_in
            # Оновлюємо сторінку
            self.page.update()
            logger.info("Діалог закрито")
        
        def go_to_login(e):
            """Перехід до екрану логіну після реєстрації"""
            logger.info("Перехід до екрану логіну")
            # Спочатку закриваємо діалог
            if register_dialog is not None:
                register_dialog.open = False
            # Оновлюємо сторінку, щоб діалог закрився
            self.page.update()
            # Використовуємо універсальну функцію очищення
            self.clear_all_dialogs()
            # Показуємо екран логіну
            if hasattr(self, 'login_content'):
                self.login_content.visible = True
            if hasattr(self, 'main_content'):
                self.main_content.visible = False
            # Очищаємо поля реєстрації
            self.register_username_field.value = ""
            self.register_password_field.value = ""
            self.register_password_confirm_field.value = ""
            self.register_status_text.value = ""
            # Оновлюємо сторінку
            self.page.update()
            logger.info("Перехід до логіну виконано")
        
        def register_submit_wrapper(e):
            logger.info("=== КНОПКА ЗАРЕЄСТРУВАТИСЯ НАТИСНУТА! ===")
            logger.info(f"Подія: {e}")
            logger.info(f"register_submit функція: {register_submit}")
            try:
                register_submit(e)
            except Exception as ex:
                logger.error(f"Помилка в register_submit_wrapper: {ex}", exc_info=True)
        
        def register_submit(e):
            logger.info("register_submit викликано!")
            logger.info(f"Подія: {e}")
            try:
                # Отримуємо значення з полів
                username = self.register_username_field.value.strip() if self.register_username_field.value else ""
                password = self.register_password_field.value if self.register_password_field.value else ""
                password_confirm = self.register_password_confirm_field.value if self.register_password_confirm_field.value else ""
                
                logger.info(f"Реєстрація - логін: {username}, пароль: {len(password)} символів")
                
                # Валідація
                if not username or not password:
                    logger.warning("Порожні поля логіну або пароля")
                    self.register_status_text.value = "⚠️ Введіть логін та пароль!"
                    self.register_status_text.color = "#F44336"
                    register_dialog.open = True
                    self.page.update()
                    return
                
                if len(username) < 3:
                    logger.warning(f"Логін занадто короткий: {len(username)} символів")
                    self.register_status_text.value = "⚠️ Логін має бути мінімум 3 символи!"
                    self.register_status_text.color = "#F44336"
                    register_dialog.open = True
                    self.page.update()
                    return
                
                if len(password) < 4:
                    logger.warning(f"Пароль занадто короткий: {len(password)} символів")
                    self.register_status_text.value = "⚠️ Пароль має бути мінімум 4 символи!"
                    self.register_status_text.color = "#F44336"
                    register_dialog.open = True
                    self.page.update()
                    return
                
                if password != password_confirm:
                    logger.warning("Паролі не співпадають")
                    self.register_status_text.value = "⚠️ Паролі не співпадають!"
                    self.register_status_text.color = "#F44336"
                    register_dialog.open = True
                    self.page.update()
                    return
                
                # Реєстрація
                logger.info("Викликаємо db.register_user")
                success, user_id, message = self.db.register_user(username, password)
                logger.info(f"Результат реєстрації - success: {success}, message: {message}")
                
                if success:
                    logger.info(f"Реєстрація успішна! User ID: {user_id}")
                    self.register_status_text.value = "✅ " + message + " Тепер увійдіть!"
                    self.register_status_text.color = "#4CAF50"
                    # Ховаємо кнопку "Зареєструватися", змінюємо кнопку "Скасувати" на "Увійти"
                    register_submit_btn.visible = False
                    register_cancel_btn.text = "🔐 Увійти"
                    register_cancel_btn.bgcolor = "#4CAF50"
                    register_cancel_btn.on_click = go_to_login  # Змінюємо обробник на перехід до логіну
                    register_dialog.open = True
                    self.page.update()
                else:
                    logger.warning(f"Реєстрація не вдалася: {message}")
                    self.register_status_text.value = message
                    self.register_status_text.color = "#F44336"
                    register_dialog.open = True
                    self.page.update()
            except Exception as ex:
                logger.error(f"Помилка в register_submit: {ex}", exc_info=True)
                self.register_status_text.value = f"⚠️ Помилка: {str(ex)}"
                self.register_status_text.color = "#F44336"
                register_dialog.open = True
                self.page.update()
        
        # Створюємо кнопки
        register_submit_btn = ft.ElevatedButton(
            text="Зареєструватися",
            bgcolor="#2196F3",
            color="#FFFFFF",
        )
        
        register_cancel_btn = ft.ElevatedButton(
            text="Скасувати",
            bgcolor="#757575",
            color="#FFFFFF",
        )
        
        # Встановлюємо обробники подій для кнопок
        register_submit_btn.on_click = register_submit_wrapper
        register_cancel_btn.on_click = close_dialog
        
        # Створюємо форму
        register_form = ft.Column([
                ft.Text("📝 Реєстрація", size=24, weight=ft.FontWeight.BOLD, color="#2196F3"),
                ft.Divider(height=20),
                self.register_username_field,
                self.register_password_field,
                self.register_password_confirm_field,
                self.register_status_text,
                ft.Row([
                    register_submit_btn,
                    register_cancel_btn,
                ], spacing=10),
            ], spacing=15, width=400, scroll=ft.ScrollMode.AUTO)
        
        # Створюємо title з кнопкою закриття
        register_title_row = ft.Row([
            ft.Text("Реєстрація", expand=True),
            ft.IconButton(
                icon="close",
                icon_color="#757575",
                on_click=close_dialog,
                tooltip="Закрити",
            ),
        ], tight=True)
        
        # Створюємо діалог з контентом
        register_dialog = ft.AlertDialog(
            title=register_title_row,
            content=register_form,
            open=True,
            modal=False,  # Вимкнуто modal, щоб уникнути проблем з overlay
        )
        
        logger.info("Форма створена")
        
        logger.info("Встановлюємо діалог на сторінку")
        # Додаємо діалог до overlay (якщо його там ще немає)
        if register_dialog not in self.page.overlay:
            self.page.overlay.append(register_dialog)
        register_dialog.open = True
        logger.info(f"Діалог open={register_dialog.open}, modal={register_dialog.modal}, content={register_dialog.content is not None}")
        self.page.update()
        logger.info("Діалог відкрито та оновлено сторінку")
    
    def show_admin_panel(self, e=None):
        """Показати адмінську панель для управління користувачами"""
        logger.info("=== show_admin_panel ВИКЛИКАНО ===")
        
        # Перевірка чи користувач адмін
        if not self.is_logged_in or not self.current_user:
            logger.warning("Спроба відкрити адмін панель без авторизації")
            return
        
        if not self.db.is_admin(self.current_user['username']):
            logger.warning(f"Користувач {self.current_user['username']} не є адміном")
            return
        
        # Спочатку закриваємо та видаляємо всі існуючі діалоги
        self.clear_all_dialogs()
        
        # Отримуємо всіх користувачів
        users = self.db.get_all_users()
        logger.info(f"Знайдено {len(users)} користувачів")
        
        # Створюємо таблицю користувачів
        user_rows = []
        
        # Заголовок таблиці (компактний)
        header_row = ft.DataRow(
            cells=[
                ft.DataCell(ft.Text("ID", weight=ft.FontWeight.BOLD, color="#2196F3", size=12)),
                ft.DataCell(ft.Text("Логін", weight=ft.FontWeight.BOLD, color="#2196F3", size=12)),
                ft.DataCell(ft.Text("Дата реєстрації", weight=ft.FontWeight.BOLD, color="#2196F3", size=12)),
                ft.DataCell(ft.Text("Дії", weight=ft.FontWeight.BOLD, color="#2196F3", size=12)),
            ]
        )
        user_rows.append(header_row)
        
        # Рядки з користувачами
        for user in users:
            user_id = user['id']
            username = user['username']
            created_at = user['created_at']
            
            # Форматуємо дату
            try:
                if isinstance(created_at, str):
                    date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    date_obj = created_at
                formatted_date = date_obj.strftime("%d.%m.%Y %H:%M")
            except:
                formatted_date = str(created_at)
            
            # Кнопки редагування та видалення (компактні, тільки іконки)
            edit_btn = ft.ElevatedButton(
                text="✏️",
                bgcolor="#2196F3",
                color="#FFFFFF",
                height=28,
                width=35,
                tooltip="Редагувати",
            )
            
            delete_btn = ft.ElevatedButton(
                text="🗑️",
                bgcolor="#F44336",
                color="#FFFFFF",
                height=28,
                width=35,
                tooltip="Видалити",
            )
            
            # Обробники подій
            def make_edit_handler(uid, uname):
                def edit_handler(e):
                    self.edit_user_dialog(uid, uname)
                return edit_handler
            
            def make_delete_handler(uid, uname):
                def delete_handler(e):
                    self.delete_user_dialog(uid, uname)
                return delete_handler
            
            edit_btn.on_click = make_edit_handler(user_id, username)
            delete_btn.on_click = make_delete_handler(user_id, username)
            
            # Рядок таблиці (компактний)
            data_row = ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(user_id), color="#90CAF9", size=12)),
                    ft.DataCell(ft.Text(username, color="#90CAF9", size=12)),
                    ft.DataCell(ft.Text(formatted_date, color="#90CAF9", size=11)),
                    ft.DataCell(ft.Row([edit_btn, delete_btn], spacing=3, tight=True)),
                ]
            )
            user_rows.append(data_row)
        
        # Створюємо таблицю (компактну, без зайвих рамок)
        users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("ID", size=12), numeric=True),
                ft.DataColumn(ft.Text("Логін", size=12)),
                ft.DataColumn(ft.Text("Дата реєстрації", size=12)),
                ft.DataColumn(ft.Text("Дії", size=12)),
            ],
            rows=user_rows,
            border=ft.border.all(1, "#333333"),  # Тонша темна рамка
            border_radius=5,
            heading_row_height=35,  # Компактна висота заголовка
            data_row_min_height=35,  # Компактна висота рядка
            data_row_max_height=35,
        )
        
        # Створюємо форму (компактно, без зайвих відступів)
        admin_form = ft.Column([
            ft.Row([
                ft.Text("⚙️ Адмін панель", size=20, weight=ft.FontWeight.BOLD, color="#FF9800", expand=True),
                ft.Text(f"Всього користувачів: {len(users)}", size=14, color="#90CAF9"),
            ], tight=True),
            ft.Divider(height=5, color="#333333"),
            ft.Container(
                content=users_table,
                expand=True,
                padding=5,
            ),
        ], spacing=5, expand=True, scroll=ft.ScrollMode.AUTO)
        
        # Створюємо діалог на весь екран БЕЗ modal
        # Використовуємо розміри сторінки для повноекранного відображення
        dialog_width = min(1200, self.page.width - 20) if hasattr(self.page, 'width') and self.page.width else 1200
        dialog_height = min(700, self.page.height - 20) if hasattr(self.page, 'height') and self.page.height else 700
        
        admin_dialog = ft.AlertDialog(
            title=None,  # Прибираємо title, щоб займати більше місця
            content=ft.Container(
                content=admin_form,
                width=dialog_width,
                height=dialog_height,
                padding=10,
                bgcolor="#1E1E1E",
            ),
            open=True,
            modal=False,  # Вимикаємо modal, щоб уникнути сірого overlay
            bgcolor="#1E1E1E",  # Темний фон для діалогу
        )
        
        def close_admin_dialog(e):
            logger.info("Закриваємо адмін панель")
            
            # Спочатку закриваємо ВСІ діалоги (включаючи edit/delete, які можуть бути відкриті)
            all_dialogs = [d for d in self.page.overlay if isinstance(d, ft.AlertDialog)]
            for dialog in all_dialogs:
                dialog.open = False
            
            # Закриваємо основний адмін діалог
            admin_dialog.open = False
            self.page.update()
            
            # Використовуємо універсальну функцію очищення (видаляє всі діалоги)
            self.clear_all_dialogs()
            
            # Агресивно видаляємо адмін діалог з overlay (кілька разів для надійності)
            for _ in range(10):  # Спробуємо видалити до 10 разів
                if admin_dialog in self.page.overlay:
                    try:
                        self.page.overlay.remove(admin_dialog)
                    except (ValueError, AttributeError):
                        break
                else:
                    break
            
            # Додатково перевіряємо, чи не залишилися діалоги
            remaining_dialogs = [d for d in self.page.overlay if isinstance(d, ft.AlertDialog)]
            if remaining_dialogs:
                logger.warning(f"Залишилося {len(remaining_dialogs)} діалогів після очищення, видаляємо...")
                for dialog in remaining_dialogs:
                    dialog.open = False
                    for _ in range(5):
                        if dialog in self.page.overlay:
                            try:
                                self.page.overlay.remove(dialog)
                            except (ValueError, AttributeError):
                                break
                        else:
                            break
            
            # Переконуємося, що login_content та main_content видимі
            if hasattr(self, 'login_content'):
                self.login_content.visible = not self.is_logged_in
            if hasattr(self, 'main_content'):
                self.main_content.visible = self.is_logged_in
            
            # Фінальне оновлення (кілька разів для надійності)
            self.page.update()
            # Невелика затримка та повторне оновлення для гарантії
            def final_update():
                time.sleep(0.1)
                self.page.run_task(lambda: self.page.update())
            threading.Thread(target=final_update, daemon=True).start()
            
            logger.info("Адмін панель закрито")
        
        # Додаємо кнопку закриття в заголовок форми
        close_btn = ft.IconButton(
            icon="close",
            icon_color="#FF9800",
            icon_size=24,
            on_click=close_admin_dialog,
            tooltip="Закрити",
            bgcolor="#333333",
        )
        # Оновлюємо перший рядок форми, додаючи кнопку закриття
        admin_form.controls[0].controls.append(close_btn)
        
        # Спочатку видаляємо всі інші діалоги з overlay
        self.clear_all_dialogs()
        
        # Додаємо діалог до overlay
        if admin_dialog not in self.page.overlay:
            self.page.overlay.append(admin_dialog)
        self.page.update()
        logger.info("Адмін панель відкрито")
    
    def edit_user_dialog(self, user_id, username):
        """Діалог редагування користувача"""
        logger.info(f"Редагування користувача {user_id}: {username}")
        
        # Поля для редагування
        edit_username_field = ft.TextField(
            label="Логін",
            value=username,
            width=300,
        )
        edit_password_field = ft.TextField(
            label="Новий пароль (залиште порожнім, щоб не змінювати)",
            password=True,
            can_reveal_password=True,
            width=300,
        )
        edit_status_text = ft.Text(
            "",
            size=14,
            color="#90CAF9",
            text_align=ft.TextAlign.CENTER,
        )
        
        edit_dialog = None
        
        def save_user(e):
            new_username = edit_username_field.value.strip() if edit_username_field.value else ""
            new_password = edit_password_field.value if edit_password_field.value else None
            
            if not new_username:
                edit_status_text.value = "⚠️ Введіть логін!"
                edit_status_text.color = "#F44336"
                edit_dialog.open = True
                self.page.update()
                return
            
            success, message = self.db.update_user(user_id, new_username, new_password)
            if success:
                edit_status_text.value = "✅ " + message
                edit_status_text.color = "#4CAF50"
                edit_dialog.open = True
                self.page.update()
                # Закриваємо діалог через 1 секунду та оновлюємо адмін панель
                def delayed_close():
                    time.sleep(1)
                    edit_dialog.open = False
                    # Оновлюємо сторінку, щоб діалог закрився
                    self.page.run_task(lambda: self.page.update())
                    # Видаляємо діалог з overlay
                    def remove_dialog():
                        self.clear_all_dialogs()
                        self.page.update()
                        # Оновлюємо адмін панель
                        self.show_admin_panel()
                    self.page.run_task(remove_dialog)
                threading.Thread(target=delayed_close, daemon=True).start()
            else:
                edit_status_text.value = "⚠️ " + message
                edit_status_text.color = "#F44336"
                edit_dialog.open = True
                self.page.update()
        
        def close_edit_dialog(e):
            logger.info("Закриваємо діалог редагування")
            edit_dialog.open = False
            # Оновлюємо сторінку, щоб діалог закрився
            self.page.update()
            # Використовуємо універсальну функцію очищення
            self.clear_all_dialogs()
            self.page.update()
            logger.info("Діалог редагування закрито")
        
        edit_form = ft.Column([
            ft.Text("✏️ Редагування користувача", size=20, weight=ft.FontWeight.BOLD, color="#2196F3"),
            ft.Divider(height=20),
            edit_username_field,
            edit_password_field,
            edit_status_text,
            ft.Row([
                ft.ElevatedButton(
                    text="💾 Зберегти",
                    on_click=save_user,
                    bgcolor="#2196F3",
                    color="#FFFFFF",
                ),
                ft.ElevatedButton(
                    text="Скасувати",
                    on_click=close_edit_dialog,
                    bgcolor="#757575",
                    color="#FFFFFF",
                ),
            ], spacing=10),
        ], spacing=15, width=400, scroll=ft.ScrollMode.AUTO)
        
        # Створюємо title з кнопкою закриття
        edit_title_row = ft.Row([
            ft.Text("Редагування користувача", expand=True),
            ft.IconButton(
                icon="close",
                icon_color="#757575",
                on_click=close_edit_dialog,
                tooltip="Закрити",
            ),
        ], tight=True)
        
        edit_dialog = ft.AlertDialog(
            title=edit_title_row,
            content=edit_form,
            open=True,
            modal=True,
        )
        
        if edit_dialog not in self.page.overlay:
            self.page.overlay.append(edit_dialog)
        self.page.update()
    
    def delete_user_dialog(self, user_id, username):
        """Діалог підтвердження видалення користувача"""
        logger.info(f"Видалення користувача {user_id}: {username}")
        
        delete_status_text = ft.Text(
            "",
            size=14,
            color="#90CAF9",
            text_align=ft.TextAlign.CENTER,
        )
        
        delete_dialog = None
        
        def confirm_delete(e):
            # Не можна видалити адміна
            if username.lower() == "admin":
                delete_status_text.value = "⚠️ Неможливо видалити адміністратора!"
                delete_status_text.color = "#F44336"
                delete_dialog.open = True
                self.page.update()
                return
            
            success, message = self.db.delete_user(user_id)
            if success:
                delete_status_text.value = "✅ " + message
                delete_status_text.color = "#4CAF50"
                delete_dialog.open = True
                self.page.update()
                # Закриваємо діалог через 1 секунду та оновлюємо адмін панель
                def delayed_close():
                    time.sleep(1)
                    delete_dialog.open = False
                    # Оновлюємо сторінку, щоб діалог закрився
                    self.page.run_task(lambda: self.page.update())
                    # Видаляємо діалог з overlay
                    def remove_dialog():
                        self.clear_all_dialogs()
                        self.page.update()
                        # Оновлюємо адмін панель
                        self.show_admin_panel()
                    self.page.run_task(remove_dialog)
                threading.Thread(target=delayed_close, daemon=True).start()
            else:
                delete_status_text.value = "⚠️ " + message
                delete_status_text.color = "#F44336"
                delete_dialog.open = True
                self.page.update()
        
        def close_delete_dialog(e):
            logger.info("Закриваємо діалог видалення")
            delete_dialog.open = False
            # Оновлюємо сторінку, щоб діалог закрився
            self.page.update()
            # Використовуємо універсальну функцію очищення
            self.clear_all_dialogs()
            self.page.update()
            logger.info("Діалог видалення закрито")
        
        delete_form = ft.Column([
            ft.Text("🗑️ Видалення користувача", size=20, weight=ft.FontWeight.BOLD, color="#F44336"),
            ft.Divider(height=20),
            ft.Text(f"Ви впевнені, що хочете видалити користувача '{username}'?", size=14, color="#90CAF9"),
            ft.Text("Ця дія незворотна! Всі досягнення користувача також будуть видалені.", size=12, color="#F44336"),
            delete_status_text,
            ft.Row([
                ft.ElevatedButton(
                    text="🗑️ Видалити",
                    on_click=confirm_delete,
                    bgcolor="#F44336",
                    color="#FFFFFF",
                ),
                ft.ElevatedButton(
                    text="Скасувати",
                    on_click=close_delete_dialog,
                    bgcolor="#757575",
                    color="#FFFFFF",
                ),
            ], spacing=10),
        ], spacing=15, width=400, scroll=ft.ScrollMode.AUTO)
        
        # Створюємо title з кнопкою закриття
        delete_title_row = ft.Row([
            ft.Text("Підтвердження видалення", expand=True),
            ft.IconButton(
                icon="close",
                icon_color="#757575",
                on_click=close_delete_dialog,
                tooltip="Закрити",
            ),
        ], tight=True)
        
        delete_dialog = ft.AlertDialog(
            title=delete_title_row,
            content=delete_form,
            open=True,
            modal=True,
        )
        
        if delete_dialog not in self.page.overlay:
            self.page.overlay.append(delete_dialog)
        self.page.update()
    
    def build_ui(self, page: ft.Page):
        """Побудова інтерфейсу"""
        self.page = page
        page.title = "📡 Тренажер азбуки Морзе"
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = "#000000"  # Чорний фон
        page.padding = 20
        page.window_width = 900
        page.window_height = 700
        
        # Додаємо обробник клавіатури
        page.on_keyboard_event = self.on_keyboard_event
        
        # === ЕКРАН ЛОГІНУ/РЕЄСТРАЦІЇ ===
        login_title = ft.Text(
            "📡 Тренажер азбуки Морзе",
            size=32,
            weight=ft.FontWeight.BOLD,
            color="#2196F3",
            text_align=ft.TextAlign.CENTER
        )
        
        # Поля для логіну (завантажуємо збережені дані тільки якщо було "Запам'ятати мене")
        remember_me = page.client_storage.get("remember_me") or False
        saved_username = ""
        saved_password = ""
        if remember_me:
            saved_username = page.client_storage.get("saved_username") or ""
            saved_password = page.client_storage.get("saved_password") or ""
        
        self.login_username_field = ft.TextField(
            label="Логін",
            hint_text="Введіть логін",
            width=300,
            autofocus=True,
            value=saved_username,
        )
        self.login_password_field = ft.TextField(
            label="Пароль",
            hint_text="Введіть пароль",
            password=True,
            can_reveal_password=True,
            width=300,
            value=saved_password,
        )
        
        # Чекбокс "Запам'ятати мене"
        checkbox_control = ft.Checkbox(
            value=remember_me,
        )
        self.remember_me_checkbox = ft.Row(
            [
                checkbox_control,
                ft.Text("Запам'ятати мене", size=12),
            ],
            spacing=5,
            width=300,
        )
        # Для доступу до значення чекбокса використовуємо checkbox_control
        self._remember_me_checkbox_value = checkbox_control
        self.login_status_text = ft.Text(
            "",
            size=14,
            color="#90CAF9",
            text_align=ft.TextAlign.CENTER,
        )
        
        login_btn = ft.ElevatedButton(
            text="🔐 Увійти",
            on_click=self.on_login_click,
            bgcolor="#2196F3",
            color="#FFFFFF",
            width=300,
            height=40,
        )
        
        register_btn = ft.TextButton(
            text="📝 Реєстрація",
            on_click=self.show_register_dialog,  # Використовуємо метод класу напряму
            width=300,
        )
        
        login_form = ft.Column([
            login_title,
            ft.Divider(height=30),
            self.login_username_field,
            self.login_password_field,
            self.remember_me_checkbox,
            self.login_status_text,
            login_btn,
            register_btn,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15)
        
        self.login_content = ft.Container(
            content=login_form,
            alignment=ft.alignment.center,
            expand=True,
            visible=True,
        )
        
        # === ПОЛЯ ДЛЯ РЕЄСТРАЦІЇ (створюємо заздалегідь) ===
        self.register_username_field = ft.TextField(
            label="Логін",
            hint_text="Мінімум 3 символи",
            width=300,
        )
        self.register_password_field = ft.TextField(
            label="Пароль",
            hint_text="Мінімум 4 символи",
            password=True,
            can_reveal_password=True,
            width=300,
        )
        self.register_password_confirm_field = ft.TextField(
            label="Підтвердження пароля",
            hint_text="Повторіть пароль",
            password=True,
            can_reveal_password=True,
            width=300,
        )
        self.register_status_text = ft.Text(
            "",
            size=14,
            color="#90CAF9",
            text_align=ft.TextAlign.CENTER,
        )
        
        # Заголовок
        title = ft.Text(
            "📡 Тренажер азбуки Морзе",
            size=32,
            weight=ft.FontWeight.BOLD,
            color="#2196F3"  # яскраво-синій
        )
        
        # Кнопка показати азбуку (об'ємна та стильна)
        show_alphabet_btn = ft.ElevatedButton(
            text="📖 Показати азбуку",
            on_click=self.show_alphabet_table,
            bgcolor="#2196F3",
            color="#FFFFFF",
            height=45,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                elevation=8,  # Тінь для об'ємності
                shadow_color="#1976D2",
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
            ),
        )
        
        # Кнопка виходу (якщо залогінений)
        self.logout_btn = ft.ElevatedButton(
            text="🚪 Вийти",
            on_click=self.on_logout_click,
            bgcolor="#757575",
            color="#FFFFFF",
            height=40,
            visible=False,
        )
        
        # Кнопка адмін панелі (тільки для адміна)
        self.admin_btn = ft.ElevatedButton(
            text="⚙️ Адмін панель",
            on_click=self.show_admin_panel,
            bgcolor="#FF9800",
            color="#FFFFFF",
            height=40,
            visible=False,
        )
        
        # Індикатор користувача
        self.user_indicator = ft.Text(
            "",
            size=14,
            color="#90CAF9",
            visible=False,
        )
        
        # Рядок заголовка з кнопками (з відступом справа щоб не налазила на скрол)
        title_row = ft.Row([
            title,
            ft.Container(expand=True),
            self.user_indicator,
            self.admin_btn,
            self.logout_btn,
            ft.Container(
                content=show_alphabet_btn,
                padding=ft.padding.only(right=15),  # Відступ справа від скролу
            ),
        ], spacing=10)
        
        # Статус (зверху)
        self.status_text = ft.Text(
            "Виберіть символи для тренування",
            size=16,
            color="#90CAF9"  # світло-синій
        )
        
        # Статистика (знизу)
        self.stats_text = ft.Text(
            "📊 Статистика: Правильних: 0 | Помилок: 0",
            size=14,
            color="#90CAF9",  # світло-синій
            visible=False,  # Спочатку прихована
        )
        
        # Поле вводу для режиму Слова
        self.word_input_field = ft.TextField(
            label="Введіть слово",
            hint_text="Введіть слово яке почули",
            visible=False,
            on_submit=self.on_word_submit,
            autofocus=False,
            width=300,
        )
        
        # Параметри для режиму Швидкість
        speed_test_count_field = ft.TextField(
            label="Кількість символів",
            hint_text="20",
            value="20",
            width=150,
            on_change=lambda e: setattr(self, 'speed_test_target', int(e.control.value) if e.control.value.isdigit() else 20),
        )
        self.speed_test_params = ft.Row([
            ft.Text("⚡ Параметри:", size=14, color="#90CAF9"),
            speed_test_count_field,
        ], spacing=10, visible=False)
        
        # Параметри для режиму Таймер
        time_attack_duration_field = ft.Dropdown(
            label="Тривалість",
            options=[
                ft.dropdown.Option("30", "30 секунд"),
                ft.dropdown.Option("60", "1 хвилина"),
                ft.dropdown.Option("120", "2 хвилини"),
                ft.dropdown.Option("180", "3 хвилини"),
            ],
            value="60",
            width=150,
            on_change=lambda e: setattr(self, 'time_attack_duration', int(e.control.value)),
        )
        self.time_attack_params = ft.Row([
            ft.Text("⏱️ Параметри:", size=14, color="#90CAF9"),
            time_attack_duration_field,
        ], spacing=10, visible=False)
        
        # === РЕЖИМ ТРЕНУВАННЯ ===
        training_checkbox = ft.Checkbox(
            label="🎯 Режим тренування (з перевіркою)",
            value=False,
            on_change=self.toggle_training_mode,
        )
        
        # === ТИП ТРЕНУВАННЯ ===
        training_type_radio = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="normal", label="📝 Звичайний (одиночні символи)", label_position=ft.LabelPosition.RIGHT),
                ft.Radio(value="words", label="📚 Слова (відтворення цілих слів)", label_position=ft.LabelPosition.RIGHT),
                ft.Radio(value="challenge", label="🔥 Виклик (автоматичне збільшення швидкості)", label_position=ft.LabelPosition.RIGHT),
                ft.Radio(value="weak_spots", label="🎯 Слабкі місця (фокус на проблемних символах)", label_position=ft.LabelPosition.RIGHT),
                ft.Radio(value="speed_test", label="⚡ Швидкість (фіксована кількість символів)", label_position=ft.LabelPosition.RIGHT),
                ft.Radio(value="time_attack", label="⏱️ Таймер (фіксований час)", label_position=ft.LabelPosition.RIGHT),
            ], spacing=5),
            value="normal",
            on_change=self.on_training_type_change,
        )
        
        training_type_container = ft.Container(
            content=training_type_radio,
            visible=False,  # Показуємо тільки коли увімкнено режим тренування
        )
        self.training_type_container = training_type_container
        
        # === ШВИДКІСТЬ ВІДТВОРЕННЯ ===
        speed_slider = ft.Slider(
            min=1.0,
            max=2.0,
            value=1.0,
            divisions=10,  # 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0 (крок 0.1)
            label="Швидкість: {value}x",
            on_change=self.on_speed_change,
            width=280,
        )
        
        self.speed_slider = speed_slider  # Зберігаємо посилання для оновлення в режимі Виклик
        
        # === ЧАСТОТА ЗВУКУ ===
        frequency_slider = ft.Slider(
            min=400,
            max=1200,
            value=800,
            divisions=16,  # Крок 50 Гц (400, 450, 500, ..., 1200)
            label="Частота: {value} Гц",
            on_change=self.on_frequency_change,
            width=280,
        )
        
        self.frequency_slider = frequency_slider  # Зберігаємо посилання
        
        # Об'єднуємо обидва слайдери в один рядок
        speed_row = ft.Row([
            ft.Column([
                ft.Text("⚡ Швидкість:", size=14, color="#90CAF9"),
                speed_slider,
            ], spacing=5, tight=True),
            ft.Column([
                ft.Text("🔊 Частота:", size=14, color="#90CAF9"),
                frequency_slider,
            ], spacing=5, tight=True),
        ], spacing=20, expand=True)
        
        # === КНОПКИ ВИБОРУ ===
        controls_buttons = ft.Row([
            ft.TextButton("Вибрати всі цифри", on_click=self.select_all_digits),
            ft.TextButton("Вибрати всі літери", on_click=self.select_all_letters),
            ft.TextButton("Зняти всі", on_click=self.deselect_all),
        ], spacing=10)
        
        # === СТВОРЮЄМО КАСТОМНІ ЧЕКБОКСИ (символ всередині квадратика) ===
        all_symbols = []
        
        # Спочатку цифри
        for digit in self.digits:
            # Створюємо контейнер-кнопку що виглядає як чекбокс
            symbol_checkbox = self.create_symbol_checkbox(digit, is_digit=True)
            all_symbols.append(symbol_checkbox)
        
        # Потім літери
        for letter in self.letters:
            symbol_checkbox = self.create_symbol_checkbox(letter, is_digit=False)
            all_symbols.append(symbol_checkbox)
        
        # Всі символи в один рядок з wrap
        symbols_container = ft.Row(
            controls=all_symbols,
            wrap=True,
            spacing=5,
            run_spacing=5,
        )
        
        # === КНОПКА СТАРТ/СТОП ===
        self.start_button = ft.ElevatedButton(
            text="▶️ СТАРТ",
            on_click=self.on_start_stop_click,
            width=200,
            height=50,
            bgcolor="#2196F3",  # синій
            color="#000000",  # чорний текст
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
            )
        )
        
        # === ГОЛОВНИЙ КОНТЕНТ ===
        self.main_content = ft.Column(
            [
                title_row,
                ft.Divider(height=20, color="transparent"),
                self.status_text,
                ft.Divider(height=20),
                
                # Режим тренування
                training_checkbox,
                training_type_container,
                ft.Divider(height=10),
                
                # Поле вводу слова (для режиму Слова)
                ft.Container(
                    content=self.word_input_field,
                    alignment=ft.alignment.center,
                ),
                ft.Divider(height=10),
                
                # Параметри для режиму Швидкість
                ft.Container(
                    content=self.speed_test_params,
                    alignment=ft.alignment.center,
                ),
                
                # Параметри для режиму Таймер
                ft.Container(
                    content=self.time_attack_params,
                    alignment=ft.alignment.center,
                ),
                ft.Divider(height=10),
                
                # Швидкість та частота відтворення
                speed_row,
                ft.Divider(height=15),
                
                # Кнопки вибору
                controls_buttons,
                ft.Divider(height=15),
                
                # Всі символи
                symbols_container,
                ft.Divider(height=30),
                
                # Кнопка
                ft.Container(
                    content=self.start_button,
                    alignment=ft.alignment.center,
                ),
                
                ft.Divider(height=20),
                
                # Статистика знизу
                ft.Container(
                    content=self.stats_text,
                    alignment=ft.alignment.center,
                ),
            ],
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
            visible=True,
        )
        
        # === КОНТЕНТ ТАБЛИЦІ ===
        # Створюємо таблицю
        table_rows = []
        
        # Кнопка повернутись
        back_btn = ft.ElevatedButton(
            text="← Назад",
            on_click=self.hide_alphabet_table,
            bgcolor="#2196F3",
            color="#000000",
        )
        
        # Заголовок таблиці
        table_title = ft.Row([
            ft.Text("📖 Азбука Морзе", size=24, weight=ft.FontWeight.BOLD, color="#2196F3"),
            ft.Container(expand=True),
            back_btn,
        ])
        table_rows.append(table_title)
        table_rows.append(ft.Divider(height=20, color="#2196F3"))
        
        # Заголовок колонок
        header_row = ft.Row([
            ft.Container(ft.Text("Символ", weight=ft.FontWeight.BOLD, size=14, color="#2196F3"), width=70),
            ft.Container(ft.Text("Код Морзе", weight=ft.FontWeight.BOLD, size=14, color="#2196F3"), width=100),
            ft.Container(ft.Text("Наспівка", weight=ft.FontWeight.BOLD, size=14, color="#2196F3"), width=250),
        ])
        table_rows.append(header_row)
        table_rows.append(ft.Divider(height=1, color="#2196F3"))
        
        # Цифри
        for digit in self.digits:
            row = ft.Row([
                ft.Container(ft.Text(digit, size=14, color="#90CAF9"), width=70),
                ft.Container(ft.Text(self.morse_codes.get(digit, ""), size=14, color="#90CAF9"), width=100),
                ft.Container(ft.Text(self.mnemonics.get(digit, ""), size=12, color="#90CAF9"), width=250),
            ])
            table_rows.append(row)
        
        table_rows.append(ft.Divider(height=1, color="#2196F3"))
        
        # Літери
        for letter in self.letters:
            row = ft.Row([
                ft.Container(ft.Text(letter, size=14, color="#90CAF9"), width=70),
                ft.Container(ft.Text(self.morse_codes.get(letter, ""), size=14, color="#90CAF9"), width=100),
                ft.Container(ft.Text(self.mnemonics.get(letter, ""), size=12, color="#90CAF9"), width=250),
            ])
            table_rows.append(row)
        
        self.table_content = ft.Column(
            table_rows,
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
            visible=False,
        )
        
        # Оновлюємо видимість елементів залежно від стану логіну
        self.main_content.visible = self.is_logged_in
        self.login_content.visible = not self.is_logged_in
        self.logout_btn.visible = self.is_logged_in
        self.user_indicator.visible = self.is_logged_in
        
        if self.is_logged_in and self.current_user:
            self.user_indicator.value = f"👤 {self.current_user['username']}"
        
        # Додаємо всі контени на сторінку
        page.add(self.login_content)
        page.add(self.main_content)
        page.add(self.table_content)


def main(page: ft.Page):
    trainer = MorseTrainer()
    trainer.build_ui(page)


if __name__ == "__main__":
    # Для веб-хостингу використовуємо WEB_BROWSER view
    # Порт буде встановлено автоматично з змінної середовища PORT або за замовчуванням 8550
    import os
    port = int(os.environ.get("PORT", 8550))
    ft.app(
        target=main,
        view=ft.WEB_BROWSER,
        port=port,
        host="0.0.0.0"  # Слухаємо на всіх інтерфейсах для хостингу
    )

