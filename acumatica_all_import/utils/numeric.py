"""Small numeric conversions shared by Acumatica staging importers."""


def parse_float(value):
    """Convert an optional value to float, preserving legacy fallback behavior."""
    try:
        return float(value or 0)
    except Exception:
        return 0.0
