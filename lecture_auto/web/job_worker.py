"""Keep credential redaction alive with the job when the web server restarts."""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def main() -> int:
    keys = {os.environ[k].encode() for k in ("BAZE_API_KEY", "FACTCHAT_API_KEY", "OPENAI_API_KEY")
            if os.environ.get(k)}
    ready_fd = int(sys.argv[1])
    with subprocess.Popen(sys.argv[2:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
        # Reap the worker after a group cancellation instead of leaving it orphaned.
        signal.signal(signal.SIGTERM, lambda _sig, _frame: child.terminate())
        with os.fdopen(ready_fd, "wb") as ready:
            ready.write(b"ready\n")
        with child.stdout:
            for line in child.stdout:
                for key in keys:
                    line = line.replace(key, b"[REDACTED]")
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
        return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
