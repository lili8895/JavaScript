"""CLI-точка входа приложения «Быстрая доставка» (argparse).

Примеры:
    python main_cli.py report --period month
    python main_cli.py export --file orders_backup.xml
    python main_cli.py import --file orders_new.json
    python main_cli.py --db tinydb orders list --status новый
"""
import argparse
import logging
import sys
from datetime import date, timedelta
from typing import List, Optional

from data_export import FORMATS, ImportFormatError, export_orders, import_orders
from database import BACKENDS, PERIODS, Database, DatabaseError, format_report, get_database
from logger_config import setup_logging
from models import STATUSES, Customer, Order, OrderItem, ValidationError

logger = logging.getLogger("delivery.cli")


def parse_item(text: str) -> OrderItem:
    """Разбирает позицию вида 'Название:количество:цена'."""
    parts = text.rsplit(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"Позиция '{text}' должна иметь вид 'Название:кол-во:цена'")
    name, qty, price = parts
    try:
        return OrderItem(name, int(qty), float(price))
    except (ValueError, ValidationError) as exc:
        raise argparse.ArgumentTypeError(f"Позиция '{text}': {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delivery", description="Учёт заказов «Быстрая доставка»")
    parser.add_argument("--db", choices=BACKENDS, default="sqlite", help="тип БД (по умолчанию sqlite)")
    parser.add_argument("--db-path", help="путь к файлу БД (по умолчанию data/...)")
    parser.add_argument("--log-dir", help="папка для логов (по умолчанию logs/)")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный вывод логов")
    sub = parser.add_subparsers(dest="command", metavar="КОМАНДА")
    sub.required = True

    rep = sub.add_parser("report", help="отчёт: статусы, топ-3 клиента, выручка")
    rep.add_argument("--period", choices=PERIODS, default="month", help="день / неделя / месяц")
    rep.add_argument("--date", help="опорная дата периода ГГГГ-ММ-ДД (по умолчанию сегодня)")

    for name, text in (("export", "экспорт заказов в файл"), ("import", "импорт заказов из файла")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--file", required=True, help="путь к файлу .json или .xml")
        p.add_argument("--format", choices=FORMATS, help="формат (по умолчанию по расширению)")

    cust = sub.add_parser("customers", help="управление клиентами")
    csub = cust.add_subparsers(dest="action", metavar="ДЕЙСТВИЕ")
    csub.required = True
    csub.add_parser("list", help="список клиентов")
    c_add = csub.add_parser("add", help="добавить клиента")
    c_add.add_argument("--name", required=True)
    c_add.add_argument("--phone", default="")
    c_add.add_argument("--address", default="")
    c_upd = csub.add_parser("update", help="изменить клиента")
    c_upd.add_argument("id", type=int)
    c_upd.add_argument("--name")
    c_upd.add_argument("--phone")
    c_upd.add_argument("--address")
    c_del = csub.add_parser("delete", help="удалить клиента (если нет заказов)")
    c_del.add_argument("id", type=int)

    orders = sub.add_parser("orders", help="управление заказами")
    osub = orders.add_subparsers(dest="action", metavar="ДЕЙСТВИЕ")
    osub.required = True
    o_list = osub.add_parser("list", help="список заказов с фильтрами")
    o_list.add_argument("--status", choices=STATUSES)
    o_list.add_argument("--from", dest="date_from", help="дата с (ГГГГ-ММ-ДД)")
    o_list.add_argument("--to", dest="date_to", help="дата по (ГГГГ-ММ-ДД)")
    o_add = osub.add_parser("add", help="добавить заказ")
    o_add.add_argument("--customer-id", type=int, required=True)
    o_add.add_argument("--date", default=date.today().isoformat())
    o_add.add_argument("--status", choices=STATUSES, default="новый")
    o_add.add_argument("--item", type=parse_item, action="append", required=True,
                       help="позиция 'Название:кол-во:цена' (можно несколько раз)")
    o_upd = osub.add_parser("update", help="изменить заказ")
    o_upd.add_argument("id", type=int)
    o_upd.add_argument("--customer-id", type=int)
    o_upd.add_argument("--date")
    o_upd.add_argument("--status", choices=STATUSES)
    o_upd.add_argument("--item", type=parse_item, action="append",
                       help="новый состав заказа (заменяет старый)")
    o_del = osub.add_parser("delete", help="удалить заказ")
    o_del.add_argument("id", type=int)

    sub.add_parser("seed", help="заполнить БД демонстрационными данными")
    return parser


# ------------------------------------------------------------------ команды
def cmd_report(db: Database, args) -> None:
    print(format_report(db.build_report(args.period, args.date)))


def cmd_export(db: Database, args) -> None:
    count = export_orders(db, args.file, args.format)
    print(f"Экспортировано заказов: {count} -> {args.file}")


def cmd_import(db: Database, args) -> None:
    count = import_orders(db, args.file, args.format)
    print(f"Импортировано заказов: {count} из {args.file}")


def cmd_customers(db: Database, args) -> None:
    if args.action == "list":
        customers = db.list_customers()
        if not customers:
            print("Клиентов нет")
        for c in customers:
            print(f"{c.id:>4}  {c.name:<25} {c.phone:<18} {c.address}")
    elif args.action == "add":
        cid = db.add_customer(Customer(args.name, args.phone, args.address))
        print(f"Клиент добавлен, id={cid}")
    elif args.action == "update":
        customer = db.get_customer(args.id)
        if customer is None:
            raise DatabaseError(f"Клиент #{args.id} не найден")
        updated = Customer(args.name if args.name is not None else customer.name,
                           args.phone if args.phone is not None else customer.phone,
                           args.address if args.address is not None else customer.address, customer.id)
        db.update_customer(updated)
        print(f"Клиент #{args.id} обновлён")
    elif args.action == "delete":
        db.delete_customer(args.id)
        print(f"Клиент #{args.id} удалён")


def cmd_orders(db: Database, args) -> None:
    if args.action == "list":
        orders = db.list_orders(args.status, args.date_from, args.date_to)
        names = {c.id: c.name for c in db.list_customers()}
        if not orders:
            print("Заказов нет")
        for o in orders:
            items = ", ".join(f"{i.product_name}×{i.quantity}" for i in o.items)
            print(f"{o.id:>4}  {o.order_date}  {names.get(o.customer_id, '?'):<20} "
                  f"{o.status:<11} {o.total:>10.2f}  {items}")
    elif args.action == "add":
        order = Order(args.customer_id, args.date, args.item, args.status)
        oid = db.add_order(order)
        print(f"Заказ добавлен, id={oid}, сумма {order.total:.2f}")
    elif args.action == "update":
        order = db.get_order(args.id)
        if order is None:
            raise DatabaseError(f"Заказ #{args.id} не найден")
        items = args.item or order.items
        updated = Order(args.customer_id or order.customer_id, args.date or order.order_date,
                        items, args.status or order.status, None, order.id)
        db.update_order(updated)
        print(f"Заказ #{args.id} обновлён, сумма {updated.total:.2f}")
    elif args.action == "delete":
        db.delete_order(args.id)
        print(f"Заказ #{args.id} удалён")


def seed_demo_data(db: Database) -> int:
    """Демонстрационные клиенты и заказы (даты — относительно сегодняшнего дня)."""
    today = date.today()
    customers = [
        Customer("Иван Петров", "+7 900 111-22-33", "г. Москва, ул. Ленина, 1"),
        Customer("Мария Соколова", "+7 900 222-33-44", "г. Москва, пр. Мира, 15"),
        Customer("ООО «Ромашка»", "+7 495 123-45-67", "г. Москва, ул. Садовая, 7"),
        Customer("Алексей Смирнов", "+7 900 333-44-55", "г. Химки, ул. Победы, 3"),
    ]
    ids = [db.add_customer(c) for c in customers]
    demo = [
        (0, 0, "новый", [("Пицца Маргарита", 2, 750)]),
        (1, 1, "в доставке", [("Роллы Филадельфия", 3, 590), ("Соус", 3, 50)]),
        (2, 2, "выполнен", [("Бизнес-ланч", 10, 420)]),
        (0, 5, "выполнен", [("Бургер", 2, 380), ("Картофель фри", 2, 150)]),
        (3, 9, "отменён", [("Пицца Пепперони", 1, 820)]),
        (2, 20, "выполнен", [("Кофе", 12, 180), ("Круассан", 12, 120)]),
        (1, 40, "выполнен", [("Суши-сет", 1, 2400)]),
    ]
    for cust_idx, days_ago, status, items in demo:
        db.add_order(Order(ids[cust_idx], (today - timedelta(days=days_ago)).isoformat(),
                           [OrderItem(*i) for i in items], status))
    return len(demo)


def cmd_seed(db: Database, args) -> None:
    count = seed_demo_data(db)
    print(f"Добавлены демо-данные: 4 клиента, {count} заказов")


COMMANDS = {"report": cmd_report, "export": cmd_export, "import": cmd_import,
            "customers": cmd_customers, "orders": cmd_orders, "seed": cmd_seed}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO, args.log_dir, console=args.verbose)
    logger.info("Запуск CLI: %s", " ".join(argv if argv is not None else sys.argv[1:]))
    try:
        with get_database(args.db, args.db_path) as db:
            COMMANDS[args.command](db, args)
    except (DatabaseError, ValidationError, ImportFormatError, ValueError) as exc:
        logger.error("Ошибка выполнения команды %s: %s", args.command, exc)
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
