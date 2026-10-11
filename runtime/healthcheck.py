"""A working login page is required; a listening TCP socket alone is insufficient."""

import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    try:
        with urlopen("http://127.0.0.1:8069/web/login", timeout=4) as response:
            body = response.read(512_000)
            return 0 if response.status == 200 and b'name="login"' in body else 1
    except (URLError, TimeoutError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
