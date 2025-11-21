# Інструкція з розгортання Тренажера азбуки Морзе

## Варіанти розгортання

### Варіант 1: Flet Cloud (Найпростіший) ⭐ РЕКОМЕНДОВАНО

Flet Cloud - це офіційний хостинг від розробників Flet, найпростіший спосіб розгорнути додаток.

#### Кроки:

1. **Встановіть Flet CLI** (якщо ще не встановлено):
   ```bash
   pip install flet
   ```

2. **Зареєструйтеся на Flet Cloud**:
   - Перейдіть на https://flet.dev
   - Створіть акаунт

3. **Розгорніть додаток**:
   ```bash
   flet deploy
   ```
   
   Або через веб-інтерфейс на https://flet.dev

4. **Додаток буде доступний за URL** типу: `https://your-app-name.flet.dev`

**Переваги:**
- ✅ Безкоштовний план доступний
- ✅ Автоматичне HTTPS
- ✅ Просте розгортання
- ✅ Автоматичні оновлення

---

### Варіант 2: Railway.app

Railway - популярний хостинг для Python додатків.

#### Кроки:

1. **Створіть файл `railway.json`** (вже створено в проекті)

2. **Створіть файл `Procfile`**:
   ```
   web: python main.py
   ```

3. **Зареєструйтеся на Railway**:
   - Перейдіть на https://railway.app
   - Підключіть GitHub репозиторій

4. **Налаштуйте змінні середовища** (опціонально):
   - `PORT` - Railway встановить автоматично
   - `FLET_HOST` - залиште порожнім або `0.0.0.0`

5. **Deploy**:
   - Railway автоматично виявить Python додаток
   - Встановить залежності з `requirements.txt`
   - Запустить `main.py`

**Переваги:**
- ✅ Безкоштовний план ($5 кредитів на місяць)
- ✅ Автоматичне HTTPS
- ✅ Просте розгортання з GitHub

---

### Варіант 3: Render.com

Render - ще один популярний хостинг.

#### Кроки:

1. **Створіть файл `render.yaml`** (вже створено в проекті)

2. **Зареєструйтеся на Render**:
   - Перейдіть на https://render.com
   - Підключіть GitHub репозиторій

3. **Створіть новий Web Service**:
   - Build Command: `pip install -r requirements.txt && playwright install`
   - Start Command: `python main.py`
   - Environment: `Python 3`

4. **Налаштуйте змінні середовища**:
   - `PORT` - Render встановить автоматично

**Переваги:**
- ✅ Безкоштовний план доступний
- ✅ Автоматичне HTTPS
- ✅ Просте розгортання

---

### Варіант 4: Власний VPS/Сервер

Якщо у вас є власний сервер (VPS, DigitalOcean, AWS тощо).

#### Кроки:

1. **Встановіть залежності на сервері**:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

2. **Запустіть додаток**:
   ```bash
   python main.py
   ```

3. **Для постійного запуску використовуйте systemd або supervisor**:
   
   Створіть файл `/etc/systemd/system/morse-trainer.service`:
   ```ini
   [Unit]
   Description=Morse Code Trainer
   After=network.target

   [Service]
   Type=simple
   User=your-user
   WorkingDirectory=/path/to/morze
   ExecStart=/usr/bin/python3 /path/to/morze/main.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   Запустіть:
   ```bash
   sudo systemctl enable morse-trainer
   sudo systemctl start morse-trainer
   ```

4. **Налаштуйте Nginx як reverse proxy** (опціонально):
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:8550;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
       }
   }
   ```

---

## Важливі зауваження

### База даних SQLite
- База даних `morse_trainer.db` створюється автоматично
- На хостингу з ефемерною файловою системою (Railway, Render) дані можуть втрачатися при перезапуску
- **Рекомендація**: Використовуйте зовнішню базу даних (PostgreSQL) для продакшену

### Тимчасові файли
- Програма створює тимчасові WAV файли для аудіо
- Вони автоматично видаляються після використання
- Переконайтеся, що є достатньо місця на диску

### Файли проекту
Переконайтеся, що всі файли завантажені:
- ✅ `main.py`
- ✅ `morse_data.json`
- ✅ `requirements.txt`

### Логування
- Логи зберігаються в `morse_trainer.log`
- На хостингу перевіряйте логи через панель управління

---

## Тестування локально перед розгортанням

1. **Запустіть як веб-додаток**:
   ```bash
   python main.py
   ```
   
   Додаток відкриється в браузері автоматично.

2. **Або запустіть на конкретному порту**:
   ```bash
   flet run main.py --port 8550 --web
   ```

3. **Перевірте доступність**:
   - Відкрийте `http://localhost:8550` в браузері
   - Перевірте, що сторінка авторизації відображається

---

## Підтримка

Якщо виникли проблеми:
1. Перевірте логи на хостингу
2. Переконайтеся, що всі залежності встановлені
3. Перевірте, що `morse_data.json` присутній
4. Перевірте права доступу до файлів

---

## Оновлення додатку

Після змін у коді:
- **Flet Cloud**: Просто запустіть `flet deploy` знову
- **Railway/Render**: Зробіть push до GitHub, розгортання відбудеться автоматично
- **VPS**: Зупиніть сервіс, оновіть код, запустіть знову

