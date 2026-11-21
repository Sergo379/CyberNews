"""Drive the real interactive bootstrap CLI in the disposable Linux test container."""

import json
import os
import pty
import select
import subprocess
import sys
from time import monotonic


def read_until(terminal, prompt, transcript):
    deadline = monotonic() + 12
    while prompt not in transcript:
        remaining = deadline - monotonic()
        if remaining <= 0 or not select.select([terminal], [], [], remaining)[0]:
            raise RuntimeError("Timed out waiting for bootstrap CLI")
        try:
            chunk = os.read(terminal, 1024)
        except OSError:
            raise RuntimeError("Bootstrap CLI exited before the expected prompt") from None
        if not chunk:
            raise RuntimeError("Bootstrap CLI closed its terminal")
        transcript.extend(chunk)


def main():
    data = json.load(sys.stdin)
    terminal, slave = pty.openpty()
    with subprocess.Popen(
        [sys.executable, "-m", "app.bootstrap"], stdin=slave, stdout=slave, stderr=slave,
    ) as process:
        os.close(slave)
        try:
            transcript = bytearray()
            for prompt, field in (
                (b"Email: ", "email"),
                (b"Nickname: ", "nickname"),
                (b"Account password: ", "password"),
                (b"Administrative password: ", "admin_password"),
                (b"Confirm account password: ", "password"),
                (b"Confirm administrative password: ", "admin_password"),
            ):
                read_until(terminal, prompt, transcript)
                os.write(terminal, data[field].encode() + b"\n")
            read_until(terminal, b"Created Super Admin ", transcript)
            if process.wait(timeout=12) != 0:
                raise RuntimeError("Bootstrap CLI failed")
            if any(data[field].encode() in transcript for field in ("password", "admin_password")):
                raise RuntimeError("Bootstrap CLI echoed a password")
        finally:
            os.close(terminal)
            if process.poll() is None:
                process.kill()
    print("PASS: Interactive Super Admin setup with hidden password input.")


if __name__ == "__main__":
    main()
