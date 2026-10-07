"""Docker HEALTHCHECK for runner/notifier: no HTTP port, so check the tick file's age."""

import pathlib
import sys
import time

ALIVE_FILE = pathlib.Path("/tmp/alive")
MAX_AGE_SECONDS = 10

if not ALIVE_FILE.exists():
    sys.exit(1)

age = time.time() - ALIVE_FILE.stat().st_mtime
sys.exit(0 if age < MAX_AGE_SECONDS else 1)
