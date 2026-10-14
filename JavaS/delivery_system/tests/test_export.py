import json

import pytest

from data_export import ImportFormatError, detect_format, export_orders, import_orders
from database import get_database
from models import Customer


@pytest.fixture
def empty_db(tmp_path):
    db = get_database("sqlite", tmp_path / "target.db")
    yield db
    db.close()


@pytest.mark.parametrize("fmt", ["json", "xml"])
def test_export_import_roundtrip(filled_db, empty_db, tmp_path, fmt):
    path = tmp_path / f"orders.{fmt}"
    assert export_orders(filled_db, path) == 5
    assert import_orders(empty_db, path) == 5

    def snapshot(db):
        names = {c.id: c.name for c in db.list_customers()}
        return sorted((names[o.customer_id], o.order_date, o.status, o.total,
                       tuple((i.product_name, i.quantity, i.price) for i in o.items))
                      for o in db.list_orders())

    assert snapshot(empty_db) == snapshot(filled_db)
    assert len(empty_db.list_customers()) == 3


def test_export_creates_dirs_and_utf8(filled_db, tmp_path):
    path = tmp_path / "nested" / "dir" / "orders.json"
    export_orders(filled_db, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orders"][0]["customer"]["name"] in {"Иван", "Мария", "Пётр"}
    assert "Пицца" in path.read_text(encoding="utf-8")  # без \u-экранирования


def test_import_reuses_existing_customers(filled_db, tmp_path):
    path = tmp_path / "orders.xml"
    export_orders(filled_db, path)
    import_orders(filled_db, path)
    assert len(filled_db.list_customers()) == 3
    assert len(filled_db.list_orders()) == 10


def test_explicit_format_overrides_extension(filled_db, empty_db, tmp_path):
    path = tmp_path / "backup.dat"
    export_orders(filled_db, path, fmt="xml")
    assert path.read_text(encoding="utf-8").startswith("<?xml")
    assert import_orders(empty_db, path, fmt="xml") == 5


def test_import_tz_json_schema_with_customer_id(empty_db, tmp_path):
    """Формат из ТЗ (вариант Б): заказы ссылаются на клиента по customer_id."""
    cid = empty_db.add_customer(Customer("Иван"))
    path = tmp_path / "orders.json"
    path.write_text(json.dumps({"orders": [{
        "id": 1, "customer_id": cid, "order_date": "2025-04-20", "status": "новый", "total": 1500.0,
        "items": [{"product_name": "Пицца", "quantity": 2, "price": 750}]}]}), encoding="utf-8")
    assert import_orders(empty_db, path) == 1
    assert empty_db.list_orders()[0].customer_id == cid


def test_import_xml_with_customer_id_and_list_json(empty_db, tmp_path):
    cid = empty_db.add_customer(Customer("Иван"))
    xml = tmp_path / "o.xml"
    xml.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<orders><order order_date="2025-04-20" status="выполнен" customer_id="{cid}">
<items><item><product_name>Сок</product_name><quantity>3</quantity><price>100</price></item></items>
</order></orders>""", encoding="utf-8")
    assert import_orders(empty_db, xml) == 1
    js = tmp_path / "o.json"  # допускается и просто список заказов
    js.write_text(json.dumps([{"customer": {"name": "Новый"}, "order_date": "2025-04-21",
                               "items": [{"product_name": "Чай", "quantity": 1, "price": 50}]}]),
                  encoding="utf-8")
    assert import_orders(empty_db, js) == 1
    assert empty_db.list_orders()[0].total == 300.0


BAD_RECORDS = [
    ({"customer": {"name": ""}, "order_date": "2025-04-20", "items": [
        {"product_name": "A", "quantity": 1, "price": 1}]}, "Имя"),
    ({"customer": {"name": "И"}, "order_date": "2025-13-01", "items": [
        {"product_name": "A", "quantity": 1, "price": 1}]}, "дата"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "status": "потерян", "items": [
        {"product_name": "A", "quantity": 1, "price": 1}]}, "статус"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "items": [
        {"product_name": "A", "quantity": 1.5, "price": 1}]}, "целое"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "items": [
        {"product_name": "A", "quantity": 1, "price": None}]}, "число"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "total": 999, "items": [
        {"product_name": "A", "quantity": 1, "price": 1}]}, "не совпадает"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "items": "Пицца"}, "списком"),
    ({"customer": {"name": "И"}, "order_date": "2025-04-20", "items": ["Пицца"]}, "объектом"),
    ({"order_date": "2025-04-20", "items": []}, "клиент"),
    ({"customer_id": 777, "order_date": "2025-04-20", "items": [
        {"product_name": "A", "quantity": 1, "price": 1}]}, "не найден"),
    ("строка вместо заказа", "объектом"),
]


@pytest.mark.parametrize("record,message", BAD_RECORDS)
def test_import_invalid_records_are_rejected_atomically(empty_db, tmp_path, record, message):
    good = {"customer": {"name": "Хороший"}, "order_date": "2025-04-20",
            "items": [{"product_name": "A", "quantity": 1, "price": 1}]}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"orders": [good, record]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ImportFormatError, match=message):
        import_orders(empty_db, path)
    # первый корректный заказ тоже не записан — импорт атомарный
    assert empty_db.list_orders() == []
    assert empty_db.list_customers() == []


@pytest.mark.parametrize("name,content,message", [
    ("broken.json", "{not json", "Некорректный JSON"),
    ("wrong.json", '{"orders": 5}', "список"),
    ("broken.xml", "<orders><order>", "Некорректный XML"),
    ("wrong.xml", "<customers/>", "Корневой элемент"),
])
def test_import_broken_files(empty_db, tmp_path, name, content, message):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ImportFormatError, match=message):
        import_orders(empty_db, path)


def test_import_missing_file_and_bad_format(empty_db, tmp_path):
    with pytest.raises(ImportFormatError, match="не найден"):
        import_orders(empty_db, tmp_path / "nope.json")
    with pytest.raises(ImportFormatError, match="Неподдерживаемый"):
        detect_format("orders.csv")
    assert detect_format("ORDERS.XML") == "xml"
