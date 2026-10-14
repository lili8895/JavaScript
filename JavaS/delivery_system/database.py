"""Работа с хранилищем: SQLite и TinyDB с единым интерфейсом и общими отчётами."""
import calendar
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import DATE_FORMAT, STATUSES, Customer, Order, OrderItem, ValidationError, validate_date

logger = logging.getLogger("delivery.database")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PATHS = {
    "sqlite": BASE_DIR / "data" / "delivery.db",
    "tinydb": BASE_DIR / "data" / "tinydb.json",
}
BACKENDS = tuple(DEFAULT_PATHS)
PERIODS = ("day", "week", "month")
PERIOD_NAMES = {"day": "день", "week": "неделя", "month": "месяц"}
CANCELLED = "отменён"


class DatabaseError(Exception):
    """Базовая ошибка работы с БД."""


class NotFoundError(DatabaseError):
    """Запись не найдена."""


class CustomerHasOrdersError(DatabaseError):
    """Попытка удалить клиента, у которого есть заказы."""


def period_bounds(period: str, ref_date=None) -> Tuple[str, str]:
    """Границы календарного периода (день/неделя/месяц), содержащего ref_date."""
    if isinstance(ref_date, str):
        ref_date = datetime.strptime(validate_date(ref_date), DATE_FORMAT).date()
    ref = ref_date or date.today()
    if period == "day":
        start = end = ref
    elif period == "week":
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = ref.replace(day=1)
        end = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
    else:
        raise ValueError(f"Неизвестный период '{period}'. Допустимые: {', '.join(PERIODS)}")
    return start.strftime(DATE_FORMAT), end.strftime(DATE_FORMAT)


def _check_status(status: Optional[str]) -> None:
    if status is not None and status not in STATUSES:
        raise ValidationError(f"Недопустимый статус '{status}'")


class Database(ABC):
    """Общий интерфейс хранилища. Отчёты реализованы один раз поверх CRUD."""

    backend = "abstract"

    # --- клиенты ---
    @abstractmethod
    def add_customer(self, customer: Customer) -> int: ...

    @abstractmethod
    def get_customer(self, customer_id: int) -> Optional[Customer]: ...

    @abstractmethod
    def list_customers(self) -> List[Customer]: ...

    @abstractmethod
    def update_customer(self, customer: Customer) -> None: ...

    @abstractmethod
    def customer_has_orders(self, customer_id: int) -> bool: ...

    @abstractmethod
    def _delete_customer(self, customer_id: int) -> None: ...

    # --- заказы ---
    @abstractmethod
    def add_order(self, order: Order) -> int: ...

    @abstractmethod
    def get_order(self, order_id: int) -> Optional[Order]: ...

    @abstractmethod
    def _all_orders(self) -> List[Order]: ...

    @abstractmethod
    def update_order(self, order: Order) -> None: ...

    @abstractmethod
    def delete_order(self, order_id: int) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    # --- общая логика ---
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def delete_customer(self, customer_id: int) -> None:
        if self.get_customer(customer_id) is None:
            raise NotFoundError(f"Клиент #{customer_id} не найден")
        if self.customer_has_orders(customer_id):
            logger.warning("Отказ в удалении клиента #%s: есть заказы", customer_id)
            raise CustomerHasOrdersError(f"Клиента #{customer_id} нельзя удалить: у него есть заказы")
        self._delete_customer(customer_id)
        logger.info("Удалён клиент #%s", customer_id)

    def _require_customer(self, customer_id: int) -> None:
        if self.get_customer(customer_id) is None:
            raise NotFoundError(f"Клиент #{customer_id} не найден")

    def list_orders(self, status: Optional[str] = None, date_from: Optional[str] = None,
                    date_to: Optional[str] = None) -> List[Order]:
        """Заказы с фильтрацией по статусу и диапазону дат (включительно)."""
        _check_status(status)
        if date_from:
            validate_date(date_from)
        if date_to:
            validate_date(date_to)
        result = [
            o for o in self._all_orders()
            if (status is None or o.status == status)
            and (not date_from or o.order_date >= date_from)
            and (not date_to or o.order_date <= date_to)
        ]
        return sorted(result, key=lambda o: (o.order_date, o.id))

    def orders_count_by_status(self) -> Dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for order in self._all_orders():
            counts[order.status] += 1
        return counts

    def top_customers(self, limit: int = 3) -> List[Tuple[Customer, float]]:
        """Топ клиентов по сумме заказов (отменённые не учитываются)."""
        totals: Dict[int, float] = {}
        for order in self._all_orders():
            if order.status != CANCELLED:
                totals[order.customer_id] = totals.get(order.customer_id, 0.0) + order.total
        ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        return [(self.get_customer(cid), round(total, 2)) for cid, total in ranked]

    def revenue(self, period: str = "month", ref_date=None) -> Dict:
        """Выручка за календарный период (отменённые заказы не учитываются)."""
        start, end = period_bounds(period, ref_date)
        orders = [o for o in self.list_orders(date_from=start, date_to=end) if o.status != CANCELLED]
        return {
            "period": period,
            "date_from": start,
            "date_to": end,
            "orders": len(orders),
            "revenue": round(sum(o.total for o in orders), 2),
        }

    def build_report(self, period: str = "month", ref_date=None) -> Dict:
        report = {
            "by_status": self.orders_count_by_status(),
            "top_customers": self.top_customers(3),
            "revenue": self.revenue(period, ref_date),
        }
        logger.info("Сформирован отчёт за период %s", period)
        return report


def format_report(report: Dict) -> str:
    """Текстовое представление отчёта (для CLI и GUI)."""
    lines = ["Количество заказов по статусам:"]
    for status, count in report["by_status"].items():
        lines.append(f"  {status:<12} {count}")
    lines.append("")
    lines.append("Топ-3 клиента по сумме заказов:")
    if report["top_customers"]:
        for pos, (customer, total) in enumerate(report["top_customers"], 1):
            lines.append(f"  {pos}. {customer.name:<25} {total:>12.2f} руб.")
    else:
        lines.append("  нет данных")
    rev = report["revenue"]
    lines.append("")
    lines.append(f"Выручка за {PERIOD_NAMES[rev['period']]} ({rev['date_from']} — {rev['date_to']}):")
    lines.append(f"  {rev['revenue']:.2f} руб., заказов: {rev['orders']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- SQLite
SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('новый','в доставке','выполнен','отменён')),
    total REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL
);
"""


class SQLiteDatabase(Database):
    backend = "sqlite"

    def __init__(self, path=DEFAULT_PATHS["sqlite"]):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        logger.info("Открыта SQLite БД: %s", self.path)

    def close(self) -> None:
        self.conn.close()

    # клиенты
    def add_customer(self, customer: Customer) -> int:
        customer.validate()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)",
                (customer.name, customer.phone, customer.address))
        customer.id = cur.lastrowid
        logger.info("Добавлен клиент #%s (%s)", customer.id, customer.name)
        return customer.id

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        row = self.conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return Customer(row["name"], row["phone"] or "", row["address"] or "", row["id"]) if row else None

    def list_customers(self) -> List[Customer]:
        rows = self.conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
        return [Customer(r["name"], r["phone"] or "", r["address"] or "", r["id"]) for r in rows]

    def update_customer(self, customer: Customer) -> None:
        customer.validate()
        self._require_customer(customer.id)
        with self.conn:
            self.conn.execute("UPDATE customers SET name = ?, phone = ?, address = ? WHERE id = ?",
                              (customer.name, customer.phone, customer.address, customer.id))
        logger.info("Обновлён клиент #%s", customer.id)

    def customer_has_orders(self, customer_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM orders WHERE customer_id = ? LIMIT 1",
                                 (customer_id,)).fetchone() is not None

    def _delete_customer(self, customer_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

    # заказы
    def _save_items(self, order: Order) -> None:
        self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order.id,))
        self.conn.executemany(
            "INSERT INTO order_items (order_id, product_name, quantity, price) VALUES (?, ?, ?, ?)",
            [(order.id, i.product_name, i.quantity, i.price) for i in order.items])

    def add_order(self, order: Order) -> int:
        order.validate()
        self._require_customer(order.customer_id)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO orders (customer_id, order_date, status, total) VALUES (?, ?, ?, ?)",
                (order.customer_id, order.order_date, order.status, order.total))
            order.id = cur.lastrowid
            self._save_items(order)
        logger.info("Добавлен заказ #%s на сумму %.2f", order.id, order.total)
        return order.id

    def _row_to_order(self, row) -> Order:
        items = [OrderItem(r["product_name"], r["quantity"], r["price"]) for r in self.conn.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (row["id"],))]
        return Order(row["customer_id"], row["order_date"], items, row["status"], row["total"], row["id"])

    def get_order(self, order_id: int) -> Optional[Order]:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return self._row_to_order(row) if row else None

    def _all_orders(self) -> List[Order]:
        return [self._row_to_order(r) for r in self.conn.execute("SELECT * FROM orders ORDER BY id")]

    def update_order(self, order: Order) -> None:
        order.validate()
        if order.id is None or self.get_order(order.id) is None:
            raise NotFoundError(f"Заказ #{order.id} не найден")
        self._require_customer(order.customer_id)
        with self.conn:
            self.conn.execute(
                "UPDATE orders SET customer_id = ?, order_date = ?, status = ?, total = ? WHERE id = ?",
                (order.customer_id, order.order_date, order.status, order.total, order.id))
            self._save_items(order)
        logger.info("Обновлён заказ #%s", order.id)

    def delete_order(self, order_id: int) -> None:
        if self.get_order(order_id) is None:
            raise NotFoundError(f"Заказ #{order_id} не найден")
        with self.conn:
            self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            self.conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        logger.info("Удалён заказ #%s", order_id)


# ---------------------------------------------------------------- TinyDB
class TinyDatabase(Database):
    """TinyDB: внешние ключи и JOIN эмулируются программно (фильтрацией списков)."""

    backend = "tinydb"

    def __init__(self, path=DEFAULT_PATHS["tinydb"]):
        from tinydb import TinyDB  # импорт здесь, чтобы SQLite работал и без tinydb

        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = TinyDB(self.path, ensure_ascii=False, indent=2, encoding="utf-8")
        self.customers = self.db.table("customers")
        self.orders = self.db.table("orders")
        logger.info("Открыта TinyDB: %s", self.path)

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _to_customer(doc) -> Customer:
        return Customer(doc["name"], doc.get("phone", ""), doc.get("address", ""), doc.doc_id)

    @staticmethod
    def _to_order(doc) -> Order:
        return Order(doc["customer_id"], doc["order_date"], list(doc.get("items", [])),
                     doc["status"], doc["total"], doc.doc_id)

    # клиенты
    def add_customer(self, customer: Customer) -> int:
        customer.validate()
        customer.id = self.customers.insert(customer.to_dict(include_id=False))
        logger.info("Добавлен клиент #%s (%s)", customer.id, customer.name)
        return customer.id

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        doc = self.customers.get(doc_id=int(customer_id))
        return self._to_customer(doc) if doc else None

    def list_customers(self) -> List[Customer]:
        return sorted((self._to_customer(d) for d in self.customers.all()), key=lambda c: c.id)

    def update_customer(self, customer: Customer) -> None:
        customer.validate()
        self._require_customer(customer.id)
        self.customers.update(customer.to_dict(include_id=False), doc_ids=[customer.id])
        logger.info("Обновлён клиент #%s", customer.id)

    def customer_has_orders(self, customer_id: int) -> bool:
        return any(d["customer_id"] == customer_id for d in self.orders.all())

    def _delete_customer(self, customer_id: int) -> None:
        self.customers.remove(doc_ids=[customer_id])

    # заказы
    def add_order(self, order: Order) -> int:
        order.validate()
        self._require_customer(order.customer_id)
        order.id = self.orders.insert(order.to_dict(include_id=False))
        logger.info("Добавлен заказ #%s на сумму %.2f", order.id, order.total)
        return order.id

    def get_order(self, order_id: int) -> Optional[Order]:
        doc = self.orders.get(doc_id=int(order_id))
        return self._to_order(doc) if doc else None

    def _all_orders(self) -> List[Order]:
        return [self._to_order(d) for d in self.orders.all()]

    def update_order(self, order: Order) -> None:
        order.validate()
        if order.id is None or self.get_order(order.id) is None:
            raise NotFoundError(f"Заказ #{order.id} не найден")
        self._require_customer(order.customer_id)
        self.orders.update(order.to_dict(include_id=False), doc_ids=[order.id])
        logger.info("Обновлён заказ #%s", order.id)

    def delete_order(self, order_id: int) -> None:
        if self.get_order(order_id) is None:
            raise NotFoundError(f"Заказ #{order_id} не найден")
        self.orders.remove(doc_ids=[order_id])
        logger.info("Удалён заказ #%s", order_id)


def get_database(backend: str = "sqlite", path=None) -> Database:
    """Фабрика: возвращает хранилище нужного типа."""
    if backend not in BACKENDS:
        raise ValueError(f"Неизвестный тип БД '{backend}'. Допустимые: {', '.join(BACKENDS)}")
    path = path or DEFAULT_PATHS[backend]
    return SQLiteDatabase(path) if backend == "sqlite" else TinyDatabase(path)
