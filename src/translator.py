from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass

from src.isa import OpCode


INSTR_WITH_OPERAND = {
    OpCode.LD,
    OpCode.LD_IND,
    OpCode.LD_IMM,
    OpCode.ST,
    OpCode.ST_IND,
    OpCode.ADD,
    OpCode.ADD_IND,
    OpCode.ADD_IMM,
    OpCode.MUL,
    OpCode.DIV,
    OpCode.MOD,
    OpCode.SUB,
    OpCode.SUB_IND,
    OpCode.SUB_IMM,
    OpCode.BEQ,
    OpCode.BNE,
    OpCode.BLT,
    OpCode.BGT,
    OpCode.JMP,
    OpCode.CMP,
    OpCode.CMP_IND,
    OpCode.CMP_IMM,
    OpCode.IN,
    OpCode.OUT,
    OpCode.OUT_CSTR,
}

IMM_ONEBYTE = {
    OpCode.LD_IMM,
    OpCode.ADD_IMM,
    OpCode.SUB_IMM,
    OpCode.CMP_IMM,
}


@dataclass
class Macro:
    params: list[str]
    body: list[str]


@dataclass
class ConditionalFrame:
    parent_active: bool
    condition_active: bool
    else_seen: bool = False

    @property
    def active(self) -> bool:
        return self.parent_active and self.condition_active


def _clean(line: str) -> str:
    return line.split(";", 1)[0].split("#", 1)[0].strip()


def _parse_number(s: str) -> int:
    s = s.strip()
    if s.startswith("'") and s.endswith("'") and len(s) == 3:
        return ord(s[1])
    return int(s, 0)


def _line_size(cmd: str | None) -> int:
    if cmd is None:
        return 0
    name = cmd.upper()
    if name == "JUMP":
        name = "JMP"
    op = OpCode[name]
    if op in IMM_ONEBYTE:
        return 2
    if op in INSTR_WITH_OPERAND:
        return 3
    return 1


def _resolve(s: str, labels: dict[str, int]) -> int:
    if s in labels:
        return labels[s]
    return _parse_number(s)


def _opcode(name: str) -> OpCode:
    up = name.upper()
    if up == "JUMP":
        up = "JMP"
    return OpCode[up]


def _replace_macro_params(line: str, bindings: dict[str, str]) -> str:
    for name, value in bindings.items():
        line = line.replace("{" + name + "}", value)
        line = re.sub(rf"\b{re.escape(name)}\b", value, line)
    return line


def _expand_macro(macro: Macro, args: list[str]) -> list[str]:
    if len(args) != len(macro.params):
        raise ValueError(
            f"Macro expects {len(macro.params)} arguments, got {len(args)}"
        )
    bindings = dict(zip(macro.params, args))
    return [_replace_macro_params(line, bindings) for line in macro.body]


def preprocess_source(source: str) -> str:
    lines = source.splitlines()
    macros: dict[str, Macro] = {}
    constants: set[str] = set()
    conditionals: list[ConditionalFrame] = []
    output: list[str] = []
    macro_name: str | None = None
    macro_params: list[str] = []
    macro_body: list[str] = []

    def is_active() -> bool:
        return all(frame.active for frame in conditionals)

    for raw in lines:
        line = _clean(raw)
        if not line:
            continue

        parts = line.split()
        directive = parts[0].lower()

        if directive in [".ifdef", ".ifndef", ".ifconst"]:
            if len(parts) != 2:
                raise ValueError(f"Bad conditional directive: {line}")
            parent_active = is_active()
            name = parts[1]
            is_defined = name in constants or name in macros
            if directive == ".ifndef":
                condition_active = not is_defined
            else:
                condition_active = is_defined
            conditionals.append(ConditionalFrame(parent_active, condition_active))
            continue

        if directive == ".else":
            if len(parts) != 1 or not conditionals:
                raise ValueError(f"Bad .else directive: {line}")
            frame = conditionals[-1]
            if frame.else_seen:
                raise ValueError(f"Duplicate .else directive: {line}")
            frame.condition_active = not frame.condition_active
            frame.else_seen = True
            continue

        if directive == ".endif":
            if len(parts) != 1 or not conditionals:
                raise ValueError(f"Bad .endif directive: {line}")
            conditionals.pop()
            continue

        if not is_active():
            continue

        if macro_name is not None:
            if directive == ".endmacro":
                if len(parts) != 1:
                    raise ValueError(f"Bad .endmacro directive: {line}")
                macros[macro_name] = Macro(macro_params, macro_body)
                macro_name = None
                macro_params = []
                macro_body = []
            else:
                macro_body.append(line)
            continue

        if directive == ".macro":
            if len(parts) < 2:
                raise ValueError(f"Bad .macro directive: {line}")
            macro_name = parts[1]
            macro_params = parts[2:]
            macro_body = []
            continue

        if directive == ".endmacro":
            raise ValueError(f"Unexpected .endmacro directive: {line}")

        if directive == ".const":
            if len(parts) != 3:
                raise ValueError(f"Bad .const directive: {line}")
            constants.add(parts[1])

        name = parts[0]
        if name in macros:
            args = line.split(maxsplit=1)[1].split() if len(parts) > 1 else []
            output.extend(_expand_macro(macros[name], args))
        else:
            output.append(line)

    if macro_name is not None:
        raise ValueError(f"Unclosed macro: {macro_name}")
    if conditionals:
        raise ValueError("Unclosed conditional block")

    return "\n".join(output)


def parse_source(source: str):
    lines = preprocess_source(source).splitlines()
    section = "text"
    text_addr = 0
    data_addr = 0
    entry = None
    labels = {}
    constants = {}
    parsed = []

    for raw in lines:
        line = _clean(raw)
        if not line:
            continue

        if line.lower().startswith(".const"):
            parts = line.split(maxsplit=2)
            if len(parts) != 3:
                raise ValueError(f"Bad .const directive: {line}")
            constants[parts[1]] = _parse_number(parts[2])
            continue

        if line.lower().startswith(".section"):
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Bad section directive: {line}")
            section = parts[1].lower()
            if section not in ["text", "data"]:
                raise ValueError(f"Unknown section: {section}")
            continue

        if line.lower().startswith(".org"):
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                raise ValueError(f"Bad org directive: {line}")
            value = _parse_number(parts[1])
            if section == "text":
                text_addr = value
            else:
                data_addr = value
            continue

        label = None
        if ":" in line:
            left, right = line.split(":", 1)
            label = left.strip()
            line = right.strip()
            if label in labels:
                raise ValueError(f"Duplicate label: {label}")
            labels[label] = text_addr if section == "text" else data_addr
            if section == "text" and label == "_start":
                entry = text_addr

        if not line:
            parsed.append(
                {
                    "section": section,
                    "addr": text_addr if section == "text" else data_addr,
                    "label": label,
                    "mnemonic": None,
                    "operand": None,
                    "value": None,
                }
            )
            continue

        if section == "data":
            if line.lower().startswith(".cstr"):
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    raise ValueError(f"Bad .cstr directive: {line}")
                s = parts[1].strip()
                if not (len(s) >= 2 and s[0] == '"' and s[-1] == '"'):
                    raise ValueError(f"Bad .cstr literal: {line}")
                text = bytes(s[1:-1], "utf-8").decode("unicode_escape")
                for ch in text:
                    parsed.append(
                        {
                            "section": section,
                            "addr": data_addr,
                            "label": label,
                            "mnemonic": None,
                            "operand": None,
                            "value": ord(ch),
                        }
                    )
                    label = None
                    data_addr += 1
                parsed.append(
                    {
                        "section": section,
                        "addr": data_addr,
                        "label": label,
                        "mnemonic": None,
                        "operand": None,
                        "value": 0,
                    }
                )
                data_addr += 1
                continue
            if line.lower().startswith(".word"):
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    raise ValueError(f"Bad .word directive: {line}")
                val_s = parts[1].strip()
                value = constants[val_s] if val_s in constants else _parse_number(val_s)
            else:
                val_s = line.strip()
                value = constants[val_s] if val_s in constants else _parse_number(val_s)
            parsed.append(
                {
                    "section": section,
                    "addr": data_addr,
                    "label": label,
                    "mnemonic": None,
                    "operand": None,
                    "value": value,
                }
            )
            data_addr += 1
            continue

        parts = line.split(maxsplit=1)
        mnemonic = parts[0]
        operand = parts[1].strip() if len(parts) > 1 else None
        if operand in constants:
            operand = str(constants[operand])
        parsed.append(
            {
                "section": section,
                "addr": text_addr,
                "label": label,
                "mnemonic": mnemonic,
                "operand": operand,
                "value": None,
            }
        )
        text_addr += _line_size(mnemonic)

    if entry is None:
        raise ValueError("Missing required _start label in .section text")

    return parsed, labels, entry


def assemble(source: str) -> bytes:
    parsed, labels, entry = parse_source(source)
    cmd = [0] * 65536
    data = {}
    max_cmd = 0

    for item in parsed:
        if item["section"] == "data":
            if item["value"] is not None:
                data[item["addr"]] = item["value"]
            continue

        if item["mnemonic"] is None:
            continue

        op = _opcode(item["mnemonic"])
        cmd[item["addr"]] = op.value
        end = item["addr"]
        if op in INSTR_WITH_OPERAND:
            if item["operand"] is None:
                raise ValueError(f"Missing operand for {item['mnemonic']}")
            op_token = item["operand"]
            value = labels[op_token] if op_token in labels else _parse_number(op_token)
            if op in IMM_ONEBYTE:
                cmd[item["addr"] + 1] = value & 0xFF
                end = item["addr"] + 1
            else:
                cmd[item["addr"] + 1] = (value >> 8) & 0xFF
                cmd[item["addr"] + 2] = value & 0xFF
                end = item["addr"] + 2
        max_cmd = max(max_cmd, end)

    cmd_blob = bytes(cmd[: max_cmd + 1] if max_cmd > 0 else [0])
    out = bytearray()
    out.extend(b"AK4B")
    out.extend(struct.pack(">H", entry))
    out.extend(struct.pack(">H", len(cmd_blob)))
    out.extend(cmd_blob)
    out.extend(struct.pack(">H", len(data)))
    for addr in sorted(data.keys()):
        out.extend(struct.pack(">Hi", addr, data[addr]))
    return bytes(out)


def write_debug(source: str, path: str) -> None:
    parsed, labels, _ = parse_source(source)
    with open(path, "w", encoding="utf-8") as f:
        for item in parsed:
            if item["section"] != "text" or item["mnemonic"] is None:
                continue
            op = _opcode(item["mnemonic"])
            if op in INSTR_WITH_OPERAND:
                operand = 0
                if item["operand"] is not None:
                    token = item["operand"]
                    operand = labels[token] if token in labels else _parse_number(token)
                if op in IMM_ONEBYTE:
                    hexc = f"{op.value:02X}{operand & 0xFF:02X}"
                else:
                    hexc = (
                        f"{op.value:02X}{(operand >> 8) & 0xFF:02X}{operand & 0xFF:02X}"
                    )
                mnem = f"{item['mnemonic']} {item['operand']}"
            else:
                hexc = f"{op.value:02X}"
                mnem = item["mnemonic"]
            f.write(f"{item['addr']:04X} - {hexc} - {mnem}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--debug", default=None)
    args = parser.parse_args()

    with open(args.source, encoding="utf-8") as f:
        text = f.read()

    blob = assemble(text)
    with open(args.output, "wb") as f:
        f.write(blob)
    if args.debug is not None:
        write_debug(text, args.debug)


if __name__ == "__main__":
    main()
