"""
Pricing quote generator for Chainguard image subscriptions.

Generates formatted price quote documents from pricing calculations.
"""

import logging
from datetime import datetime
from pathlib import Path

from forge_gauge.utils.formatting import format_currency, format_date_with_ordinal

logger = logging.getLogger(__name__)


class PricingQuoteGenerator:
    """Generator for pricing quote documents."""

    def __init__(self, customer_name: str = "Customer"):
        """
        Initialize quote generator.

        Args:
            customer_name: Name of customer for quote
        """
        self.customer_name = customer_name

    def generate_text_quote(self, quote_data: dict, output_path: Path) -> Path:
        """
        Generate text-based pricing quote.

        Args:
            quote_data: Quote data from PricingCalculator.calculate_quote()
            output_path: Path to write quote file

        Returns:
            Path to generated quote file
        """
        lines = []

        # Header
        lines.append("=" * 80)
        lines.append("CHAINGUARD CONTAINER SUBSCRIPTION PRICING QUOTE")
        lines.append("=" * 80)
        lines.append("")

        # Customer and policy info
        lines.append(f"Customer:        {self.customer_name}")
        lines.append(f"Quote Date:      {datetime.now().strftime('%B %d, %Y')}")
        lines.append(f"Policy:          {quote_data['policy_name']}")
        lines.append(f"Effective Date:  {quote_data['effective_date']}")
        lines.append(f"Currency:        {quote_data['currency']}")
        lines.append("")

        # Line items
        lines.append("-" * 100)
        lines.append(
            f"{'TIER':<20} {'QTY':>6} {'LIST PRICE':>15} {'DISCOUNT':>10} {'DISC PRICE':>15} {'TOTAL':>15}"
        )
        lines.append("-" * 100)

        for item in quote_data["line_items"]:
            tier_display = item["tier_display"]
            quantity = item["quantity"]
            list_price = format_currency(
                item["list_price_per_image"], quote_data["currency"]
            )
            discount = item.get("discount", 0.0)
            discount_pct = f"{discount * 100:.0f}%" if discount > 0 else "-"
            disc_price = format_currency(
                item["discounted_price_per_image"], quote_data["currency"]
            )
            total = format_currency(item["total"], quote_data["currency"])

            lines.append(
                f"{tier_display:<20} {quantity:>6} {list_price:>15} {discount_pct:>10} {disc_price:>15} {total:>15}"
            )

            # Show image names under the tier
            images = item.get("images", [])
            if images:
                lines.append(f"  Images:")
                for image in images:
                    lines.append(f"    - {image}")
                lines.append("")  # Blank line after images

        lines.append("-" * 100)

        # Totals
        subtotal = format_currency(quote_data["subtotal"], quote_data["currency"])
        grand_total = format_currency(quote_data["grand_total"], quote_data["currency"])

        lines.append(f"{'':>42} {'SUBTOTAL:':>15} {subtotal:>15}")
        lines.append(f"{'':>42} {'GRAND TOTAL:':>15} {grand_total:>15}")
        lines.append("")

        # Pricing unit note
        pricing_unit = quote_data.get("pricing_unit", "per image per year")
        lines.append(f"Note: All prices are {pricing_unit}")
        lines.append("")

        # Policy notes
        if quote_data.get("notes"):
            lines.append("Additional Information:")
            lines.append("-" * 80)
            notes = quote_data["notes"].strip()
            for line in notes.split("\n"):
                lines.append(line)
            lines.append("")

        # Footer
        lines.append("=" * 80)
        generated_date = format_date_with_ordinal(datetime.now())
        lines.append(f"Generated on {generated_date}")
        lines.append("=" * 80)

        # Write to file
        content = "\n".join(lines)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(content)

        logger.info(f"Generated pricing quote: {output_path}")
        return output_path

    def generate_html_quote(self, quote_data: dict, output_path: Path) -> Path:
        """
        Generate HTML-based pricing quote.

        Args:
            quote_data: Quote data from PricingCalculator.calculate_quote()
            output_path: Path to write quote file

        Returns:
            Path to generated quote file
        """
        # Get CSS content
        css_content = self._get_pricing_css()

        # Build HTML
        html_parts = []

        # HTML header
        html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chainguard Pricing Quote</title>
    <style>
{css_content}
    </style>
</head>
<body>
    <div class="container">
""")

        # Header section with logo (embedded as base64 for portability)
        from outputs.html_generator import _get_logo_data_uri

        logo_data_uri = _get_logo_data_uri()
        html_parts.append('        <div class="header-section">')
        html_parts.append(
            f'            <img class="header-logo" src="{logo_data_uri}" alt="Chainguard Logo">'
        )
        html_parts.append(
            "            <h1>Chainguard Container Subscription Pricing Quote</h1>"
        )
        html_parts.append(f"            <p>Prepared for {self.customer_name}</p>")
        html_parts.append("        </div>")

        # Quote details section
        html_parts.append('        <div class="pricing-section">')
        html_parts.append('            <div class="info-grid">')
        html_parts.append('                <div class="info-item">')
        html_parts.append(
            '                    <span class="info-label">Quote Date:</span>'
        )
        html_parts.append(
            f'                    <span class="info-value">{datetime.now().strftime("%B %d, %Y")}</span>'
        )
        html_parts.append("                </div>")
        html_parts.append('                <div class="info-item">')
        html_parts.append('                    <span class="info-label">Policy:</span>')
        html_parts.append(
            f'                    <span class="info-value">{quote_data["policy_name"]}</span>'
        )
        html_parts.append("                </div>")
        html_parts.append('                <div class="info-item">')
        html_parts.append(
            '                    <span class="info-label">Effective Date:</span>'
        )
        html_parts.append(
            f'                    <span class="info-value">{quote_data["effective_date"]}</span>'
        )
        html_parts.append("                </div>")
        html_parts.append('                <div class="info-item">')
        html_parts.append(
            '                    <span class="info-label">Currency:</span>'
        )
        html_parts.append(
            f'                    <span class="info-value">{quote_data["currency"]}</span>'
        )
        html_parts.append("                </div>")
        html_parts.append("            </div>")

        # Line items table
        html_parts.append("            <h2>Line Items</h2>")
        html_parts.append('            <div class="table-container">')
        html_parts.append("                <table>")
        html_parts.append("                    <thead>")
        html_parts.append("                        <tr>")
        html_parts.append("                            <th>Image Tier</th>")
        html_parts.append(
            '                            <th class="number">Quantity</th>'
        )
        html_parts.append(
            '                            <th class="number">List Price</th>'
        )
        html_parts.append(
            '                            <th class="number">Discount</th>'
        )
        html_parts.append(
            '                            <th class="number">Discounted Price</th>'
        )
        html_parts.append('                            <th class="number">Total</th>')
        html_parts.append("                        </tr>")
        html_parts.append("                    </thead>")
        html_parts.append("                    <tbody>")

        for item in quote_data["line_items"]:
            tier = item["tier"]
            tier_display = item["tier_display"]
            tier_class = f"tier-{tier}"
            discount = item.get("discount", 0.0)
            discount_display = f"{discount * 100:.0f}%" if discount > 0 else "-"
            images = item.get("images", [])

            html_parts.append("                        <tr>")
            html_parts.append(
                f'                            <td class="{tier_class}"><strong>{tier_display}</strong>'
            )
            # Show image names under tier name
            if images:
                html_parts.append(
                    '                                <ul style="margin: 8px 0 0 0; padding-left: 20px; font-size: 0.9em; font-weight: normal; color: var(--cg-gray-dark);">'
                )
                for image in images:
                    html_parts.append(
                        f"                                    <li>{image}</li>"
                    )
                html_parts.append("                                </ul>")
            html_parts.append("                            </td>")
            html_parts.append(
                f'                            <td class="number">{item["quantity"]}</td>'
            )
            html_parts.append(
                f'                            <td class="number">{format_currency(item["list_price_per_image"], quote_data["currency"])}</td>'
            )
            html_parts.append(
                f'                            <td class="number">{discount_display}</td>'
            )
            html_parts.append(
                f'                            <td class="number">{format_currency(item["discounted_price_per_image"], quote_data["currency"])}</td>'
            )
            html_parts.append(
                f'                            <td class="number">{format_currency(item["total"], quote_data["currency"])}</td>'
            )
            html_parts.append("                        </tr>")

        # Add grand total row to table
        html_parts.append('                        <tr class="grand-total-row">')
        html_parts.append(
            '                            <td colspan="5" class="total-label"><strong>Grand Total</strong></td>'
        )
        html_parts.append(
            f'                            <td class="number total-amount"><strong>{format_currency(quote_data["grand_total"], quote_data["currency"])}</strong></td>'
        )
        html_parts.append("                        </tr>")
        html_parts.append("                    </tbody>")
        html_parts.append("                </table>")
        html_parts.append("            </div>")

        # Pricing unit note
        pricing_unit = quote_data.get("pricing_unit", "per image per year")
        html_parts.append('            <div class="pricing-notes">')
        html_parts.append(
            f"                <p><strong>All prices are {pricing_unit}.</strong></p>"
        )

        # Policy notes
        if quote_data.get("notes"):
            notes_html = quote_data["notes"].strip().replace("\n", "<br>")
            html_parts.append(f"                {notes_html}")

        html_parts.append("            </div>")
        html_parts.append("        </div>")  # Close pricing-section

        # Footer
        generated_date = format_date_with_ordinal(datetime.now())
        html_parts.append('        <div class="footer">')
        html_parts.append(
            f"            <p>This quote is {self.customer_name} & Chainguard Confidential | Generated on {generated_date}</p>"
        )
        html_parts.append("        </div>")

        # HTML footer
        html_parts.append("    </div>")  # Close container
        html_parts.append("</body>")
        html_parts.append("</html>")

        # Write to file
        content = "\n".join(html_parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(content)

        logger.info(f"Generated pricing quote: {output_path}")
        return output_path

    def _get_pricing_css(self) -> str:
        """Get CSS content for pricing quotes."""
        from outputs.html_generator import load_embedded_css

        return load_embedded_css()
