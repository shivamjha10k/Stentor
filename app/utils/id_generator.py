"""
Generates unique call_id and call_timestamp for each incoming call.

call_id format: call_{YYYY_MM_DD}_{6-char-hex}
Example: call_2026_02_09_a1b2c3
"""

import uuid
from datetime import datetime, timezone


def generate_call_id() -> str:
    """Generate a unique call ID using current date + short UUID hex."""
    date_str = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    short_uuid = uuid.uuid4().hex[:6]
    return f"call_{date_str}_{short_uuid}"


def generate_call_timestamp() -> datetime:
    """Generate current UTC timestamp."""
    return datetime.now(timezone.utc)
