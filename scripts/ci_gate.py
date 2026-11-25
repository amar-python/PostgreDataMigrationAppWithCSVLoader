#!/usr/bin/env python3
"""One verdict from the parallel database jobs, for the `integration (postgres service)` check of quality-gate.yml.

    python3 scripts/ci_gate.py <code-changed: true|false> shards=<result> egress=<result> coverage=<result>

The check keeps the name it always had, so a branch-protection rule that requires it keeps working, but the work now
happens in several jobs. This script turns their results into one answer:

  * code changed (``true``): every job must be ``success``. A job that was SKIPPED is a failure here: if the jobs are
    skipped by mistake the gate must not read "nothing is red" as "all is well";
  * documentation only (``false``): the jobs are expected to be ``skipped``; ``success`` is fine too, anything else
    (``failure``, ``cancelled``) still fails;
  * anything else for ``changed``, including empty (the changes job itself failed), fails.

Exit status 0 for pass, 1 for fail. The message names every job and what it did.
"""

from __future__ import annotations

import sys


def verdict(changed: str, results: dict[str, str]) -> tuple[int, str]:
    lines = [f"code changed: {changed!r}"] + [f"  {name}: {result}" for name, result in sorted(results.items())]
    if changed not in ("true", "false"):
        return 1, "\n".join(lines + ["FAIL: the changes job gave no usable answer, so nothing may be skipped"])
    if not results:
        return 1, "\n".join(lines + ["FAIL: no job results were given"])
    allowed = {"success"} if changed == "true" else {"success", "skipped"}
    bad = [name for name, result in sorted(results.items()) if result not in allowed]
    if bad:
        return 1, "\n".join(lines + [f"FAIL: {', '.join(bad)} did not finish as required"])
    return 0, "\n".join(lines + ["PASS"])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: ci_gate.py <true|false> name=result ...", file=sys.stderr)
        return 1
    results = dict(item.split("=", 1) for item in args[1:] if "=" in item)
    code, message = verdict(args[0], results)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
