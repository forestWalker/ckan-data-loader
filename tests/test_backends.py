"""Backend tests using httpx.MockTransport (no network)."""

from datetime import datetime, timezone

import httpx
import pytest

from core.config import Settings
from core.ovak import OVAKBackend
from core.scorpio import ScorpioBackend


def _settings(**overrides):
    base = dict(
        ovak_source="https://ovak.test",
        ovak_key="k",
        ckan_url="https://ckan",
        ckan_admin_password="p",
        scorpio_url="https://scorpio.test",
        page_size=500,
    )
    base.update(overrides)
    return Settings(**base)


def _dt(h, m):
    return datetime(2026, 5, 11, h, m, tzinfo=timezone.utc)


def _entity(h, m, **attrs):
    entity = {
        "id": f"urn:ngsi-ld:E:{h}:{m}",
        "type": "E",
        "dateObserved": {"type": "Property", "value": f"2026-05-11T{h:02d}:{m:02d}:00Z"},
    }
    entity.update(attrs)
    return entity


def _install_transport(backend, handler):
    backend._client.close()
    backend._client = httpx.Client(transport=httpx.MockTransport(handler), verify=False)


def _scorpio_entities_handler(all_entities):
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", 500))
        body = all_entities[offset : offset + limit]
        headers = {"Content-Type": "application/json"}
        if offset + limit < len(all_entities):
            headers["Link"] = f'<{request.url}?offset={offset + limit}>; rel="next"'
        headers["ngsild-results-count"] = str(len(all_entities))
        return httpx.Response(200, json=body, headers=headers)

    return handler


def _ovak_entities_handler(all_entities):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("PageNumber", 1))
        size = int(request.url.params.get("PageSize", 500))
        start = (page - 1) * size
        body = all_entities[start : start + size]
        return httpx.Response(200, json=body, headers={"Content-Type": "application/json"})

    return handler


class TestScorpioWindow:
    def test_overlap_kept(self):
        assert ScorpioBackend._in_window(_entity(12, 0), _dt(11, 30), _dt(12, 30))

    def test_before_window_dropped(self):
        assert not ScorpioBackend._in_window(_entity(10, 0), _dt(11, 30), _dt(12, 30))

    def test_after_window_dropped(self):
        assert not ScorpioBackend._in_window(_entity(14, 0), _dt(11, 30), _dt(12, 30))

    def test_interval_endpoint_overlaps(self):
        entity = {
            "dateObserved": {"type": "Property", "value": "2026-05-11T11:50:00Z/2026-05-11T13:10:00Z"}
        }
        assert ScorpioBackend._in_window(entity, _dt(12, 0), _dt(12, 30))

    def test_missing_date_dropped_when_window_requested(self):
        assert not ScorpioBackend._in_window({"id": "urn:x"}, _dt(12, 0), _dt(12, 30))

    def test_invalid_date_dropped(self):
        entity = {"dateObserved": {"type": "Property", "value": "not-a-date"}}
        assert not ScorpioBackend._in_window(entity, _dt(12, 0), _dt(12, 30))


class TestScorpioPagination:
    def _backend(self, page_size):
        bk = ScorpioBackend(_settings(page_size=page_size))
        self._bk = bk
        return bk

    def test_pages_until_short_page(self):
        bk = self._backend(page_size=3)
        entities = [_entity(1, 1), _entity(2, 2), _entity(3, 3), _entity(4, 4), _entity(5, 5)]
        _install_transport(bk, _scorpio_entities_handler(entities))
        try:
            out = bk.get_entities("E")
        finally:
            bk.close()
        assert len(out) == 5

    def test_count_header_respected(self):
        bk = self._backend(page_size=3)
        entities = [_entity(1, 1), _entity(2, 2), _entity(3, 3), _entity(4, 4)]
        _install_transport(bk, _scorpio_entities_handler(entities))
        try:
            out = bk.get_entities("E")
        finally:
            bk.close()
        assert len(out) == 4

    def test_window_filter_applied_client_side(self):
        bk = self._backend(page_size=500)
        entities = [_entity(10, 0), _entity(12, 0), _entity(14, 0)]
        _install_transport(bk, _scorpio_entities_handler(entities))
        try:
            out = bk.get_entities("E", time_from=_dt(11, 0), time_to=_dt(13, 0))
        finally:
            bk.close()
        assert [e["id"] for e in out] == [entities[1]["id"]]

    def test_require_attr(self):
        bk = self._backend(page_size=500)
        entities = [
            _entity(1, 1),
            _entity(1, 2, pm25={"type": "Property", "value": 1.0}),
        ]
        _install_transport(bk, _scorpio_entities_handler(entities))
        try:
            out = bk.get_entities("E", require_attr="pm25")
        finally:
            bk.close()
        assert len(out) == 1

    def test_limit_caps_kept(self):
        bk = self._backend(page_size=500)
        entities = [_entity(1, 1), _entity(2, 2), _entity(3, 3)]
        _install_transport(bk, _scorpio_entities_handler(entities))
        try:
            out = bk.get_entities("E", limit=2)
        finally:
            bk.close()
        assert len(out) == 2


class TestScorpioTypeResolution:
    def test_short_type_resolved(self):
        stored = "https://smartdatamodels.org/dataModel.UrbanMobility/GtfsRoute"

        def handler(request: httpx.Request) -> httpx.Response:
            if "types" in request.url.path:
                return httpx.Response(200, json={"typeList": [stored]})
            raise AssertionError("unexpected path " + request.url.path)

        bk = ScorpioBackend(_settings())
        _install_transport(bk, handler)
        try:
            assert bk.resolve_stored_type("GtfsRoute") == stored
        finally:
            bk.close()

    def test_iri_passthrough(self):
        bk = ScorpioBackend(_settings())
        try:
            assert bk.resolve_stored_type("https://x/y/GtfsRoute") == "https://x/y/GtfsRoute"
        finally:
            bk.close()


class TestOvakPagination:
    def _client(self):
        return OVAKBackend(_settings(page_size=2))

    def test_stops_on_short_page(self):
        c = self._client()
        all_entities = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        _install_transport(c, _ovak_entities_handler(all_entities))
        try:
            out = c._paginate("/x", {})
        finally:
            c.close()
        assert [r["id"] for r in out] == ["1", "2", "3"]

    def test_deduplicates_ignored_paging(self):
        c = self._client()
        page = [{"id": "1"}, {"id": "2"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=page, headers={"Content-Type": "application/json"})

        _install_transport(c, handler)
        try:
            out = c._paginate("/x", {})
        finally:
            c.close()
        assert [r["id"] for r in out] == ["1", "2"]

    def test_cap_shrinks_page_size(self):
        c = self._client()
        all_entities = [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}]
        _install_transport(c, _ovak_entities_handler(all_entities))
        try:
            out = c._paginate("/x", {}, cap=1)
        finally:
            c.close()
        assert [r["id"] for r in out] == ["1"]

    def test_cap_overshoots_by_at_most_a_page(self):
        c = self._client()
        all_entities = [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}]
        _install_transport(c, _ovak_entities_handler(all_entities))
        try:
            out = c._paginate("/x", {}, cap=3)
        finally:
            c.close()
        assert [r["id"] for r in out] == ["1", "2", "3", "4"]

    def test_single_dict_wrapped(self):
        c = self._client()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "1"}, headers={"Content-Type": "application/json"})

        _install_transport(c, handler)
        try:
            assert c._get_json("https://ovak.test/single") == [{"id": "1"}]
        finally:
            c.close()
