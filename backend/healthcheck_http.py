"""Docker HEALTHCHECK for api/chaos: no curl installed, so plain urllib it is."""

import sys
import urllib.request

try:
    urllib.request.urlopen("http://localhost:8000/healthz", timeout=2)
except Exception:
    sys.exit(1)
