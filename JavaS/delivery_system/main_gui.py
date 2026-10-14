"""GUI-точка входа (Tkinter): список заказов, формы заказа и клиента, отчёт, экспорт/импорт.

Запуск:
    python main_gui.py               # SQLite
    python main_gui.py --db tinydb   # TinyDB
"""
import argparse
import logging
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from data_export import ImportFormatError, export_orders, import_orders
from database import (BACKENDS, PERIOD_NAMES, PERIODS, CustomerHasOrdersError, Database,
                      DatabaseError, format_report, get_database)
from logger_config import setup_logging
from models import STATUSES, Customer, Order, OrderItem, ValidationError

logger = logging.getLogger("delivery.gui")
ALL = "все"
ERRORS = (DatabaseError, ValidationError, ImportFormatError, ValueError)


class Dialog(tk.Toplevel):
    """Базовое модальное окно."""

    def __init__(self, master, title: str):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.result = None
        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill="both", expand=True)

    def show(self):
        self.grab_set()
        self.wait_window(self)
        return self.result


# ------------------------------------------------------------------ клиенты
class CustomerDialog(Dialog):
    def __init__(self, master, customer: Customer = None):
        super().__init__(master, "Редактирование клиента" if customer else "Новый клиент")
        self.customer = customer
        self.vars = {}
        for row, (key, label) in enumerate((("name", "Имя*"), ("phone", "Телефон"), ("address", "Адрес"))):
            ttk.Label(self.body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=getattr(customer, key, "") if customer else "")
            ttk.Entry(self.body, textvariable=var, width=40).grid(row=row, column=1, pady=3)
            self.vars[key] = var
        buttons = ttk.Frame(self.body)
        buttons.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=5)

    def save(self):
        try:
            self.result = Customer(self.vars["name"].get(), self.vars["phone"].get(),
                                   self.vars["address"].get(),
                                   self.customer.id if self.customer else None)
        except ValidationError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self)
            return
        self.destroy()


class CustomersWindow(tk.Toplevel):
    def __init__(self, master, db: Database, on_change):
        super().__init__(master)
        self.title("Клиенты")
        self.geometry("700x350")
        self.db, self.on_change = db, on_change
        cols = ("id", "name", "phone", "address")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, text, width in zip(cols, ("ID", "Имя", "Телефон", "Адрес"), (50, 200, 140, 280)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        self.tree.bind("<Double-1>", lambda e: self.edit())
        buttons = ttk.Frame(self)
        buttons.pack(pady=(0, 10))
        for text, cmd in (("Добавить", self.add), ("Редактировать", self.edit), ("Удалить", self.delete)):
            ttk.Button(buttons, text=text, command=cmd).pack(side="left", padx=5)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for c in self.db.list_customers():
            self.tree.insert("", "end", iid=str(c.id), values=(c.id, c.name, c.phone, c.address))

    def selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Клиенты", "Выберите клиента", parent=self)
            return None
        return int(sel[0])

    def add(self):
        customer = CustomerDialog(self).show()
        if customer:
            self._run(lambda: self.db.add_customer(customer))

    def edit(self):
        cid = self.selected_id()
        if cid is None:
            return
        customer = CustomerDialog(self, self.db.get_customer(cid)).show()
        if customer:
            self._run(lambda: self.db.update_customer(customer))

    def delete(self):
        cid = self.selected_id()
        if cid is None or not messagebox.askyesno("Удаление", f"Удалить клиента #{cid}?", parent=self):
            return
        self._run(lambda: self.db.delete_customer(cid))

    def _run(self, action):
        try:
            action()
        except CustomerHasOrdersError as exc:
            messagebox.showwarning("Нельзя удалить", str(exc), parent=self)
        except ERRORS as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self)
        self.refresh()
        self.on_change()


# ------------------------------------------------------------------ заказы
class OrderDialog(Dialog):
    def __init__(self, master, db: Database, order: Order = None):
        super().__init__(master, f"Заказ #{order.id}" if order else "Новый заказ")
        self.order = order
        self.customers = db.list_customers()
        self.items = [OrderItem(i.product_name, i.quantity, i.price) for i in order.items] if order else []

        f = self.body
        ttk.Label(f, text="Клиент*").grid(row=0, column=0, sticky="w")
        self.customer_var = tk.StringVar()
        labels = [f"{c.id}: {c.name}" for c in self.customers]
        ttk.Combobox(f, textvariable=self.customer_var, values=labels, state="readonly",
                     width=37).grid(row=0, column=1, columnspan=3, sticky="w", pady=3)
        if order:
            self.customer_var.set(next((l for c, l in zip(self.customers, labels)
                                        if c.id == order.customer_id), ""))

        ttk.Label(f, text="Дата*").grid(row=1, column=0, sticky="w")
        self.date_var = tk.StringVar(value=order.order_date if order else date.today().isoformat())
        ttk.Entry(f, textvariable=self.date_var, width=15).grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(f, text="Статус").grid(row=2, column=0, sticky="w")
        self.status_var = tk.StringVar(value=order.status if order else STATUSES[0])
        ttk.Combobox(f, textvariable=self.status_var, values=STATUSES, state="readonly",
                     width=15).grid(row=2, column=1, sticky="w", pady=3)

        cols = ("name", "qty", "price", "sum")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=6)
        for col, text, width in zip(cols, ("Товар", "Кол-во", "Цена", "Сумма"), (200, 70, 90, 90)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width)
        self.tree.grid(row=3, column=0, columnspan=4, pady=(8, 4))

        self.item_vars = [tk.StringVar(), tk.StringVar(value="1"), tk.StringVar()]
        entry_row = ttk.Frame(f)
        entry_row.grid(row=4, column=0, columnspan=4, sticky="w")
        for text, var, width in zip(("Товар", "Кол-во", "Цена"), self.item_vars, (22, 6, 9)):
            ttk.Label(entry_row, text=text).pack(side="left", padx=(0, 3))
            ttk.Entry(entry_row, textvariable=var, width=width).pack(side="left", padx=(0, 8))
        ttk.Button(entry_row, text="+ Товар", command=self.add_item).pack(side="left")
        ttk.Button(entry_row, text="− Убрать", command=self.remove_item).pack(side="left", padx=4)

        self.total_var = tk.StringVar()
        ttk.Label(f, textvariable=self.total_var, font=("TkDefaultFont", 10, "bold")).grid(
            row=5, column=0, columnspan=4, sticky="e", pady=6)
        buttons = ttk.Frame(f)
        buttons.grid(row=6, column=0, columnspan=4)
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=5)
        self.refresh_items()

    def refresh_items(self):
        self.tree.delete(*self.tree.get_children())
        for idx, item in enumerate(self.items):
            self.tree.insert("", "end", iid=str(idx), values=(
                item.product_name, item.quantity, f"{item.price:.2f}", f"{item.subtotal:.2f}"))
        self.total_var.set(f"Итого: {sum(i.subtotal for i in self.items):.2f} руб.")

    def add_item(self):
        name, qty, price = (v.get() for v in self.item_vars)
        try:
            item = OrderItem(name, int(qty), float(price.replace(",", ".")))
        except (ValueError, ValidationError) as exc:
            messagebox.showerror("Ошибка", f"Некорректная позиция: {exc}", parent=self)
            return
        self.items.append(item)
        self.item_vars[0].set("")
        self.item_vars[2].set("")
        self.refresh_items()

    def remove_item(self):
        for iid in sorted(self.tree.selection(), key=int, reverse=True):
            del self.items[int(iid)]
        self.refresh_items()

    def save(self):
        if not self.customer_var.get():
            messagebox.showerror("Ошибка", "Выберите клиента", parent=self)
            return
        customer_id = int(self.customer_var.get().split(":", 1)[0])
        try:
            self.result = Order(customer_id, self.date_var.get().strip(), list(self.items),
                                self.status_var.get(), None, self.order.id if self.order else None)
        except ValidationError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self)
            return
        self.destroy()


class ReportWindow(tk.Toplevel):
    def __init__(self, master, db: Database):
        super().__init__(master)
        self.title("Отчёт")
        self.db = db
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Период:").pack(side="left")
        self.period_var = tk.StringVar(value=PERIOD_NAMES["month"])
        box = ttk.Combobox(top, textvariable=self.period_var, state="readonly", width=10,
                           values=[PERIOD_NAMES[p] for p in PERIODS])
        box.pack(side="left", padx=5)
        box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(top, text="Дата:").pack(side="left", padx=(10, 0))
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(top, textvariable=self.date_var, width=12).pack(side="left", padx=5)
        ttk.Button(top, text="Обновить", command=self.refresh).pack(side="left")
        self.text = tk.Text(self, width=60, height=18, font=("Courier", 10))
        self.text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.refresh()

    def refresh(self):
        period = next(p for p, name in PERIOD_NAMES.items() if name == self.period_var.get())
        try:
            text = format_report(self.db.build_report(period, self.date_var.get().strip() or None))
        except ERRORS as exc:
            text = f"Ошибка: {exc}"
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")


# ------------------------------------------------------------------ главное окно
class DeliveryApp(tk.Tk):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.title(f"Быстрая доставка — учёт заказов ({db.backend})")
        self.geometry("950x520")
        self.minsize(800, 400)

        filters = ttk.LabelFrame(self, text="Фильтр", padding=8)
        filters.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(filters, text="Статус:").pack(side="left")
        self.status_var = tk.StringVar(value=ALL)
        status_box = ttk.Combobox(filters, textvariable=self.status_var, state="readonly",
                                  values=(ALL,) + STATUSES, width=12)
        status_box.pack(side="left", padx=5)
        status_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.from_var, self.to_var = tk.StringVar(), tk.StringVar()
        for text, var in (("Дата с:", self.from_var), ("по:", self.to_var)):
            ttk.Label(filters, text=text).pack(side="left", padx=(10, 0))
            ttk.Entry(filters, textvariable=var, width=12).pack(side="left", padx=5)
        ttk.Button(filters, text="Применить", command=self.refresh).pack(side="left", padx=5)
        ttk.Button(filters, text="Сбросить", command=self.reset_filters).pack(side="left")

        cols = ("id", "date", "customer", "status", "items", "total")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, text, width, anchor in zip(
                cols, ("ID", "Дата", "Клиент", "Статус", "Товары", "Сумма"),
                (50, 95, 180, 100, 360, 100), ("center", "center", "w", "w", "w", "e")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="top", fill="both", expand=True, padx=(10, 0))
        scroll.place(in_=self.tree, relx=1.0, rely=0, relheight=1.0, anchor="ne")
        self.tree.bind("<Double-1>", lambda e: self.edit_order())

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        for text, cmd in (("Добавить", self.add_order), ("Редактировать", self.edit_order),
                          ("Удалить", self.delete_order), ("Клиенты", self.open_customers),
                          ("Показать отчёт", lambda: ReportWindow(self, self.db))):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        ttk.Button(bar, text="Импорт", command=self.import_data).pack(side="right", padx=3)
        ttk.Button(bar, text="Экспорт", command=self.export_data).pack(side="right", padx=3)
        self.format_var = tk.StringVar(value="JSON")
        ttk.Combobox(bar, textvariable=self.format_var, values=("JSON", "XML"), state="readonly",
                     width=6).pack(side="right", padx=3)
        ttk.Label(bar, text="Формат:").pack(side="right")

        self.status_bar = tk.StringVar()
        ttk.Label(self, textvariable=self.status_bar, anchor="w", padding=(10, 0, 10, 6)).pack(fill="x")
        self.refresh()

    # --- данные
    def refresh(self):
        status = None if self.status_var.get() == ALL else self.status_var.get()
        try:
            orders = self.db.list_orders(status, self.from_var.get().strip() or None,
                                         self.to_var.get().strip() or None)
        except ERRORS as exc:
            messagebox.showerror("Фильтр", str(exc), parent=self)
            return
        names = {c.id: c.name for c in self.db.list_customers()}
        self.tree.delete(*self.tree.get_children())
        for o in orders:
            items = ", ".join(f"{i.product_name} ×{i.quantity}" for i in o.items)
            self.tree.insert("", "end", iid=str(o.id), values=(
                o.id, o.order_date, names.get(o.customer_id, "?"), o.status, items, f"{o.total:.2f}"))
        self.status_bar.set(f"Заказов: {len(orders)} на сумму {sum(o.total for o in orders):.2f} руб.")

    def reset_filters(self):
        self.status_var.set(ALL)
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Заказы", "Выберите заказ в списке", parent=self)
            return None
        return int(sel[0])

    def _run(self, action, success: str = None):
        try:
            action()
        except ERRORS as exc:
            logger.error("Ошибка GUI: %s", exc)
            messagebox.showerror("Ошибка", str(exc), parent=self)
        else:
            if success:
                messagebox.showinfo("Готово", success, parent=self)
        self.refresh()

    # --- действия
    def add_order(self):
        if not self.db.list_customers():
            messagebox.showwarning("Нет клиентов", "Сначала добавьте клиента (кнопка «Клиенты»)", parent=self)
            return
        order = OrderDialog(self, self.db).show()
        if order:
            self._run(lambda: self.db.add_order(order))

    def edit_order(self):
        oid = self.selected_id()
        if oid is None:
            return
        order = OrderDialog(self, self.db, self.db.get_order(oid)).show()
        if order:
            self._run(lambda: self.db.update_order(order))

    def delete_order(self):
        oid = self.selected_id()
        if oid is not None and messagebox.askyesno("Удаление", f"Удалить заказ #{oid}?", parent=self):
            self._run(lambda: self.db.delete_order(oid))

    def open_customers(self):
        CustomersWindow(self, self.db, self.refresh)

    def export_data(self):
        fmt = self.format_var.get().lower()
        path = filedialog.asksaveasfilename(parent=self, defaultextension=f".{fmt}",
                                            initialfile=f"orders_backup.{fmt}",
                                            filetypes=[(fmt.upper(), f"*.{fmt}")])
        if path:
            self._run(lambda: export_orders(self.db, path, fmt), f"Заказы экспортированы в\n{path}")

    def import_data(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[
            ("JSON или XML", "*.json *.xml"), ("JSON", "*.json"), ("XML", "*.xml")])
        if path:
            self._run(lambda: import_orders(self.db, path), "Импорт выполнен")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="GUI учёта заказов «Быстрая доставка»")
    parser.add_argument("--db", choices=BACKENDS, default="sqlite")
    parser.add_argument("--db-path")
    args = parser.parse_args(argv)
    setup_logging()
    logger.info("Запуск GUI (%s)", args.db)
    db = get_database(args.db, args.db_path)
    try:
        DeliveryApp(db).mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()
