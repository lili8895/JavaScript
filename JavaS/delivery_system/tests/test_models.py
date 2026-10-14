import pytest

from models import Customer, Order, OrderItem, ValidationError, validate_date


class TestCustomer:
    def test_create_and_strip(self):
        c = Customer("  Иван  ", " +7 (900) 123-45-67 ", " Москва ")
        assert (c.name, c.phone, c.address) == ("Иван", "+7 (900) 123-45-67", "Москва")

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_empty_name(self, name):
        with pytest.raises(ValidationError):
            Customer(name)

    def test_bad_phone(self):
        with pytest.raises(ValidationError):
            Customer("Иван", "abc")

    def test_dict_roundtrip(self):
        c = Customer("Иван", "+79001112233", "Москва", id=5)
        assert Customer.from_dict(c.to_dict()) == c
        assert "id" not in c.to_dict(include_id=False)


class TestOrderItem:
    def test_subtotal(self):
        assert OrderItem("Пицца", 3, 250.5).subtotal == 751.5

    @pytest.mark.parametrize("name,qty,price", [
        ("", 1, 10), ("Пицца", 0, 10), ("Пицца", -1, 10), ("Пицца", 1.5, 10),
        ("Пицца", True, 10), ("Пицца", 1, -5), ("Пицца", 1, "10"),
    ])
    def test_invalid(self, name, qty, price):
        with pytest.raises(ValidationError):
            OrderItem(name, qty, price)


class TestOrder:
    def test_total_calculated(self):
        order = Order(1, "2025-04-20", [OrderItem("Пицца", 2, 750), OrderItem("Сок", 1, 120)])
        assert order.total == 1620.0
        assert order.status == "новый"

    def test_items_from_dicts(self):
        order = Order(1, "2025-04-20", [{"product_name": "Пицца", "quantity": 2, "price": 750}])
        assert isinstance(order.items[0], OrderItem)

    def test_total_mismatch(self):
        with pytest.raises(ValidationError, match="не совпадает"):
            Order(1, "2025-04-20", [OrderItem("Пицца", 2, 750)], total=100)

    @pytest.mark.parametrize("kwargs", [
        {"status": "потерян"},
        {"order_date": "20.04.2025"},
        {"order_date": "2025-02-30"},
        {"customer_id": 0},
        {"customer_id": None},
        {"items": []},
        {"total": "abc"},
    ])
    def test_invalid(self, kwargs):
        data = {"customer_id": 1, "order_date": "2025-04-20", "items": [OrderItem("Пицца", 1, 100)]}
        data.update(kwargs)
        with pytest.raises(ValidationError):
            Order(**data)

    def test_dict_roundtrip(self):
        order = Order(2, "2025-04-20", [OrderItem("Пицца", 2, 750)], "выполнен", id=7)
        restored = Order.from_dict(order.to_dict())
        assert restored == order
        assert restored.to_dict()["items"] == [{"product_name": "Пицца", "quantity": 2, "price": 750.0}]


def test_validate_date():
    assert validate_date("2025-04-20") == "2025-04-20"
    with pytest.raises(ValidationError):
        validate_date(None)
