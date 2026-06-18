"""Importing this package registers every tool as a side effect.

The agent only needs ``get_schemas`` and ``dispatch`` from here.
"""
from app.tools.registry import Scope, dispatch, get_schemas, get_specs, tool

# Side-effect imports: each module decorates and registers its tools.
from app.tools import client_tools  # noqa: F401,E402
from app.tools import auth_tools  # noqa: F401,E402
from app.tools import lead_tools  # noqa: F401,E402
from app.tools import knowledge_tools  # noqa: F401,E402

__all__ = ["Scope", "dispatch", "get_schemas", "get_specs", "tool"]
