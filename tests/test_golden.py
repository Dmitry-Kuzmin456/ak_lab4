from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent
GOLDEN_ROOT = ROOT / "golden"
sys.path.insert(0, str(PROJECT_ROOT))

from src.translator import assemble, write_debug  # noqa: E402
from src.run_code import run_source  # noqa: E402

machine = importlib.import_module("src.machine")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_output(path: Path) -> str:
    return _read(path).removesuffix("\n")


def _assert_contains(actual: str, expected_path: Path) -> None:
    expected = _read(expected_path)
    for line in expected.splitlines():
        if line.strip():
            assert line in actual


def _read_limit(case: Path) -> int:
    limit_file = case / "limit.txt"
    if limit_file.exists():
        return int(limit_file.read_text(encoding="utf-8").strip())
    return 100000


def test_golden_cases(tmp_path: Path) -> None:
    cases = [path for path in sorted(GOLDEN_ROOT.iterdir()) if path.is_dir()]
    assert cases

    for case in cases:
        source = _read(case / "source.asm")
        input_path = case / "input.txt"
        prepared_input_path = tmp_path / f"{case.name}.input"
        binary_path = tmp_path / f"{case.name}.bin"
        debug_path = tmp_path / f"{case.name}.dbg"
        trace_path = tmp_path / f"{case.name}.trace"

        binary = assemble(source)
        binary_path.write_bytes(binary)
        write_debug(source, str(debug_path))
        prepared_input_path.write_text(_read_output(input_path), encoding="utf-8")

        assert binary[:4] == b"AK4B"

        output = machine.run(
            str(binary_path),
            str(prepared_input_path) if input_path.exists() else None,
            _read_limit(case),
            (case / "superscalar").exists(),
            str(trace_path),
        )

        assert output == _read_output(case / "expected_output.txt")
        _assert_contains(
            debug_path.read_text(encoding="utf-8"), case / "expected_debug.txt"
        )
        _assert_contains(
            trace_path.read_text(encoding="utf-8"), case / "expected_trace.txt"
        )


def test_start_label_is_required() -> None:
    source = """
    .section text
    HLT
    """

    with pytest.raises(ValueError, match="Missing required _start label"):
        assemble(source)


def test_run_code_assembles_and_runs_source(tmp_path: Path) -> None:
    source_path = tmp_path / "cat.asm"
    input_path = tmp_path / "input.txt"
    output_path = tmp_path / "output.txt"
    trace_path = tmp_path / "trace.log"

    source_path.write_text(_read(GOLDEN_ROOT / "cat" / "source.asm"), encoding="utf-8")
    input_path.write_text("abc", encoding="utf-8")

    output = run_source(
        source_path,
        input_path,
        output_path,
        trace_path,
        1000,
        False,
    )

    assert output == "abc"
    assert output_path.read_text(encoding="utf-8") == "abc"
    assert source_path.with_suffix(".bin").exists()
    assert "IN[0] -> AC=97" in trace_path.read_text(encoding="utf-8")
