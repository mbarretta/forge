"""Output generators for vulnerability assessment reports."""

from forge_gauge.outputs.base import OutputGenerator
from forge_gauge.outputs.xlsx_generator import XLSXGenerator
from forge_gauge.outputs.html_generator import HTMLGenerator

__all__ = [
    "OutputGenerator",
    "XLSXGenerator",
    "HTMLGenerator",
]
