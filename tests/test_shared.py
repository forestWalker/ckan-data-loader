"""Unit tests for shared row-building helpers (exports/_shared.py)."""

from collections import Counter

from exports import _shared as sh

SMART_DM = "https://smartdatamodels.org/dataModel.Environment/"


def _expanded(name, value):
    return {SMART_DM + name: {"type": "Property", "value": value}}


class TestNormalizeWeather:
    def test_basic_row(self):
        entity = {
            "dateObserved": {"type": "Property", "value": "2026-05-11T12:00:00Z"},
            "windSpeed": {"type": "Property", "value": 3.5},
            "temperature": {"type": "Property", "value": 21},
            **_expanded("pressure", 1013),
        }
        rows = sh.normalize_weather([entity])
        assert rows[0]["temperature_Celsius"] == 21
        assert rows[0]["pressure_hPa"] == 1013
        assert rows[0]["rainfall_L_m2"] is None

    def test_rainfall_falls_back_to_precipitation(self):
        entity = {"precipitation": {"type": "Property", "value": 1.1}}
        assert sh.normalize_weather([entity])[0]["rainfall_L_m2"] == 1.1

    def test_rainfall_prefers_rainfall(self):
        entity = {
            "rainfall": {"type": "Property", "value": 2.0},
            "precipitation": {"type": "Property", "value": 1.1},
        }
        assert sh.normalize_weather([entity])[0]["rainfall_L_m2"] == 2.0


def _expanded(name, value):
    return {SMART_DM + name: {"type": "Property", "value": value}}


class TestNormalizeBio:

    def test_one_row_per_particle(self):
        entity = {
            "dateObserved": {"type": "Property", "value": "2026-05-11T12:00:00Z"},
            "BioParticlesObserved": {
                "type": "Property",
                "value": [
                    {"name": "PM2.5", "particleType": "Particulate", "count": 12},
                    {"name": "PM10", "particleType": "Particulate", "count": 34},
                ],
            },
        }
        rows = sh.normalize_bio([entity])
        assert len(rows) == 2
        assert rows[0]["particleName"] == "PM2.5"
        assert rows[1]["particleCount_count"] == 34

    def test_skips_non_list(self):
        assert sh.normalize_bio([{"BioParticlesObserved": {"type": "Property", "value": 1}}]) == []


class TestJoinNearest:
    def test_joins_to_nearest(self):
        left = [{"t": "2026-05-11T12:01:00Z", "a": 1}]
        right = [{"t": "2026-05-11T12:00:00Z", "b": 2}]
        out = sh.join_nearest(left, right, 5, "t", "t")
        assert out[0]["b"] == 2
        assert out[0]["timeDifferenceMinutes"] == 1

    def test_drops_beyond_max_gap(self):
        left = [{"t": "2026-05-11T12:30:00Z", "a": 1}]
        right = [{"t": "2026-05-11T12:00:00Z", "b": 2}]
        assert sh.join_nearest(left, right, 5, "t", "t") == []

    def test_skips_left_row_without_time(self):
        out = sh.join_nearest([{"a": 1}], [{"t": "2026-05-11T12:00:00Z", "b": 2}], 5, "t", "t")
        assert out == []


class TestMisc:
    def test_entity_map(self):
        assert sh.entity_map([{"id": "urn:1"}, {"id": "urn:2"}]) == {"urn:1": {"id": "urn:1"}, "urn:2": {"id": "urn:2"}}

    def test_entity_map_skips_missing_id(self):
        assert sh.entity_map([{"name": "x"}]) == {}

    def test_count_by_trip(self):
        stoptimes = [
            {"_stopId": {"type": "Property", "value": "S1"}, "hasTrip": {"type": "Relationship", "object": "urn:T1"}},
            {"_stopId": {"type": "Property", "value": "S1"}, "hasTrip": {"type": "Relationship", "object": "urn:T1"}},
            {"_stopId": {"type": "Property", "value": "S1"}, "hasTrip": {"type": "Relationship", "object": "urn:T2"}},
        ]
        trip_to_route = {"urn:T1": "R1", "urn:T2": "R2"}
        counts = sh.count_by_trip(stoptimes, trip_to_route)
        assert counts["S1"] == Counter({"R1": 2, "R2": 1})


class TestRoadFields:
    def test_no_road(self):
        assert sh.road_fields("origin", None, {}) == {"originRoadName": None}

    def test_road_with_device(self):
        road = {
            "name": {"type": "Property", "value": "Petőfi híd"},
            "refDevice": {"type": "Relationship", "object": "urn:ngsi-ld:Device:d1"},
        }
        devices = {"urn:ngsi-ld:Device:d1": {"name": {"type": "Property", "value": "D1 cam"}}}
        out = sh.road_fields("origin", road, devices)
        assert out["originRoadName"] == "Petőfi híd"
        assert out["originDeviceId"] == "d1"
        assert out["originDeviceName"] == "D1 cam"


class TestCommuterOrganization:
    def test_resolves_through_road_and_device(self):
        roads = {
            "urn:road:1": {"refDevice": {"type": "Relationship", "object": "urn:ngsi-ld:Device:d1"}},
            "urn:road:2": {"refDevice": {"type": "Relationship", "object": "urn:ngsi-ld:Device:d2"}},
        }
        devices = {
            "urn:ngsi-ld:Device:d1": {"owner": {"type": "Relationship", "object": "urn:ngsi-ld:Organization:o1"}},
            "urn:ngsi-ld:Device:d2": {},
        }
        assert sh.commuter_organization("urn:road:2", "urn:road:1", roads, devices) == "urn:ngsi-ld:Organization:o1"

    def test_none_when_unresolvable(self):
        assert sh.commuter_organization("urn:road:9", "urn:road:8", {}, {}) is None
