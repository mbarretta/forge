"""
XLSX format definitions and factory.

Provides centralized format management for Excel workbooks,
eliminating duplication through a format factory pattern.
"""

import xlsxwriter


class OutputFormatter:
    """Factory for creating consistent XLSX cell formats."""

    # Base format properties shared by all formats
    BASE_FORMAT = {
        "border": 1,
        "font_name": "Arial",
        "font_size": 10,
        "align": "left",
        "valign": "vcenter",
    }

    # Color schemes
    COLORS = {
        "blue": "#4285f4",
        "lightgrey": "#D9D9D9",
        "darkgrey": "#666666",
        "lightyellow": "#FFF2CC",
        "yellow": "#FCFF04",
        "green": "#D9EAD3",
        "lightblue": "#C8DAF8",
        "white": "#FFFFFF",
        "grey": "#F3F3F3",
        "red": "#FFE5E5",  # Light red background for KEV highlighting
    }

    # Number formats
    NUM_FORMATS = {
        "hours": "#,###",
        "money": "$#,###",
        "percent": "0.00%",
    }

    def __init__(self, workbook: xlsxwriter.Workbook):
        """
        Initialize formatter with workbook.

        Args:
            workbook: XlsxWriter workbook instance
        """
        self.workbook = workbook
        self.formats = self._create_all_formats()

    def _create_format(
        self,
        bg_color: str = None,
        font_color: str = "black",
        bold: bool = False,
        num_format: str = None,
    ) -> xlsxwriter.format.Format:
        """
        Create a format with base properties plus overrides.

        Args:
            bg_color: Background color (hex or color name)
            font_color: Font color (default: black)
            bold: Whether text should be bold
            num_format: Number format string (e.g., "$#,###")

        Returns:
            Configured format object
        """
        format_dict = self.BASE_FORMAT.copy()

        if bg_color:
            format_dict["bg_color"] = bg_color
        if font_color != "black":
            format_dict["font_color"] = font_color
        if bold:
            format_dict["bold"] = True
        if num_format:
            format_dict["num_format"] = num_format

        return self.workbook.add_format(format_dict)

    def _create_all_formats(self) -> dict:
        """
        Create all required formats using the factory method.

        Returns:
            Dictionary of format names to format objects
        """
        return {
            # Header formats
            "header_blue": self._create_format(
                bg_color=self.COLORS["blue"],
                font_color="white",
                bold=True,
            ),
            "header_lightgrey": self._create_format(
                bg_color=self.COLORS["lightgrey"],
                bold=True,
            ),
            "header_darkgrey": self._create_format(
                bg_color=self.COLORS["darkgrey"],
                font_color="white",
                bold=True,
            ),
            "header_white": self._create_format(
                bold=True,
            ),
            "header_lightyellow": self._create_format(
                bg_color=self.COLORS["lightyellow"],
                bold=True,
            ),
            # Yellow body formats
            "body_yellow": self._create_format(
                bg_color=self.COLORS["yellow"],
            ),
            "body_yellow_hours": self._create_format(
                bg_color=self.COLORS["yellow"],
                num_format=self.NUM_FORMATS["hours"],
            ),
            "body_yellow_money": self._create_format(
                bg_color=self.COLORS["yellow"],
                num_format=self.NUM_FORMATS["money"],
            ),
            # White body formats
            "body_white": self._create_format(),
            "body_white_percent": self._create_format(
                num_format=self.NUM_FORMATS["percent"],
            ),
            "body_white_hours": self._create_format(
                num_format=self.NUM_FORMATS["hours"],
            ),
            "body_white_money": self._create_format(
                num_format=self.NUM_FORMATS["money"],
            ),
            # Green body formats
            "body_green": self._create_format(
                bg_color=self.COLORS["green"],
            ),
            "body_green_hours": self._create_format(
                bg_color=self.COLORS["green"],
                num_format=self.NUM_FORMATS["hours"],
            ),
            "body_green_money": self._create_format(
                bg_color=self.COLORS["green"],
                num_format=self.NUM_FORMATS["money"],
            ),
            # Light blue body formats
            "body_lightblue": self._create_format(
                bg_color=self.COLORS["lightblue"],
            ),
            "body_lightblue_hours": self._create_format(
                bg_color=self.COLORS["lightblue"],
                num_format=self.NUM_FORMATS["hours"],
            ),
            "body_lightblue_money": self._create_format(
                bg_color=self.COLORS["lightblue"],
                num_format=self.NUM_FORMATS["money"],
            ),
            # Light grey body format
            "body_lightgrey": self._create_format(
                bg_color=self.COLORS["grey"],
            ),
            # Red body format (for KEV highlighting)
            "body_red": self._create_format(
                bg_color=self.COLORS["red"],
            ),
        }

    def get(self, format_name: str) -> xlsxwriter.format.Format:
        """
        Get a format by name.

        Args:
            format_name: Name of the format

        Returns:
            Format object

        Raises:
            KeyError: If format name doesn't exist
        """
        return self.formats[format_name]
