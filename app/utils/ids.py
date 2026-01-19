# app/utils/ids.py
import re, uuid
from typing import Optional

_UUID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')

def safe_uuid(s: str) -> Optional[uuid.UUID]:
    if isinstance(s, str) and _UUID_RE.match(s):
        try:
            return uuid.UUID(s)
        except Exception:
            return None
    return None
