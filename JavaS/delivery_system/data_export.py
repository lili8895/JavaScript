"""Экспорт и импорт заказов в форматах JSON и XML с проверкой корректности."""
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from database import Database
from models import Customer, Order, OrderItem, ValidationError

logger = logging.getLogger("delivery.export")

FORMATS = ("json", "xml")


class ImportFormatError(ValueError):
    """Файл импорта повреждён или содержит некорректные данные."""


def detect_format(path, fmt: Optional[str] = None) -> str:
    """Формат берётся из аргумента или из расширения файла."""
    fmt = (fmt or Path(path).suffix.lstrip(".")).lower()
    if fmt not in FORMATS:
        raise ImportFormatError(f"Неподдерживаемый формат '{fmt}'. Допустимые: {', '.join(FORMATS)}")
    return fmt


# ------------------------------------------------------------------ экспорт
def _order_record(db: Database, order: Order) -> Dict[str, Any]:
    customer = db.get_customer(order.customer_id)
    return {
        "id": order.id,
        "order_date": order.order_date,
        "status": order.status,
        "total": order.total,
        "customer": customer.to_dict(include_id=False),
        "items": [item.to_dict() for item in order.items],
    }


def _write_xml(records: List[Dict], path: Path) -> None:
    root = ET.Element("orders", exported_at=datetime.now().isoformat(timespec="seconds"))
    for rec in records:
        el = ET.SubElement(root, "order", id=str(rec["id"]), order_date=rec["order_date"],
                           status=rec["status"], total=f"{rec['total']:.2f}")
        cust = ET.SubElement(el, "customer")
        for key, value in rec["customer"].items():
            ET.SubElement(cust, key).text = value
        items = ET.SubElement(el, "items")
        for item in rec["items"]:
            item_el = ET.SubElement(items, "item")
            ET.SubElement(item_el, "product_name").text = item["product_name"]
            ET.SubElement(item_el, "quantity").text = str(item["quantity"])
            ET.SubElement(item_el, "price").text = f"{item['price']:.2f}"
    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):  # Python 3.9+
        ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def export_orders(db: Database, path, fmt: Optional[str] = None) -> int:
    """Экспортирует все заказы в файл. Возвращает количество заказов."""
    fmt = detect_format(path, fmt)
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    records = [_order_record(db, o) for o in db.list_orders()]
    if fmt == "json":
        payload = {"exported_at": datetime.now().isoformat(timespec="seconds"), "orders": records}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        _write_xml(records, path)
    logger.info("Экспортировано %d заказов в %s (%s)", len(records), path, fmt)
    return len(records)


# ------------------------------------------------------------------ импорт
def _read_json(path: Path) -> List[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ImportFormatError(f"Некорректный JSON: {exc}")
    if isinstance(data, dict):
        data = data.get("orders")
    if not isinstance(data, list):
        raise ImportFormatError("JSON должен содержать список заказов (ключ 'orders')")
    return data


def _text(parent, tag: str) -> Optional[str]:
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _read_xml(path: Path) -> List[Dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ImportFormatError(f"Некорректный XML: {exc}")
    if root.tag != "orders":
        raise ImportFormatError(f"Корневой элемент должен быть <orders>, а не <{root.tag}>")
    records = []
    for el in root.findall("order"):
        rec: Dict[str, Any] = {
            "order_date": el.get("order_date"),
            "status": el.get("status", "новый"),
            "total": el.get("total"),
            "items": [
                {"product_name": _text(i, "product_name"), "quantity": _text(i, "quantity"),
                 "price": _text(i, "price")}
                for i in el.findall("items/item")
            ],
        }
        cust = el.find("customer")
        if cust is not None:
            rec["customer"] = {k: _text(cust, k) or "" for k in ("name", "phone", "address")}
        elif el.get("customer_id"):
            rec["customer_id"] = el.get("customer_id")
        records.append(rec)
    return records


def _to_int(value: Any) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"ожидалось целое число, получено {value!r}")
    return int(value)


def _to_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"ожидалось число, получено {value!r}")
    return float(value)


def _parse_record(rec: Any, index: int) -> Tuple[Optional[Customer], Optional[int], Order]:
    """Проверяет одну запись. Возвращает (новый клиент | None, id клиента | None, заказ)."""
    try:
        if not isinstance(rec, dict):
            raise ValueError("запись заказа должна быть объектом")
        customer, customer_id = None, None
        if isinstance(rec.get("customer"), dict):
            customer = Customer.from_dict(rec["customer"])
        elif rec.get("customer_id") is not None:
            customer_id = _to_int(rec["customer_id"])
        else:
            raise ValueError("не указан клиент (customer или customer_id)")
        raw_items = rec.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("поле items должно быть списком")
        items = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError("позиция заказа должна быть объектом")
            items.append(OrderItem(item.get("product_name"), _to_int(item.get("quantity")),
                                   _to_float(item.get("price"))))
        total = rec.get("total")
        order = Order(customer_id=customer_id or 1, order_date=rec.get("order_date"), items=items,
                      status=rec.get("status", "новый"),
                      total=_to_float(total) if total not in (None, "") else None)
        return customer, customer_id, order
    except (ValidationError, ValueError, TypeError) as exc:
        raise ImportFormatError(f"Заказ №{index}: {exc}")


def import_orders(db: Database, path, fmt: Optional[str] = None) -> int:
    """Импортирует заказы. Сначала проверяются ВСЕ записи, и только потом идёт запись в БД:
    при любой ошибке база не меняется. Клиенты сопоставляются по имени и телефону."""
    fmt = detect_format(path, fmt)
    path = Path(path)
    if not path.is_file():
        raise ImportFormatError(f"Файл не найден: {path}")
    raw = _read_json(path) if fmt == "json" else _read_xml(path)
    parsed = [_parse_record(rec, i) for i, rec in enumerate(raw, 1)]
    for i, (_, customer_id, _) in enumerate(parsed, 1):
        if customer_id is not None and db.get_customer(customer_id) is None:
            raise ImportFormatError(f"Заказ №{i}: клиент #{customer_id} не найден в базе")

    known = {(c.name, c.phone): c.id for c in db.list_customers()}
    for customer, customer_id, order in parsed:
        if customer is not None:
            key = (customer.name, customer.phone)
            if key not in known:
                known[key] = db.add_customer(customer)
            customer_id = known[key]
        order.customer_id = customer_id
        db.add_order(order)
    logger.info("Импортировано %d заказов из %s (%s)", len(parsed), path, fmt)
    return len(parsed)
