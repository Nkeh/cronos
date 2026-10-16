"""Docker HEALTHCHECK: no curl installed, so plain urllib it is.

Hits /healthz on both listeners: the plain port, which the catch-all route answers 200 unless
something has explicitly set that path to "down" via /_control, and the tls-bad port (8443),
whose certificate never verifies by design -- so this probes it with an unverified SSL context,
which still catches the second listener failing to start at all.
"""

import ssl
import sys
import urllib.request

try:
    urllib.request.urlopen("http://localhost:8000/healthz", timeout=2)
except Exception:
    sys.exit(1)

try:
    unverified = ssl._create_unverified_context()
    urllib.request.urlopen("https://localhost:8443/healthz", timeout=2, context=unverified)
except Exception:
    sys.exit(1)
