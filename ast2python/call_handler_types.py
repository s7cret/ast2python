from __future__ import annotations

from collections.abc import Callable
from typing import Any

ExactCallHandler = Callable[[Any, Any, str], Any]
PrefixCallHandler = Callable[[Any, str, Any, str], Any]
