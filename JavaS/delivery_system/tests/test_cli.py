import pytest

from main_cli import main


@pytest.fixture(params=["sqlite", "tinydb"])
def run(request, tmp_path):
    db_path = tmp_path / ("cli.db" if request.param == "sqlite" else "cli.json")
    base = ["--db", request.param, "--db-path", str(db_path), "--log-dir", str(tmp_path / "logs")]

    def _run(*args):
        return main(base + list(args))

    return _run


def test_full_scenario(run, tmp_path, capsys):
    assert run("customers", "add", "--name", "Иван", "--phone", "+79001112233", "--address", "Москва") == 0
    assert run("customers", "update", "1", "--name", "Иван Петров") == 0
    assert run("orders", "add", "--customer-id", "1", "--date", "2025-04-20",
               "--item", "Пицца:2:750", "--item", "Сок:1:100") == 0
    assert run("orders", "update", "1", "--status", "выполнен") == 0
    assert run("orders", "list", "--status", "выполнен") == 0
    assert run("customers", "list") == 0
    out = capsys.readouterr().out
    assert "Иван Петров" in out and "1600.00" in out

    assert run("report", "--period", "month", "--date", "2025-04-01") == 0
    assert "1600.00" in capsys.readouterr().out

    backup = tmp_path / "backup.xml"
    assert run("export", "--file", str(backup)) == 0
    assert run("import", "--file", str(backup)) == 0
    assert run("orders", "list") == 0
    assert capsys.readouterr().out.count("Пицца") >= 2

    # клиента с заказами удалить нельзя
    assert run("customers", "delete", "1") == 1
    assert "нельзя удалить" in capsys.readouterr().err
    assert run("orders", "delete", "1") == 0
    assert run("orders", "delete", "2") == 0
    assert run("customers", "delete", "1") == 0


def test_seed_and_reports(run, capsys):
    assert run("seed") == 0
    for period in ("day", "week", "month"):
        assert run("report", "--period", period) == 0
    out = capsys.readouterr().out
    assert "Топ-3" in out and "Выручка" in out


def test_errors(run, tmp_path, capsys):
    assert run("orders", "list") == 0
    assert run("customers", "list") == 0
    assert run("orders", "add", "--customer-id", "42", "--item", "А:1:1") == 1
    assert run("orders", "update", "42") == 1
    assert run("customers", "update", "42", "--name", "X") == 1
    assert run("import", "--file", str(tmp_path / "none.json")) == 1
    assert run("report", "--date", "плохая-дата") == 1
    assert "Ошибка" in capsys.readouterr().err


def test_bad_item_argument(run):
    with pytest.raises(SystemExit):
        run("orders", "add", "--customer-id", "1", "--item", "без-цены")
    with pytest.raises(SystemExit):
        run("orders", "add", "--customer-id", "1", "--item", "Пицца:два:100")
