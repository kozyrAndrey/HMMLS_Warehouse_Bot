# HMMLS Warehouse Bot

Telegram-бот для складских процессов HMMLS.

Бот используется для:

- оприходования товара;
- оформления возвратов;
- отправки возвратов в тему Telegram-чата;
- выгрузки отчёта оприходований в тему Telegram-чата;
- хранения данных в PostgreSQL.

---

## Основная логика

После запуска бот показывает кнопку:

```text
🚀 Старт
```

После нажатия открывается главное меню:

```text
📦 Отчет оприходований
↩️ Возвраты
```

---

## Раздел «Отчет оприходований»

В разделе находятся кнопки:

```text
➕ Оприходовать товар
📋 Последние записи
📤 Выгрузка отчета
```

### Оприходовать товар

Сценарий:

```text
выбор даты
→ выбор группы товара
→ выбор модели
→ выбор цвета / варианта, если их несколько
→ выбор размера
→ ввод количества «Упаковано»
→ ввод количества «Брак»
→ ввод количества «Доработка»
→ запись в PostgreSQL
```

Дата выбирается из двух вариантов:

```text
сегодня
вчера
```

Формат даты:

```text
ДД.ММ.ГГГГ
```

Пример:

```text
20.05.2026
```

### Последние записи

Кнопка показывает последние записи из PostgreSQL.

### Выгрузка отчета

Бот предлагает выбрать дату:

```text
сегодня
вчера
```

После выбора даты бот собирает все записи из PostgreSQL за эту дату, группирует их по товару и размеру и отправляет итоговый отчёт в Telegram-тему «Отчет приемки».

Пример отчёта:

```text
Дата: 20.05.2026

DIAMOND V2 ZIP HOODIE DARK BLUE
M: упаковано - 102, брак - 12, доработка - 2, общее - 116

DIAMOND PANTS BLACK
L: упаковано - 101, брак - 3, доработка - 4, общее - 108

Общее упаковано: 203
Общее брак: 15
Общее доработка: 6
Общее: 224
```

---

## Раздел «Возвраты»

В разделе находится кнопка:

```text
↩️ Оприходовать возврат
```

Сценарий возврата:

```text
фото накладной
→ ФИО контрагента
→ трек-номер
→ количество товаров в возврате
→ выбор каждого товара
→ выбор состояния каждого товара
→ при необходимости доп. фото
→ при необходимости комментарий к конкретному товару
→ отправка результата в Telegram-тему «Возвраты»
```

Для каждого товара выбирается состояние:

```text
✅ Норм
📄 Брак по накладной
🛠 Доработка по накладной
⚠️ Брак НЕ по накладной
```

Логика по состояниям:

```text
Норм
→ без доп. фото
→ без комментария
→ переход к следующему товару

Брак по накладной
→ запрос доп. фото
→ запрос комментария к этому товару
→ упоминание руководителя склада

Доработка по накладной
→ запрос доп. фото
→ запрос комментария к этому товару
→ упоминание руководителя склада

Брак НЕ по накладной
→ запрос доп. фото
→ запрос комментария к этому товару
→ упоминание руководителя склада
→ упоминание руководителя поддержки
```

Пример сообщения в теме «Возвраты»:

```text
Сотрудник: opulent_shooter
ФИО контрагента: Козырь Андрей
Трек-номер: 10928371994
Количество товаров: 3

Товары:
1. BASE LEATHER JACKET BLACK — размер M, норм
2. BASE BOMBER BLACK — размер L, брак по накладной, комментарий: порвана упаковка
3. DIAMOND PANTS BLACK — размер M, брак не по накладной, комментарий: пятно на ткани

@warehouse_manager
@support_manager
```

К сообщению прикрепляются:

```text
фото накладной
доп. фото проблемных товаров
```

---

## Структура проекта

```text
HMMLS_Warehouse_Bot/
├── bot.py
├── config.py
├── products.py
├── keyboards.py
├── database.py
├── google_sheets.py
├── access.py
├── requirements.txt
├── setup_env.sh
├── .env.example
├── .gitignore
├── README.md
└── handlers/
    ├── __init__.py
    ├── common.py
    ├── incoming.py
    ├── returns.py
    └── reports.py
```

---

## Назначение файлов

### `bot.py`

Главный файл запуска.

Он:

- создаёт Telegram-приложение;
- подключает все обработчики;
- запускает polling;
- настраивает таймауты;
- подключает обработчик ошибок.

### `config.py`

Файл настроек.

Настройки берутся из переменных окружения или из `.env`.

Внутри находятся:

```text
BOT_TOKEN
GOOGLE_SHEET_ID
GOOGLE_WORKSHEET_NAME
GOOGLE_CREDENTIALS_PATH
GROUP_CHAT_ID
RETURNS_TOPIC_ID
RECEIVING_REPORT_TOPIC_ID
DATABASE_URL
```

### `products.py`

Каталог товаров.

Текущая структура:

```text
группа
→ модель
→ цвет / вариант
```

Бот использует этот файл для выбора товара в оприходовании и возвратах.

### `keyboards.py`

Все кнопки Telegram-бота.

Например:

- главное меню;
- меню оприходований;
- меню возвратов;
- выбор даты;
- выбор товара;
- выбор размера;
- выбор состояния возврата.

### `postgres_storage.py`

Работа с PostgreSQL для оприходований.

Файл базы:

```text
PostgreSQL
```

Этот файл не хранится в GitHub.

### `google_sheets.py`

Работа с Google Таблицей.

Файл отвечает за:

- подключение к Google Sheets;
- запись оприходований;
- чтение последних записей;
- сбор отчёта оприходований;
- нормализацию дат;
- группировку данных для отчёта.

### `access.py`

Заготовка под будущую систему ролей.

Пока доступ открыт, но в будущем можно добавить роли:

```text
admin
manager
warehouse
viewer
```

### `handlers/common.py`

Общие команды и меню:

```text
/start
/last
/db_status
/whereami
```

### `handlers/incoming.py`

Сценарий оприходования товара.

### `handlers/returns.py`

Сценарий оформления возвратов.

### `handlers/reports.py`

Сценарий выгрузки отчёта оприходований.

---

## Что не хранится в GitHub

В репозиторий нельзя добавлять:

```text
.env
google_credentials.json
.venv/
incoming_goods.xlsx
```

Эти файлы должны быть в `.gitignore`.

---

## `.gitignore`

В проекте должен быть файл `.gitignore`:

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd

# Virtual environment
.venv/
venv/
env/

# Excel exports
*.xlsx

# Google credentials
google_credentials.json

# Environment variables
.env

# macOS
.DS_Store

# VS Code
.vscode/
```

---

## Переменные окружения

В GitHub хранится только пример:

```text
.env.example
```

Реальный файл `.env` создаётся вручную на компьютере или сервере.

Пример `.env.example`:

```env
BOT_TOKEN=your_telegram_bot_token_here
GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_WORKSHEET_NAME=Оприходование

GROUP_CHAT_ID=-1001234567890
RETURNS_TOPIC_ID=3
RECEIVING_REPORT_TOPIC_ID=4

GOOGLE_CREDENTIALS_PATH=google_credentials.json
```

После скачивания проекта нужно создать `.env`:

```bash
cp .env.example .env
```

И вставить реальные значения:

```env
BOT_TOKEN=реальный_токен_бота
GOOGLE_SHEET_ID=реальный_id_google_таблицы
GOOGLE_WORKSHEET_NAME=Оприходование

GROUP_CHAT_ID=-1003773664379
RETURNS_TOPIC_ID=3
RECEIVING_REPORT_TOPIC_ID=4

GOOGLE_CREDENTIALS_PATH=google_credentials.json
```

---

## Миграция Google Sheets в PostgreSQL

Runtime-данные бота хранятся в PostgreSQL. Старые Google Sheets можно перенести командой:

```bash
.venv/bin/python scripts/migrate_google_sheets_to_postgres.py --only all
```

Команда переносит:

- оприходования в рабочую таблицу `incoming_goods`;
- все листы приемки, ЗП и расписания в архив `google_sheet_archive_rows`;
- ЗП и расписание в отдельные таблицы:
  `payroll_employees`, `payroll_reports`, `payroll_expenses`,
  `payroll_penalties`, `payroll_kpi`, `payroll_periods`,
  `payroll_kpi_daily`, `schedule_archive`, `schedule_duties`,
  `schedule_exports`.

Если архив уже импортирован, отдельные таблицы можно пересобрать без Google:

```bash
.venv/bin/python scripts/sync_structured_tables.py
```

Для миграции нужны `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_SHEET_ID`, `PAYROLL_GOOGLE_SHEET_ID` и `OPERATIONS_GOOGLE_SHEET_ID`.

---

## Google credentials

Файл:

```text
google_credentials.json
```

не хранится в репозитории, потому что это секретный ключ доступа к Google API.

Он должен лежать в корне проекта рядом с `bot.py`:

```text
HMMLS_Warehouse_Bot/
├── bot.py
├── config.py
├── google_credentials.json
└── ...
```

Также Google Таблица должна быть расшарена на `client_email` из `google_credentials.json`.

Внутри JSON нужно найти строку:

```json
"client_email": "warehouse-bot@project-name.iam.gserviceaccount.com"
```

Этот email нужно добавить в доступ к Google Таблице с правами:

```text
Editor / Редактор
```

---

## Google Таблица

Бот пишет данные в лист:

```text
Оприходование
```

Название листа задаётся переменной:

```env
GOOGLE_WORKSHEET_NAME=Оприходование
```

Колонки:

```text
Дата
User ID
Пользователь
Группа
Модель
Размер
Упаковано
Брак
Доработка
```

Дата записывается в формате:

```text
ДД.ММ.ГГГГ
```

Пример:

```text
20.05.2026
```

---

## Telegram-группа и темы

Бот может отправлять сообщения в темы Telegram-группы.

Используются переменные:

```env
GROUP_CHAT_ID=-1001234567890
RETURNS_TOPIC_ID=3
RECEIVING_REPORT_TOPIC_ID=4
```

### `GROUP_CHAT_ID`

ID общей группы.

### `RETURNS_TOPIC_ID`

ID темы «Возвраты».

### `RECEIVING_REPORT_TOPIC_ID`

ID темы «Отчет приемки».

---

## Как получить `GROUP_CHAT_ID` и `message_thread_id`

1. Добавить бота в Telegram-группу.
2. Сделать бота администратором.
3. Включить темы в группе.
4. Открыть нужную тему.
5. Написать:

```text
/whereami
```

Бот ответит:

```text
chat_id: -1001234567890
message_thread_id: 3
```

`chat_id` вставить в:

```env
GROUP_CHAT_ID=-1001234567890
```

`message_thread_id` нужной темы вставить в:

```env
RETURNS_TOPIC_ID=3
```

или:

```env
RECEIVING_REPORT_TOPIC_ID=4
```

---

## Права бота в Telegram-группе

Для корректной работы в темах боту желательно дать права администратора.

Минимально нужны права:

```text
отправка сообщений
отправка медиа
работа с темами
```

---

## Установка на локальном компьютере

### 1. Клонировать репозиторий

```bash
git clone https://github.com/USERNAME/HMMLS_Warehouse_Bot.git
cd HMMLS_Warehouse_Bot
```

### 2. Создать `.env`

```bash
cp .env.example .env
```

Открыть `.env` и вставить реальные значения.

### 3. Положить `google_credentials.json`

Файл должен лежать в корне проекта.

### 4. Установить зависимости

Можно одной командой:

```bash
bash setup_env.sh
```

Или вручную:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 5. Запустить бота

```bash
source .venv/bin/activate
python bot.py
```

---

## `requirements.txt`

Минимальный список зависимостей:

```txt
python-telegram-bot>=22.0,<23.0
gspread>=6.0,<7.0
google-auth>=2.0,<3.0
python-dotenv>=1.0,<2.0
```

---

## `setup_env.sh`

Скрипт создаёт виртуальное окружение и устанавливает зависимости.

Запуск:

```bash
bash setup_env.sh
```

Или:

```bash
chmod +x setup_env.sh
./setup_env.sh
```

---

## Раздел «Маркировка»

Руководителям доступны:

- одновременная выгрузка CSV для УПД и Excel для импорта номенклатуры в 1С;
- управление локальным справочником `GTIN → название Честного ЗНАКа`;
- формирование дубликата этикетки Честного ЗНАКа.

Для выгрузки бот запрашивает название документа «Вывод из оборота» в МойСклад. Для каждой
позиции он получает размерный артикул из характеристики варианта `Артикул`, GTIN, цену типа
`Цена продажи` и коды маркировки. Если у варианта такой характеристики нет, используется артикул
самого варианта или родительской модели. Для CSV цена без НДС
рассчитывается делением на `1.07` и записывается с восемью знаками после точки.
Для Excel берется розничная цена с НДС; одна строка соответствует одной товарной модификации,
а количество равно числу уникальных КИЗ. Файл создается на основе шаблона
`resources/trend_island_1c_template.xlsx`. В столбец `Категория` для всех товаров записывается
`Товары легкой промышленности`; категория из МойСклад не используется.

При первом запуске таблица `honest_sign_products` автоматически заполняется справочником из
`resources/honest_sign_products.csv`. Дальнейшие изменения выполняются в Telegram через кнопку
`📚 Справочник Честного ЗНАКа` и не перезаписываются при перезапуске.

Типы цен и параметры Excel можно изменить переменными окружения:

```dotenv
MOYSKLAD_SALE_PRICE_TYPE=Цена продажи
MARKING_ONE_C_RETAIL_PRICE_TYPE=Цена продажи
MARKING_ONE_C_DEFAULT_GENDER=Unisex
MARKING_ONE_C_CONSIGNOR=Комитент: ООО "Ваша компания"
```

Два формата проверяются независимо. Например, если для Excel не заполнен производитель,
бот все равно отправит корректный CSV и отдельно покажет ошибки Excel.

---

## Служебные команды бота

### `/start`

Запуск бота.

### `/last`

Показывает последние записи из PostgreSQL.

### `/db_status`

Проверяет подключение к PostgreSQL и показывает колонки таблицы `incoming_goods`.

### `/whereami`

Показывает:

```text
chat_id
message_thread_id
```

Используется для настройки тем Telegram-группы.

---

## Запуск на сервере

На сервере процесс такой:

```bash
git clone https://github.com/USERNAME/HMMLS_Warehouse_Bot.git
cd HMMLS_Warehouse_Bot
cp .env.example .env
nano .env
```

Вставить реальные переменные.

Положить:

```text
google_credentials.json
```

Потом:

```bash
bash setup_env.sh
source .venv/bin/activate
python bot.py
```

---

## Запуск 24/7 через systemd

Для постоянной работы на VPS можно создать systemd-сервис.

Файл:

```bash
sudo nano /etc/systemd/system/hmmls-bot.service
```

Пример:

```ini
[Unit]
Description=HMMLS Warehouse Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/HMMLS_Warehouse_Bot
ExecStart=/home/HMMLS_Warehouse_Bot/.venv/bin/python /home/HMMLS_Warehouse_Bot/bot.py
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable hmmls-bot
sudo systemctl start hmmls-bot
```

Проверка статуса:

```bash
sudo systemctl status hmmls-bot
```

Логи:

```bash
sudo journalctl -u hmmls-bot -f
```

---

## Обновление кода на сервере

Если код обновился в GitHub:

```bash
cd /home/HMMLS_Warehouse_Bot
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl restart hmmls-bot
```

Если бот запущен вручную:

```bash
Ctrl + C
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
python bot.py
```

---

## Работа с Git

Основная ветка:

```text
main
```

Для новых функций можно создавать отдельные ветки:

```bash
git checkout -b feature/returns-update
```

После изменений:

```bash
git add .
git commit -m "Add returns update"
git push -u origin feature/returns-update
```

Для небольшого проекта можно работать прямо в `main`, но перед коммитом обязательно проверять:

```bash
git status
```

В коммит не должны попадать:

```text
.env
google_credentials.json
.venv/
```

---

## Как добавить товар

Открыть:

```text
products.py
```

Каталог устроен так:

```text
группа
→ модель
→ цвет / вариант
```

Пример модели с одним вариантом:

```python
"diamond_shirt": {
    "name": "DIAMOND SHIRT",
    "variants": {
        "one": {
            "id": "sh001",
            "color": "ONE COLOR",
            "name": "DIAMOND SHIRT",
        },
    },
},
```

Пример модели с несколькими цветами:

```python
"diamond_v2_zip_hoodie": {
    "name": "DIAMOND V2 ZIP HOODIE",
    "variants": {
        "dark_blue": {
            "id": "h010",
            "color": "DARK BLUE",
            "name": "DIAMOND V2 ZIP HOODIE DARK BLUE",
        },
        "pink": {
            "id": "h011",
            "color": "PINK",
            "name": "DIAMOND V2 ZIP HOODIE PINK",
        },
        "black": {
            "id": "h012",
            "color": "BLACK",
            "name": "DIAMOND V2 ZIP HOODIE BLACK",
        },
    },
},
```

Если у модели один вариант, бот сразу переходит к выбору размера.

Если вариантов несколько, бот показывает выбор цвета.

---

## Как добавить размер

В `products.py` найти:

```python
SIZES = ["XS", "S", "M", "L", "XL", "XXL", "ONE SIZE"]
```

Добавить нужный размер в список.

---

## Частые проблемы

### `ModuleNotFoundError`

Пример:

```text
ModuleNotFoundError: No module named 'gspread'
```

Решение:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

---

### Google Таблица не обновляется

Проверить:

```text
/db_status
```

Возможные причины:

```text
не лежит google_credentials.json
не указан GOOGLE_SHEET_ID
таблица не расшарена на client_email
не включён Google Sheets API
не включён Google Drive API
```

---

### Бот не отправляет в тему Telegram

Проверить:

```text
/whereami
```

Возможные причины:

```text
неверный GROUP_CHAT_ID
неверный RETURNS_TOPIC_ID
неверный RECEIVING_REPORT_TOPIC_ID
бот не добавлен в группу
бот не имеет прав писать в тему
```

---

### Бот работает только пока открыт терминал

Это нормально для локального запуска.

Для постоянной работы нужно запускать на сервере через:

```text
systemd
```

или другой process manager.

---

### Telegram timeout

Если появляется ошибка:

```text
telegram.error.TimedOut
```

Обычно это временная проблема сети или Telegram API.

В `bot.py` уже используются увеличенные таймауты через `HTTPXRequest`.

---

## Безопасность

Нельзя публиковать:

```text
BOT_TOKEN
.env
google_credentials.json
```

Если токен бота случайно попал в чат, GitHub или логи, его нужно перевыпустить в BotFather:

```text
/mybots
→ выбрать бота
→ API Token
→ Revoke current token
```

После этого новый токен вставить в `.env`.

---

## Минимальный чеклист перед запуском

```text
✅ Установлены зависимости
✅ Есть .env
✅ В .env указан BOT_TOKEN
✅ В .env указан GOOGLE_SHEET_ID
✅ Рядом с bot.py лежит google_credentials.json
✅ Google Таблица расшарена на client_email
✅ Бот добавлен в Telegram-группу
✅ Настроены GROUP_CHAT_ID, RETURNS_TOPIC_ID, RECEIVING_REPORT_TOPIC_ID
✅ Команда /db_status работает
✅ Команда /whereami показывает нужные ID
```

---

## Быстрый старт

```bash
git clone https://github.com/USERNAME/HMMLS_Warehouse_Bot.git
cd HMMLS_Warehouse_Bot

cp .env.example .env
nano .env

bash setup_env.sh
source .venv/bin/activate
python bot.py
```
