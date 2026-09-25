"""Web UI assets for PRAT reports.

This subpackage ships the self-contained HTML template used by
:func:`prat.reporting.generate_html_report`, and the vendored D3 build that
:func:`prat.feature_graph.generate_feature_graph_html` inlines. Both outputs are
single, offline documents (no CDNs, fonts, or external scripts) so generated
reports render anywhere, including air-gapped environments.

See ``README.md`` in this directory for the full UI documentation: feature
list, the JavaScript data contract, the ``__PRAT_*__`` placeholder reference,
theming, keyboard shortcuts, and guidance on extending the report.
"""


from __future__ import annotations

from importlib.resources import files as _files

#: Filename of the report template shipped alongside this package.
REPORT_TEMPLATE_NAME = "report_template.html"

#: Vendored D3 build inlined into the feature-graph HTML (ISC, see D3-LICENSE).
D3_BUNDLE_NAME = "d3.v7.min.js"
D3_VERSION = "7.9.0"
D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"


def report_template_path() -> str:
    """Return the absolute filesystem path to the bundled report template."""
    return str(_files(__package__).joinpath(REPORT_TEMPLATE_NAME))


def load_report_template() -> str:
    """Return the raw report template HTML (with ``__PRAT_*__`` placeholders)."""
    return _files(__package__).joinpath(REPORT_TEMPLATE_NAME).read_text(encoding="utf-8")


def load_d3_bundle() -> str:
    """Return the vendored D3 source, verifying it against the recorded digest.

    The digest pins the exact upstream artifact (``d3@7.9.0/dist/d3.min.js``) so
    a modified or truncated copy is refused rather than silently rendered.
    """
    import hashlib

    source = _files(__package__).joinpath(D3_BUNDLE_NAME).read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest != D3_SHA256:
        raise RuntimeError(
            f"Vendored {D3_BUNDLE_NAME} does not match the recorded digest "
            f"(expected {D3_SHA256}, got {digest})"
        )
    return source.decode("utf-8")


__all__ = [
    "REPORT_TEMPLATE_NAME",
    "D3_BUNDLE_NAME",
    "D3_VERSION",
    "D3_SHA256",
    "report_template_path",
    "load_report_template",
    "load_d3_bundle",
]
