"""Unit tests for the shared NGSI-LD value helpers (core/ngsilib.py)."""

from datetime import datetime, timezone

from core import ngsilib as ns


def _prop(value):
    return {"type": "Property", "value": value}


class TestUnwrap:
    def test_scalar_passthrough(self):
        assert ns.unwrap(42) == 42

    def test_property(self):
        assert ns.unwrap({"type": "Property", "value": "x"}) == "x"

    def test_relationship(self):
        assert ns.unwrap({"type": "Relationship", "object": "urn:ngsi-ld:X:1"}) == "urn:ngsi-ld:X:1"

    def test_single_element_list(self):
        assert ns.unwrap([{"type": "Property", "value": 3}]) == 3

    def test_empty_list(self):
        assert ns.unwrap([]) is None

    def test_list_of_wrappers(self):
        assert ns.unwrap([{"type": "Property", "value": 1}, {"type": "Property", "value": 2}]) == [1, 2]

    def test_at_value(self):
        assert ns.unwrap({"@value": "raw"}) == "raw"


class TestDisplayIdentifier:
    def test_urn_tail(self):
        assert ns.display_identifier("urn:ngsi-ld:GtfsRoute:SZ_1") == "SZ_1"

    def test_non_urn(self):
        assert ns.display_identifier({"type": "Property", "value": "SZ_1"}) == "SZ_1"

    def test_none(self):
        assert ns.display_identifier(None) == ""


class TestDateHelpers:
    def test_display_time(self):
        assert ns.display_time("2026-05-11T14:00:00Z") == "2026.05.11 14:00"

    def test_display_time_interval(self):
        value = "2026-07-01T12:00:00Z/2026-07-01T13:00:00Z"
        assert ns.display_time(value) == "2026.07.01 12:00 - 2026.07.01 13:00"

    def test_chart_time(self):
        assert ns.chart_time("2026-05-11T14:05:00Z") == "14:05"

    def test_traffic_time_instant(self):
        assert ns.traffic_time("2026-05-11T14:00:00Z") == datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)

    def test_traffic_time_midpoint(self):
        got = ns.traffic_time("2026-05-11T12:00:00Z/2026-05-11T12:10:00Z")
        assert got == datetime(2026, 5, 11, 12, 5, tzinfo=timezone.utc)


class TestRecordKey:
    def test_deterministic(self):
        row = {"a": "1", "b": "2"}
        assert ns.record_key(row, ["a", "b"]) == ns.record_key(row, ["a", "b"])
        assert ns.record_key(row, ["a", "b"]) != ns.record_key({"a": "2", "b": "1"}, ["a", "b"])

    def test_stable_across_field_order(self):
        assert ns.record_key({"a": "1", "b": "2"}, ["a", "b"]) == ns.record_key({"b": "2", "a": "1"}, ["b", "a"])


class TestFieldTypes:
    def test_numeric_when_all_float(self):
        rows = [{"n": "1.5"}, {"n": "2"}]
        assert ns.infer_field_types(rows, ["n"]) == {"n": "numeric"}

    def test_text_when_mixed(self):
        rows = [{"n": "1.5"}, {"n": "abc"}]
        assert ns.infer_field_types(rows, ["n"]) == {"n": "text"}

    def test_convert_record(self):
        rows = [{"n": "1.5", "s": "x"}]
        field_types = ns.infer_field_types(rows, ["n", "s"])
        record = ns.convert_record({"n": "1.5", "s": "x"}, field_types, ["n", "s"])
        assert record["n"] == 1.5
        assert record["s"] == "x"
        assert record["recordKey"] == ns.record_key({"n": "1.5", "s": "x"}, ["n", "s"])

    def test_convert_record_empty(self):
        record = ns.convert_record({"n": "", "s": None}, {"n": "text", "s": "text"}, ["n", "s"])
        assert record["n"] is None
        assert record["s"] is None
