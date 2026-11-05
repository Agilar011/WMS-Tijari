"""Pure helpers for normalizing Acumatica API payload values."""

from dateutil import parser as dateutil_parser


DEFAULT_TRUE_VALUES = frozenset(("true", "1", "yes", "y"))
DOCUMENT_ONLY_TRUE_VALUES = DEFAULT_TRUE_VALUES | {"document only"}


def acumatica_value(item, key, default=""):
    """Return an Acumatica scalar, unwrapping the common ``{"value": ...}`` shape.

    The historical import helpers use an empty string for missing/falsy values.
    Keep that behavior here so moving call sites does not change mapping results.
    """
    if not isinstance(item, dict):
        return default
    value = item.get(key, default)
    if isinstance(value, dict):
        value = value.get("value", default)
    return value or default


def acumatica_bool(value, key=None, true_values=DOCUMENT_ONLY_TRUE_VALUES, non_string_truthy=False):
    """Normalize Acumatica booleans, including wrapped values."""
    if key is not None:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return value
    if value in (False, None, ""):
        return False
    if isinstance(value, str):
        return value.strip().lower() in true_values
    return bool(value) if non_string_truthy else False


def acumatica_rows(payload, extra_keys=(), single_record=False):
    """Normalize common Acumatica collection response shapes to a list."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("value", "rows", *extra_keys):
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    return [payload] if single_record else []


def acumatica_datetime(value):
    """Parse an Acumatica datetime using the established dateutil behavior.

    Import code stores Odoo-naive datetimes, so timezone information is removed
    as it was in the existing ``_parse_dt`` helpers.
    """
    if not value:
        return False
    try:
        return dateutil_parser.parse(value).replace(tzinfo=None)
    except Exception:
        return False


def changed_import_fields(record, vals):
    """Return a chatter-friendly list of changed fields for a master staging row."""
    changed_fields = []
    for field_name, new_value in vals.items():
        field = record._fields.get(field_name)
        if not field:
            continue
        old_value = record[field_name]
        if field.type == "many2one":
            old_value = old_value.id if old_value else False
        old_value = old_value or False
        new_value = new_value or False
        if old_value != new_value:
            changed_fields.append({
                "field_name": field_name,
                "field_label": field.string,
                "old_value": old_value,
                "new_value": new_value,
            })
    return changed_fields
