# app/services/agent/payload_store.py
import uuid
import time
import threading
from typing import Any, Dict, Optional

_lock = threading.Lock()
_store: Dict[str, tuple] = {}  # key -> (payload, expire_ts)

DEFAULT_TTL = 300  # seconds

def save_payload(payload: Any, ttl: int = DEFAULT_TTL) -> str:
    key = str(uuid.uuid4())
    expire = time.time() + ttl
    with _lock:
        _store[key] = (payload, expire)
    return key

def load_payload(key: str) -> Optional[Any]:
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None
        payload, expire = entry
        if expire < time.time():
            # expired -> remove
            _store.pop(key, None)
            return None
        return payload

def delete_payload(key: str) -> None:
    with _lock:
        _store.pop(key, None)
