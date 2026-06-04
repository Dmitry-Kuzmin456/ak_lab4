from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent
GOLDEN_ROOT = ROOT / "golden"
sys.path.insert(0, str(PROJECT_ROOT))

from src.translator import (  # noqa: E402
    main as translator_main,
    preprocess_source,
    translate,
    write_output,
)
from src.run_code import run_source  # noqa: E402

machine = importlib.import_module("src.machine")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_golden(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _assert_contains(actual: str, expected: str) -> None:
    for line in expected.splitlines():
        if line.strip():
            assert line in actual


GOLDEN_CASES = sorted(GOLDEN_ROOT.glob("*.yml"))


@pytest.mark.parametrize("golden_path", GOLDEN_CASES, ids=lambda path: path.stem)
def test_golden_cases(tmp_path: Path, golden_path: Path) -> None:
    golden = _load_golden(golden_path)
    source = golden["in_source"]
    input_text = golden.get("in_input", "").removesuffix("\n")
    output_expected = golden["out"]["out_stdout"]
    code_log_expected = golden["out"]["out_code_log"]
    trace_contains = golden["out"].get("out_trace_contains", "")
    limit = golden.get("in_limit", 100000)

    input_path = tmp_path / f"{golden_path.stem}.input"
    binary_path = tmp_path / f"{golden_path.stem}.bin"
    debug_path = tmp_path / f"{golden_path.stem}.bin.log"
    trace_path = tmp_path / f"{golden_path.stem}.trace"

    binary = write_output(source, str(binary_path))
    input_path.write_text(input_text, encoding="utf-8")

    assert binary[:4] == b"AK4B"

    output = machine.run(
        str(binary_path),
        str(input_path),
        limit,
        str(trace_path),
    )

    assert output == output_expected
    assert debug_path.read_text(encoding="utf-8") == code_log_expected
    _assert_contains(trace_path.read_text(encoding="utf-8"), trace_contains)


def test_start_label_is_required() -> None:
    source = """
    .section text
    HLT
    """

    with pytest.raises(ValueError, match="Missing required _start label"):
        translate(source)


def test_ifconst_only_matches_constants() -> None:
    source = """
    .macro FEATURE
        HLT
    .endmacro
    .ifconst FEATURE
        MOV #'N', R1
    .else
        MOV #'Y', R1
    .endif
    """

    assert "MOV #'Y', R1" in preprocess_source(source)
    assert "MOV #'N', R1" not in preprocess_source(source)


def test_translator_writes_default_debug_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "hello.asm"
    binary_path = tmp_path / "hello.bin"
    source_path.write_text(
        _load_golden(GOLDEN_ROOT / "hello.yml")["in_source"], encoding="utf-8"
    )

    monkeypatch.setattr(
        sys, "argv", ["translator", str(source_path), str(binary_path)]
    )
    translator_main()

    debug_path = tmp_path / "hello.bin.log"
    assert binary_path.exists()
    assert debug_path.exists()
    assert "OUT_CSTR" in debug_path.read_text(encoding="utf-8")


def test_run_code_assembles_and_runs_source(tmp_path: Path) -> None:
    source_path = tmp_path / "cat.asm"
    input_path = tmp_path / "input.txt"
    output_path = tmp_path / "output.txt"
    trace_path = tmp_path / "trace.log"

    source_path.write_text(
        _load_golden(GOLDEN_ROOT / "cat.yml")["in_source"], encoding="utf-8"
    )
    input_path.write_text("abc", encoding="utf-8")

    output = run_source(
        source_path,
        input_path,
        output_path,
        trace_path,
        1000,
    )

    assert output == "abc"
    assert output_path.read_text(encoding="utf-8") == "abc"
    assert source_path.with_suffix(".bin").exists()
    assert source_path.with_suffix(".bin.log").exists()
    assert "IN[0] -> R1=97" in trace_path.read_text(encoding="utf-8")
