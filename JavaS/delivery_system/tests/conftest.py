import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_database  # noqa: E402
from models import Customer, Order, OrderItem  # noqa: E402


@pytest.fixture(params=["sqlite", "tinydb"])
def db(request, tmp_path):
    """Каждый тест БД выполняется на обоих хранилищах."""
    name = "test.db" if request.param == "sqlite" else "test.json"
    database = get_database(request.param, tmp_path / name)
    yield database
    database.close()


@pytest.fixture
def filled_db(db):
    """БД с тремя клиентами и пятью заказами в апреле 2025."""
    ivan = db.add_customer(Customer("Иван", "+7 900 000-00-01", "Москва"))
    maria = db.add_customer(Customer("Мария", "+7 900 000-00-02", "Тверь"))
    petr = db.add_customer(Customer("Пётр", "", ""))
    db.add_order(Order(ivan, "2025-04-20", [OrderItem("Пицца", 2, 750)], "новый"))
    db.add_order(Order(ivan, "2025-04-21", [OrderItem("Роллы", 1, 500)], "выполнен"))
    db.add_order(Order(maria, "2025-04-21", [OrderItem("Бургер", 10, 300)], "в доставке"))
    db.add_order(Order(petr, "2025-04-01", [OrderItem("Кофе", 1, 200)], "выполнен"))
    db.add_order(Order(petr, "2025-03-15", [OrderItem("Торт", 1, 9000)], "отменён"))
    return db
