"""Docker HEALTHCHECK: no curl installed, so plain urllib it is.

Hits /healthz, which the catch-all route answers 200 unless something has
explicitly set that path to "down" via /_control.
"""

import sys
import urllib.request

try:
    urllib.request.urlopen("http://localhost:8000/healthz", timeout=2)
except Exception:
    sys.exit(1)
