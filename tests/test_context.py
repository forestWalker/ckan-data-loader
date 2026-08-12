"""Unit tests for attribute-name normalization (core/context.py)."""

from core.context import TERMS_PREFIX, SMART_DM, URI_FIWARE, shorten, attr, attr_raw, has_attr


class TestShorten:
    def test_plain_short_name(self):
        assert shorten("pm25") == "pm25"

    def test_smartdm_iri(self):
        assert shorten(SMART_DM + "dataModel.Environment/pm25") == "pm25"

    def test_smartdm_iri_with_hash(self):
        assert shorten(SMART_DM + "dataModel.Environment#pm25") == "pm25"

    def test_terms_jsonld(self):
        assert shorten(TERMS_PREFIX + "pm25") == "pm25"

    def test_fiware_uri(self):
        assert shorten(URI_FIWARE + "dateObserved") == "dateObserved"

    def test_ngsi_ld_prefix(self):
        assert shorten("ngsi-ld:refDevice") == "refDevice"

    def test_unknown_prefix_takes_tail(self):
        assert shorten("https://example.org/x/y/anything") == "anything"


def _expanded(name):
    return {SMART_DM + "dataModel.Environment/" + name: {"type": "Property", "value": name}}


class TestAttr:
    def test_plain_name(self):
        assert attr({"pm25": {"type": "Property", "value": 1.2}}, "pm25") == 1.2

    def test_expanded_iri(self):
        entity = {
            "id": "urn:ngsi-ld:AirQualityObserved:1",
            "type": "AirQualityObserved",
            **_expanded("pm25"),
        }
        assert attr(entity, "pm25") == "pm25"

    def test_attr_raw_returns_wrapper(self):
        entity = {"pm25": {"type": "Property", "value": 1.2}}
        assert attr_raw(entity, "pm25") == {"type": "Property", "value": 1.2}

    def test_first_match_wins(self):
        entity = {"a": {"type": "Property", "value": 1}, "b": {"type": "Property", "value": 2}}
        assert attr(entity, "a", "b") == 1

    def test_missing_returns_none(self):
        assert attr({}, "pm25") is None

    def test_relationship_object(self):
        entity = {"refDevice": {"type": "Relationship", "object": "urn:ngsi-ld:Device:d1"}}
        assert attr(entity, "refDevice") == "urn:ngsi-ld:Device:d1"

    def test_metadata_keys_excluded_from_shortened_index(self):
        entity = {
            "id": "urn:ngsi-ld:AirQualityObserved:1",
            "type": "AirQualityObserved",
            "@context": ["https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context.jsonld"],
            "pm25": {"type": "Property", "value": 1},
        }
        assert attr(entity, "pm25") == 1


class TestHasAttr:
    def test_expanded_iri(self):
        assert has_attr(_expanded("pm25"), "pm25")
        assert not has_attr(_expanded("pm25"), "co2")
