# Быстрая доставка — учёт заказов

Внутреннее приложение компании «Быстрая доставка» для учёта клиентов и заказов.
Два режима работы — **CLI** (argparse) и **GUI** (Tkinter), два хранилища — **SQLite** и **TinyDB**,
экспорт/импорт в двух форматах — **XML** и **JSON**.

## Возможности

| Раздел | Что реализовано |
|---|---|
| Клиенты | CRUD (имя, телефон, адрес); клиента с заказами удалить нельзя (проверка в коде + `ON DELETE RESTRICT` в SQLite) |
| Заказы | Дата, клиент (выбор из списка), список товаров, итоговая сумма (считается автоматически), статус: «новый», «в доставке», «выполнен», «отменён»; CRUD + фильтр по статусу и диапазону дат |
| Отчёты | Количество заказов по статусам, топ-3 клиента по сумме заказов, выручка за день / неделю / месяц (отменённые заказы не учитываются) |
| Экспорт / импорт | JSON и XML; импорт с проверкой корректности всех полей; импорт атомарный — при любой ошибке база не меняется |
| БД | SQLite (`data/delivery.db`) и TinyDB (`data/tinydb.json`) с единым интерфейсом; в TinyDB связи и JOIN эмулируются программно |
| Логирование | `logs/delivery.log` (ротация 1 МБ × 3 файла), флаг `-v` дублирует логи в консоль |
| Тесты | pytest, 90 тестов, покрытие ≈ 98 % (каждый тест БД гоняется на обоих хранилищах) |

## Установка

Требуется Python 3.8+ (Tkinter входит в стандартную поставку Python для Windows/macOS;
в Linux может понадобиться пакет `python3-tk`).

```bash
git clone https://github.com/<ваш-логин>/delivery_system.git
cd delivery_system
python -m venv venv
# Windows: venv\Scripts\activate     Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

В репозитории уже лежат базы с демо-данными. Чтобы заполнить новую базу: `python main_cli.py seed`.

## CLI

Общие параметры (указываются **перед** командой):
`--db sqlite|tinydb` (по умолчанию sqlite), `--db-path ПУТЬ`, `--log-dir ПАПКА`, `-v`.

```bash
# Отчёт: статусы, топ-3 клиента, выручка за период (day / week / month)
python main_cli.py report --period month
python main_cli.py report --period week --date 2025-04-20

# Экспорт заказов в XML или JSON (формат — по расширению или через --format)
python main_cli.py export --file orders_backup.xml
python main_cli.py export --file orders_backup.json

# Импорт из XML или JSON
python main_cli.py import --file examples/orders_new.xml
python main_cli.py import --file examples/orders_new.json

# То же на TinyDB
python main_cli.py --db tinydb report --period month

# Клиенты
python main_cli.py customers list
python main_cli.py customers add --name "Иван" --phone "+7 900 123-45-67" --address "Москва"
python main_cli.py customers update 1 --address "Тверь"
python main_cli.py customers delete 1

# Заказы (позиция: "Название:количество:цена")
python main_cli.py orders list --status "в доставке" --from 2025-04-01 --to 2025-04-30
python main_cli.py orders add --customer-id 1 --date 2025-04-20 --item "Пицца:2:750" --item "Сок:1:120"
python main_cli.py orders update 3 --status выполнен
python main_cli.py orders delete 3

python main_cli.py --help            # справка по всем командам
```

`delivery.py` — синоним `main_cli.py` (как в примерах ТЗ): `python delivery.py report --period month`.

## GUI

```bash
python main_gui.py               # SQLite
python main_gui.py --db tinydb   # TinyDB
```

- Главное окно — список заказов (Treeview), фильтр по статусу и датам.
- Кнопки «Добавить», «Редактировать» (или двойной клик), «Удалить».
- Форма заказа: выбор клиента из списка, дата, статус, таблица товаров, итог считается автоматически.
- «Клиенты» — окно управления клиентами (CRUD).
- «Показать отчёт» — статистика в новом окне с выбором периода.
- Выпадающий список формата (JSON/XML) + кнопки «Экспорт» / «Импорт».

## Форматы файлов

JSON:

```json
{
  "orders": [
    {
      "order_date": "2025-04-20",
      "status": "новый",
      "total": 1500.0,
      "customer": {"name": "Иван", "phone": "+7 900 111-22-33", "address": "Москва"},
      "items": [{"product_name": "Пицца", "quantity": 2, "price": 750}]
    }
  ]
}
```

XML:

```xml
<orders>
  <order order_date="2025-04-20" status="новый" total="1500.00">
    <customer><name>Иван</name><phone>+7 900 111-22-33</phone><address>Москва</address></customer>
    <items>
      <item><product_name>Пицца</product_name><quantity>2</quantity><price>750</price></item>
    </items>
  </order>
</orders>
```

При импорте клиент ищется по имени и телефону; если его нет — создаётся. Также поддерживается
формат из ТЗ со ссылкой `customer_id` на существующего клиента. Проверяются: дата (ГГГГ-ММ-ДД),
статус, количество (целое > 0), цена (≥ 0), совпадение `total` с суммой позиций.

## Тесты

```bash
pytest                                    # все тесты
pytest --cov=. --cov-report=term-missing  # с покрытием
```

GUI исключён из замера покрытия (`.coveragerc`), т.к. требует графической среды.

## Структура проекта

```
delivery_system/
├── main_cli.py        # CLI-точка входа (argparse)
├── main_gui.py        # GUI-точка входа (Tkinter)
├── delivery.py        # синоним CLI из ТЗ
├── database.py        # SQLite и TinyDB с общим интерфейсом + отчёты
├── models.py          # Customer, OrderItem, Order + валидация
├── data_export.py     # экспорт/импорт XML и JSON
├── logger_config.py   # настройка логирования
├── tests/             # pytest: модели, БД, экспорт, CLI
├── logs/              # логи приложения
├── data/
│   ├── delivery.db    # SQLite
│   └── tinydb.json    # TinyDB
├── examples/          # файлы для проверки импорта
├── requirements.txt
└── README.md
```
