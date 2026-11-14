import excel_writer  # type: ignore[import-not-found]


def test_export_orders_to_excel() -> None:
    assert excel_writer.write([{"id": 1}])
