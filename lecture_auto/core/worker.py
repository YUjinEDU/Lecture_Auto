from __future__ import annotations

import sys
from pathlib import Path

from lecture_auto.core.jobs import command, read_spec


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m lecture_auto.core.worker <job spec .json>", file=sys.stderr)
        return 2
    spec = read_spec(Path(args[0]))
    target, cli_args = command(spec)
    print(f"job {spec.kind} {spec.project_id}: {target} {' '.join(cli_args)}", flush=True)
    if target == "produce":
        from scripts.produce import main as produce_main

        return produce_main(cli_args)
    from lecture_auto.production.batch import main as batch_main

    batch_main(cli_args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
