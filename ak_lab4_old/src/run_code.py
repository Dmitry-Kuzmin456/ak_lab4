from __future__ import annotations

import argparse
from pathlib import Path

from src import machine
from src.translator import write_output


def run_source(
    source_path: Path,
    input_path: Path | None,
    output_path: Path | None,
    trace_path: Path | None,
    limit: int,
) -> str:
    source = source_path.read_text(encoding="utf-8")
    binary_path = source_path.with_suffix(".bin")
    write_output(source, str(binary_path))

    actual_trace_path = trace_path or source_path.with_suffix(".trace")
    output = machine.run(
        str(binary_path),
        str(input_path) if input_path is not None else None,
        limit,
        str(actual_trace_path),
    )

    if output_path is not None:
        output_path.write_text(output, encoding="utf-8")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble an asm source file and run it immediately."
    )
    parser.add_argument("source", help="asm source file")
    parser.add_argument("--input", default=None, help="input stream file")
    parser.add_argument("--output", default=None, help="file for program output")
    parser.add_argument(
        "--trace",
        default=None,
        help="trace file path; defaults to SOURCE.trace next to the asm file",
    )
    parser.add_argument("--limit", type=int, default=1000000)
    args = parser.parse_args()

    output = run_source(
        Path(args.source),
        Path(args.input) if args.input is not None else None,
        Path(args.output) if args.output is not None else None,
        Path(args.trace) if args.trace is not None else None,
        args.limit,
    )
    if args.output is None:
        print(output, end="")


if __name__ == "__main__":
    main()
