"""Side-effect-only import of every domain models module.

Importing this module populates Base.metadata with every table, which is
all Alembic's env.py needs for autogenerate/`alembic check`. Nothing here
is re-exported deliberately — callers that need a specific model import it
from its own domain package.
"""

from __future__ import annotations

from app.accounts import models as _accounts_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.monitors import models as _monitors_models  # noqa: F401
from app.heartbeats import models as _heartbeats_models  # noqa: F401
from app.incidents import models as _incidents_models  # noqa: F401
from app.notifications import models as _notifications_models  # noqa: F401
from app.status_pages import models as _status_pages_models  # noqa: F401
from app.core import models as _core_models  # noqa: F401
