"""CKAN resource lifecycle for the export pipeline.

This is a behavioural port of block 4 of the legacy ``export_*_csv.py``
scripts: daily segmented resources, half-built-datastore self-heal, the Table
+ per-chart views, ``recordKey`` deduplication, chunked ``datastore_upsert``
and the 30-day cleanup. The login/session machinery mirrors
``apps/push_ovak_data/core/ckan.py`` (httpx drops CKAN's ``Set-Cookie`` when it
carries an empty ``Domain=``, so cookies are captured and replayed manually).
"""

from __future__ import annotations

import http.cookies
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from .config import ExportSpec, Settings
from .ngsilib import convert_record, infer_field_types, record_key

log = logging.getLogger(__name__)

BUDAPEST = ZoneInfo("Europe/Budapest")


def _extract_cookies(set_cookie: Optional[str]) -> dict[str, str]:
    if not set_cookie:
        return {}
    jar = http.cookies.SimpleCookie()
    jar.load(set_cookie)
    return {key: value.value for key, value in jar.items()}


class CKANExportsClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(
            verify=False,
            timeout=settings.timeout,
            headers={"User-Agent": "STiDS-CKAN-Exports/1.0"},
        )
        self._cookies: dict[str, str] = {}
        self._api_key: Optional[str] = settings.ckan_api_key or None

    @property
    def base_url(self) -> str:
        return self._settings.ckan_url

    def close(self) -> None:
        self._client.close()

    # ---- auth ---------------------------------------------------------------

    def login(self) -> None:
        if self._api_key:
            return
        if not self._settings.ckan_admin_password:
            raise RuntimeError(
                "Nincs CKAN hitelesítés: adj meg CKAN_API_TOKEN-t vagy CKAN_ADMIN_PASSWORD-ot."
            )
        resp = self._client.get(f"{self.base_url}/user/login")
        if resp.status_code != 200:
            raise RuntimeError(
                f"CKAN nem elérhető (HTTP {resp.status_code} a /user/login-on)."
            )
        m = re.search(
            r'name=["\']_csrf_token["\'][^>]*?value=["\']([^"\']+)["\']',
            resp.text,
        ) or re.search(
            r'value=["\']([^"\']+)["\'][^>]*?name=["\']_csrf_token["\']',
            resp.text,
        )
        if not m:
            raise RuntimeError("CSRF token nem található a CKAN login oldalon.")
        login_resp = self._client.post(
            f"{self.base_url}/user/login",
            data={
                "login": self._settings.ckan_admin_user,
                "password": self._settings.ckan_admin_password,
                "_csrf_token": m.group(1),
                "remember_me": "false",
            },
            headers={"Referer": f"{self.base_url}/user/login"},
        )
        if login_resp.status_code not in (301, 302, 303):
            raise RuntimeError(
                f"CKAN login elutasítva (HTTP {login_resp.status_code}); ellenőrizd a jelszót."
            )
        self._cookies = _extract_cookies(login_resp.headers.get("set-cookie"))
        if not self._cookies:
            raise RuntimeError("CKAN login nem adott session cookie-t.")
        key = self._get_api_key()
        if key:
            self._api_key = key
        log.info("CKAN login OK (cookie-alapú)")

    def _get_api_key(self) -> Optional[str]:
        result = self._api("user_show", {"id": "admin"})
        if isinstance(result, dict) and result.get("success"):
            value = result.get("result", {}).get("apikey")
            if value:
                return str(value)
        result = self._api("user_generate_apikey", {"id": "admin"})
        if isinstance(result, dict) and result.get("success"):
            value = result.get("result", {})
            if isinstance(value, dict):
                return value.get("apikey")
        return None

    def _re_login_after_session_issue(self) -> None:
        try:
            self._cookies = {}
            self.login()
        except Exception as e:
            log.warning("CKAN re-login sikertelen: %s", e)

    def _looks_like_login_page(self, body: str) -> bool:
        low = body.lower()
        return "_csrf_token" in low or "log in" in low or 'name="login"' in low

    # ---- CKAN API -----------------------------------------------------------

    def _api(self, action: str, data_dict: dict[str, Any]) -> dict:
        last_error: Optional[str] = None
        for attempt in range(3):
            try:
                headers: dict[str, str] = {}
                if self._api_key:
                    headers["Authorization"] = self._api_key
                resp = self._client.post(
                    f"{self.base_url}/api/3/action/{action}",
                    json=data_dict,
                    cookies=self._cookies,
                    headers=headers,
                )
                body = resp.text or ""
                if not body.strip():
                    last_error = f"üres válasz (HTTP {resp.status_code})"
                    if attempt == 0:
                        self._re_login_after_session_issue()
                        continue
                else:
                    try:
                        result = resp.json()
                    except ValueError:
                        last_error = f"nem JSON válasz (HTTP {resp.status_code}): {body[:200]!r}"
                        if attempt == 0 and self._looks_like_login_page(body):
                            self._re_login_after_session_issue()
                            continue
                    else:
                        if not result.get("success"):
                            last_error = str(result.get("error", result))[:500]
                            return result
                        return result
            except Exception as e:
                last_error = str(e)
            time.sleep(2)
        return {"success": False, "error": {"message": f"CKAN {action} failed: {last_error}"}}

    def _require_success(self, action: str, data_dict: dict[str, Any]) -> dict:
        result = self._api(action, data_dict)
        if not result.get("success"):
            raise RuntimeError(f"CKAN API-hiba: {result.get('error', result)}")
        return result

    def package_show(self, dataset_id: str) -> dict:
        return self._require_success("package_show", {"id": dataset_id}).get("result", {})

    def _package_show_optional(self, dataset_id: str) -> Optional[dict]:
        """Show a package, or return None when it does not exist yet."""
        result = self._api("package_show", {"id": dataset_id})
        if result.get("success"):
            return result.get("result", {})
        if self._is_not_found(result):
            return None
        raise RuntimeError(f"CKAN API-hiba: {result.get('error', result)}")

    @staticmethod
    def _is_not_found(result: dict) -> bool:
        error = result.get("error", {})
        if isinstance(error, dict):
            return error.get("__type") == "Not Found Error"
        return "not found" in str(error).lower()

    def ensure_package(self, dataset_id: str, title: str = "") -> dict:
        """Return the dataset, creating it first when it is missing."""
        existing = self._package_show_optional(dataset_id)
        if existing is not None:
            return existing
        data: dict[str, Any] = {
            "name": dataset_id,
            "title": title or dataset_id,
            "notes": "Standardizált CKAN export pipeline által létrehozott adathalmaz.",
        }
        owner_org = self._default_owner_org()
        if owner_org:
            data["owner_org"] = owner_org
        created = self._require_success("package_create", data)
        log.info("Új CKAN dataset létrehozva: %s", dataset_id)
        return created.get("result", {})

    def _default_owner_org(self) -> Optional[str]:
        """First organization the admin may create datasets in (site convention)."""
        result = self._api("organization_list_for_user", {"permission": "create_dataset"})
        if result.get("success"):
            orgs = result.get("result", [])
            if isinstance(orgs, list) and orgs:
                return orgs[0].get("id")
        return None

    # ---- resource lifecycle -------------------------------------------------

    def delete_expired_resources(self, dataset_id: str, max_age_days: int, created_key: str = "created") -> int:
        """Delete resources older than ``max_age_days`` (datastore first)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        package = self._package_show_optional(dataset_id)
        if package is None:
            return 0
        deleted = 0
        for resource in package.get("resources", []):
            created = self._created_value(resource, created_key)
            if created is None or created >= cutoff:
                continue
            if resource.get("datastore_active"):
                try:
                    self._require_success("datastore_delete", {"resource_id": resource["id"], "force": True})
                except RuntimeError as exc:
                    log.warning("DataStore törlés figyelmeztetés: %s", exc)
            self._require_success("resource_delete", {"id": resource["id"]})
            deleted += 1
            log.info("30 napnál régebbi CKAN resource törölve: %s", resource.get("name", resource["id"]))
        return deleted

    @staticmethod
    def _created_value(resource: dict, created_key: str):
        value = None
        for key in created_key.split(" or "):
            value = resource.get(key.strip())
            if value:
                break
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def infer_datastore_fields(self, rows: list[dict], fields: list[str]) -> list[dict]:
        field_types = infer_field_types(rows, fields)
        return [{"id": "recordKey", "type": "text"}] + [
            {"id": name, "type": field_types.get(name, "text")} for name in fields
        ]

    @staticmethod
    def table_view_fields(fields: list[str]) -> list[str]:
        return ["_id"] + [field for field in fields if not field.lower().endswith("id")]

    def create_resource_views(self, resource_id: str, fields: list[str], charts: list[Any], resource_title: str) -> None:
        existing_views = self._api("resource_view_list", {"id": resource_id}).get("result", [])
        existing_titles = {view.get("title") for view in existing_views}
        if "Table" not in existing_titles:
            self._require_success("resource_view_create", {
                "resource_id": resource_id,
                "title": "Table",
                "description": "Az exportalt adatok keresheto tablazatos nezete.",
                "view_type": "datatables_view",
                "show_fields": self.table_view_fields(fields),
            })
        for chart in charts:
            title = getattr(chart, "title", "Chart")
            if title in existing_titles:
                continue
            self._require_success("resource_view_create", {
                "resource_id": resource_id,
                "title": title,
                "description": f"{resource_title} automatikusan létrehozott diagramja.",
                "view_type": "charts_view",
                "engine": "plotly",
                "type": getattr(chart, "type", "Line"),
                "x": getattr(chart, "x", ""),
                "y": getattr(chart, "y", ""),
                "chart_title": title,
                "x_axis_label": getattr(chart, "x_label", ""),
                "y_axis_label": getattr(chart, "y_label", ""),
                "skip_null_values": True,
                "limit": 1000000,
            })

    def daily_resource(self, dataset_id: str, resource_name: str, description: str, rows: list[dict], fields: list[str]):
        package = self.package_show(dataset_id)
        existing = next(
            (item for item in package.get("resources", []) if item.get("name") == resource_name),
            None,
        )
        if existing:
            check = self._api("datastore_search", {"resource_id": existing["id"], "limit": 0})
            if check.get("success"):
                return existing, False
            schema_fields = self.infer_datastore_fields(rows, fields)
            self._require_success("datastore_create", {
                "resource_id": existing["id"], "fields": schema_fields,
                "primary_key": ["recordKey"], "force": True,
            })
            self.create_resource_views(existing["id"], fields, [], existing.get("name", resource_name))
            log.info("Félbemaradt napi DataStore helyreállítva: %s", resource_name)
            return existing, True
        resource = self._require_success("resource_create", {
            "package_id": dataset_id, "name": resource_name, "description": description,
            "format": "CSV", "url": "", "url_type": "datastore",
        }).get("result")
        schema_fields = self.infer_datastore_fields(rows, fields)
        self._require_success("datastore_create", {
            "resource_id": resource["id"], "fields": schema_fields,
            "primary_key": ["recordKey"], "force": True,
        })
        log.info("Új napi CKAN resource létrehozva: %s", resource_name)
        return resource, True

    def existing_record_keys(self, resource_id: str) -> set[str]:
        result = self._api("datastore_search", {
            "resource_id": resource_id, "fields": ["recordKey"], "limit": 1000000,
        })
        return {str(item.get("recordKey")) for item in result.get("result", {}).get("records", [])}

    # ---- publish -------------------------------------------------------------

    def publish(self, spec: ExportSpec, rows: list[dict]) -> dict:
        """Publish assembled rows to the daily resource. Returns a stats dict."""
        local_now = datetime.now(BUDAPEST)
        resource_name = f"{spec.resource_title} - {local_now:%Y.%m.%d}"
        description = f"Napi, inkrementálisan frissített adatok: {local_now:%Y.%m.%d}."

        self.ensure_package(spec.dataset, spec.title)

        deleted = self.delete_expired_resources(
            spec.dataset, self._settings.cleanup_days, spec.created_key
        )

        resource, created = self.daily_resource(
            spec.dataset, resource_name, description, rows, spec.fields
        )
        schema = self._api("datastore_search", {"resource_id": resource["id"], "limit": 0})
        field_types = {
            field["id"]: field.get("type", "text")
            for field in schema.get("result", {}).get("fields", [])
        }
        known = set() if created else self.existing_record_keys(resource["id"])
        records = [convert_record(row, field_types, spec.fields) for row in rows]
        new_records = [record for record in records if record["recordKey"] not in known]

        chunk_size = self._settings.ckan_chunk
        for start in range(0, len(new_records), chunk_size):
            self._require_success("datastore_upsert", {
                "resource_id": resource["id"],
                "records": new_records[start:start + chunk_size],
                "method": "upsert",
                "force": True,
            })

        log.info(
            "Napi resource frissítve: %s; új rekordok: %d; már meglévő: %d",
            resource_name, len(new_records), len(records) - len(new_records),
        )
        log.info(
            "CKAN resource: %s/dataset/%s/resource/%s",
            self.base_url, spec.dataset, resource["id"],
        )
        return {
            "published": len(new_records),
            "dedup": len(records) - len(new_records),
            "cleanup": deleted,
            "resource_id": resource["id"],
            "resource_name": resource_name,
        }
