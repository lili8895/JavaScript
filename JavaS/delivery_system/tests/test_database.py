import pytest

from database import (CustomerHasOrdersError, NotFoundError, SQLiteDatabase, format_report,
                      get_database, period_bounds)
from models import Customer, Order, OrderItem, ValidationError


# ------------------------------------------------------------------ клиенты
def test_customer_crud(db):
    cid = db.add_customer(Customer("Иван", "+79001112233", "Москва"))
    assert db.get_customer(cid).name == "Иван"

    db.update_customer(Customer("Иван Петров", "+79004445566", "Тверь", cid))
    updated = db.get_customer(cid)
    assert (updated.name, updated.phone, updated.address) == ("Иван Петров", "+79004445566", "Тверь")

    assert [c.id for c in db.list_customers()] == [cid]
    db.delete_customer(cid)
    assert db.get_customer(cid) is None
    assert db.list_customers() == []


def test_cannot_delete_customer_with_orders(db):
    cid = db.add_customer(Customer("Иван"))
    oid = db.add_order(Order(cid, "2025-04-20", [OrderItem("Пицца", 1, 500)]))
    with pytest.raises(CustomerHasOrdersError):
        db.delete_customer(cid)
    db.delete_order(oid)
    db.delete_customer(cid)  # после удаления заказов — можно
    assert db.get_customer(cid) is None


def test_missing_customer_errors(db):
    with pytest.raises(NotFoundError):
        db.delete_customer(999)
    with pytest.raises(NotFoundError):
        db.update_customer(Customer("Нет", id=999))
    with pytest.raises(NotFoundError):
        db.add_order(Order(999, "2025-04-20", [OrderItem("Пицца", 1, 1)]))


# ------------------------------------------------------------------ заказы
def test_order_crud(db):
    cid = db.add_customer(Customer("Иван"))
    other = db.add_customer(Customer("Мария"))
    oid = db.add_order(Order(cid, "2025-04-20", [OrderItem("Пицца", 2, 750), OrderItem("Сок", 1, 100)]))

    order = db.get_order(oid)
    assert order.total == 1600.0
    assert [i.product_name for i in order.items] == ["Пицца", "Сок"]

    db.update_order(Order(other, "2025-04-22", [OrderItem("Суши", 1, 999)], "выполнен", id=oid))
    order = db.get_order(oid)
    assert (order.customer_id, order.status, order.total) == (other, "выполнен", 999.0)
    assert len(order.items) == 1

    db.delete_order(oid)
    assert db.get_order(oid) is None
    with pytest.raises(NotFoundError):
        db.delete_order(oid)
    with pytest.raises(NotFoundError):
        db.update_order(Order(cid, "2025-04-20", [OrderItem("Пицца", 1, 1)], id=oid))


def test_filter_orders(filled_db):
    assert len(filled_db.list_orders()) == 5
    assert len(filled_db.list_orders(status="выполнен")) == 2
    april = filled_db.list_orders(date_from="2025-04-01", date_to="2025-04-30")
    assert len(april) == 4
    assert [o.order_date for o in april] == sorted(o.order_date for o in april)
    assert len(filled_db.list_orders(status="выполнен", date_from="2025-04-10")) == 1
    with pytest.raises(ValidationError):
        filled_db.list_orders(status="неизвестный")
    with pytest.raises(ValidationError):
        filled_db.list_orders(date_from="01.04.2025")


# ------------------------------------------------------------------ отчёты
def test_count_by_status(filled_db):
    assert filled_db.orders_count_by_status() == {
        "новый": 1, "в доставке": 1, "выполнен": 2, "отменён": 1}


def test_top_customers(filled_db):
    top = filled_db.top_customers()
    assert [(c.name, total) for c, total in top] == [("Мария", 3000.0), ("Иван", 2000.0), ("Пётр", 200.0)]
    assert len(filled_db.top_customers(limit=1)) == 1


@pytest.mark.parametrize("period,expected,count", [
    ("day", 1500.0, 1),     # 2025-04-20
    ("week", 1500.0, 1),    # 14.04–20.04 (воскресенье входит в неделю)
    ("month", 5200.0, 4),   # апрель без отменённого мартовского заказа
])
def test_revenue(filled_db, period, expected, count):
    rev = filled_db.revenue(period, "2025-04-20")
    assert (rev["revenue"], rev["orders"]) == (expected, count)


def test_report_and_format(filled_db):
    report = filled_db.build_report("week", "2025-04-21")
    assert report["revenue"]["revenue"] == 3500.0
    text = format_report(report)
    assert "Мария" in text and "3500.00" in text and "неделя" in text


def test_format_empty_report(db):
    assert "нет данных" in format_report(db.build_report())


def test_period_bounds():
    assert period_bounds("day", "2025-04-20") == ("2025-04-20", "2025-04-20")
    assert period_bounds("week", "2025-04-23") == ("2025-04-21", "2025-04-27")
    assert period_bounds("month", "2024-02-10") == ("2024-02-01", "2024-02-29")
    with pytest.raises(ValueError):
        period_bounds("year")


# ------------------------------------------------------------------ прочее
def test_persistence(tmp_path):
    for backend, name in (("sqlite", "p.db"), ("tinydb", "p.json")):
        path = tmp_path / name
        with get_database(backend, path) as db:
            cid = db.add_customer(Customer("Иван"))
            db.add_order(Order(cid, "2025-04-20", [OrderItem("Пицца", 1, 500)]))
        with get_database(backend, path) as db:
            assert db.list_orders()[0].total == 500.0


def test_get_database_unknown():
    with pytest.raises(ValueError):
        get_database("mongodb")


def test_sqlite_constraints_in_schema():
    """Ограничения из ТЗ действуют и на уровне самой SQLite."""
    import sqlite3

    db = SQLiteDatabase(":memory:")
    cid = db.add_customer(Customer("Иван"))
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO orders (customer_id, order_date, status, total) "
                        "VALUES (?, '2025-01-01', 'потерян', 1)", (cid,))
    db.add_order(Order(cid, "2025-04-20", [OrderItem("Пицца", 1, 500)]))
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
    db.close()
