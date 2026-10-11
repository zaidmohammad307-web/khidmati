import math


def evaluate(kind, value, minimum=0, maximum=0, expected=True, options=(), expected_text=""):
    if kind == "numeric":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Enter a finite numeric reading.")
        return minimum <= value <= maximum
    if kind in ("boolean", "pass_fail"):
        if not isinstance(value, bool):
            raise ValueError("Select PASS/FAIL or Yes/No.")
        return value == expected
    if kind in ("text", "selection"):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Enter a result.")
        if kind == "selection" and value not in options:
            raise ValueError("Select an allowed result.")
        return not expected_text or value == expected_text
    raise ValueError("Unsupported test type.")
