"""Unit tests for pipelines.yaml overlay logic (core/config.py)."""

from core.config import ExportSpec, Settings, apply_pipelines


def _spec(**overrides):
    base = dict(slug="test-export", title="T", dataset="d", resource_title="r")
    base.update(overrides)
    return ExportSpec(**base)


def _settings(page_size=100):
    return Settings(
        ovak_source="https://x",
        ovak_key="k",
        ckan_url="https://ckan",
        ckan_admin_password="p",
        page_size=page_size,
    )


class TestApplyPipelines:
    def test_no_pipelines_noop(self):
        spec = _spec()
        out = apply_pipelines(spec, {}, _settings())
        assert out is not spec
        assert out.source == "scorpio"
        assert out.window == "all"

    def test_defaults_applied(self):
        pipelines = {"defaults": {"source": "ovak", "window": "today"}}
        out = apply_pipelines(_spec(), pipelines, _settings())
        assert out.source == "ovak"
        assert out.window == "today"

    def test_export_entry_overrides_defaults(self):
        pipelines = {
            "defaults": {"source": "ovak", "window": "today"},
            "exports": {"test-export": {"source": "scorpio", "window": "all", "page_size": "42"}},
        }
        out = apply_pipelines(_spec(), pipelines, _settings())
        assert out.source == "scorpio"
        assert out.window == "all"
        assert out.page_size == 42

    def test_created_key_override(self):
        pipelines = {"exports": {"test-export": {"created_key": "retention_test_created or created"}}}
        out = apply_pipelines(_spec(), pipelines, _settings())
        assert out.created_key == "retention_test_created or created"

    def test_page_size_string_converted(self):
        pipelines = {"exports": {"test-export": {"page_size": "250"}}}
        out = apply_pipelines(_spec(), pipelines, _settings())
        assert out.page_size == 250

    def test_other_slug_untouched(self):
        pipelines = {"exports": {"other": {"window": "today"}}}
        out = apply_pipelines(_spec(), pipelines, _settings())
        assert out.window == "all"
