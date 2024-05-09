from mountaineer.migrations.db_stubs import DBType


def test_merge_type_columns():
    type_a = DBType(
        name="type_a",
        values=frozenset({"A"}),
        reference_columns=frozenset({("table_a", "column_a")}),
    )
    type_b = DBType(
        name="type_a",
        values=frozenset({"A"}),
        reference_columns=frozenset({("table_b", "column_b")}),
    )

    merged = type_a.merge(type_b)
    assert merged.name == "type_a"
    assert merged.values == frozenset({"A"})
    assert merged.reference_columns == frozenset(
        {("table_a", "column_a"), ("table_b", "column_b")}
    )
