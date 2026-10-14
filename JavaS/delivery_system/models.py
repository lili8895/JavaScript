"""Модели предметной области: клиент, позиция заказа, заказ."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

STATUSES = ("новый", "в доставке", "выполнен", "отменён")
DATE_FORMAT = "%Y-%m-%d"
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{5,20}$")


class ValidationError(ValueError):
    """Некорректные данные модели."""


def validate_date(value: Any) -> str:
    """Проверяет, что дата задана строкой формата ГГГГ-ММ-ДД."""
    try:
        datetime.strptime(value, DATE_FORMAT)
    except (TypeError, ValueError):
        raise ValidationError(f"Некорректная дата '{value}', ожидается ГГГГ-ММ-ДД")
    return value


@dataclass
class Customer:
    name: str
    phone: str = ""
    address: str = ""
    id: Optional[int] = None

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("Имя клиента не может быть пустым")
        self.name = self.name.strip()
        self.phone = str(self.phone or "").strip()
        self.address = str(self.address or "").strip()
        if self.phone and not PHONE_RE.match(self.phone):
            raise ValidationError(f"Некорректный телефон '{self.phone}'")

    def to_dict(self, include_id: bool = True) -> Dict[str, Any]:
        data = {"name": self.name, "phone": self.phone, "address": self.address}
        if include_id:
            data = {"id": self.id, **data}
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Customer":
        return cls(name=data.get("name"), phone=data.get("phone", ""),
                   address=data.get("address", ""), id=data.get("id"))


@dataclass
class OrderItem:
    product_name: str
    quantity: int
    price: float

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.product_name, str) or not self.product_name.strip():
            raise ValidationError("Название товара не может быть пустым")
        self.product_name = self.product_name.strip()
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValidationError(f"Количество должно быть целым числом > 0 (получено {self.quantity!r})")
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float)) or self.price < 0:
            raise ValidationError(f"Цена должна быть числом >= 0 (получено {self.price!r})")
        self.price = float(self.price)

    @property
    def subtotal(self) -> float:
        return round(self.quantity * self.price, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {"product_name": self.product_name, "quantity": self.quantity, "price": self.price}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderItem":
        return cls(data.get("product_name"), data.get("quantity"), data.get("price"))


@dataclass
class Order:
    customer_id: int
    order_date: str
    items: List[OrderItem] = field(default_factory=list)
    status: str = "новый"
    total: Optional[float] = None
    id: Optional[int] = None

    def __post_init__(self):
        self.items = [OrderItem.from_dict(i) if isinstance(i, dict) else i for i in self.items]
        if self.total is None:
            self.total = self.calculate_total()
        self.validate()

    def calculate_total(self) -> float:
        return round(sum(item.subtotal for item in self.items), 2)

    def validate(self) -> None:
        if isinstance(self.customer_id, bool) or not isinstance(self.customer_id, int) or self.customer_id <= 0:
            raise ValidationError("Не выбран клиент заказа")
        validate_date(self.order_date)
        if self.status not in STATUSES:
            raise ValidationError(f"Недопустимый статус '{self.status}'. Допустимые: {', '.join(STATUSES)}")
        if not self.items:
            raise ValidationError("Заказ должен содержать хотя бы один товар")
        for item in self.items:
            if not isinstance(item, OrderItem):
                raise ValidationError("Позиция заказа имеет неверный тип")
            item.validate()
        try:
            self.total = round(float(self.total), 2)
        except (TypeError, ValueError):
            raise ValidationError(f"Некорректная сумма заказа '{self.total}'")
        if abs(self.total - self.calculate_total()) > 0.01:
            raise ValidationError(
                f"Сумма заказа {self.total} не совпадает с суммой позиций {self.calculate_total()}")

    def to_dict(self, include_id: bool = True) -> Dict[str, Any]:
        data = {
            "customer_id": self.customer_id,
            "order_date": self.order_date,
            "status": self.status,
            "total": self.total,
            "items": [item.to_dict() for item in self.items],
        }
        if include_id:
            data = {"id": self.id, **data}
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Order":
        return cls(customer_id=data.get("customer_id"), order_date=data.get("order_date"),
                   items=list(data.get("items") or []), status=data.get("status", "новый"),
                   total=data.get("total"), id=data.get("id"))
