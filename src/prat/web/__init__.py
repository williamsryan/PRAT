"""Web UI assets for PRAT reports.

This subpackage ships the self-contained HTML template used by
:func:`prat.reporting.generate_html_report`. The template is a single, offline
document (no CDNs, fonts, or external scripts) so generated reports render
anywhere, including air-gapped environments.

See ``README.md`` in this directory for the full UI documentation: feature
list, the JavaScript data contract, the ``__PRAT_*__`` placeholder reference,
theming, keyboard shortcuts, and guidance on extending the report.
"""

from importlib.resources import files as _files

#: Filename of the report template shipped alongside this package.
REPORT_TEMPLATE_NAME = "report_template.html"


def report_template_path() -> str:
    """Return the absolute filesystem path to the bundled report template."""
    return str(_files(__package__).joinpath(REPORT_TEMPLATE_NAME))


def load_report_template() -> str:
    """Return the raw report template HTML (with ``__PRAT_*__`` placeholders)."""
    return _files(__package__).joinpath(REPORT_TEMPLATE_NAME).read_text(encoding="utf-8")


__all__ = ["REPORT_TEMPLATE_NAME", "report_template_path", "load_report_template"]
