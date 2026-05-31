
from __future__ import annotations

import os
import platform

# SQLAlchemy's Windows C-extension probe can block in WMI lookups on some
# machines. Disabling the runtime probe keeps startup and tests responsive.
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")

if os.name == "nt":
    def _fast_system() -> str:
        return "Windows"

    def _fast_machine() -> str:
        return (
            os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or "AMD64"
        )

    platform.system = _fast_system
    platform.machine = _fast_machine
