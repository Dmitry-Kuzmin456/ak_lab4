from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass

from src.isa import (
    ADDR_REGISTERS,
    DATA_REGISTERS,
    Operand,
    OperandKind,
    OPERAND_COUNT,
    OpCode,
    SPECIAL_REGISTERS,
    encode_instruction,
    instruction_hex,
)


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


@dataclass
class TranslationResult:
    binary: bytes
    parsed: list[dict]
    labels: dict[str, int]
    constants: dict[str, int]


def _clean(line: str) -> str:
    return line.split(";", 1)[0].strip()


def _parse_number(s: str) -> int:
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        text = bytes(s[1:-1], "utf-8").decode("unicode_escape")
        if len(text) != 1:
            raise ValueError(f"Bad char literal: {s}")
        return ord(text)
    return int(s, 0)


def _opcode(code: str) -> OpCode:
    upper = code.upper()
    aliases = {"JUMP": "JMP"}
    return OpCode[aliases.get(upper, upper)]


def _replace_macro_params(line: str, bindings: dict[str, str]) -> str:
    for name, value in bindings.items():
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
            if directive == ".ifconst":
                condition_active = name in constants
            elif directive == ".ifndef":
                condition_active = name not in constants and name not in macros
            else:
                condition_active = name in constants or name in macros
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


def _split_operands(operand_text: str | None) -> list[str]:
    if operand_text is None or operand_text.strip() == "":
        return []
    return [part.strip() for part in operand_text.split(",") if part.strip()]


def _parse_string_literal(token: str) -> str:
    token = token.strip()
    if not (len(token) >= 2 and token[0] == '"' and token[-1] == '"'):
        raise ValueError(f"Bad string literal: {token}")
    return bytes(token[1:-1], "utf-8").decode("unicode_escape")


def _parse_cstr_operands(operand_text: str | None) -> list[Operand]:
    if operand_text is None:
        raise ValueError('CSTR expects address register and string: CSTR A1, "text"')
    parts = operand_text.split(",", 1)
    if len(parts) != 2:
        raise ValueError('CSTR expects address register and string: CSTR A1, "text"')
    reg = parts[0].strip().upper()
    if reg not in ADDR_REGISTERS:
        raise ValueError(
            f"CSTR destination must be address register: {parts[0].strip()}"
        )
    text = _parse_string_literal(parts[1])
    return [
        Operand(OperandKind.ADDR_REG, ADDR_REGISTERS[reg], parts[0].strip()),
        *[Operand(OperandKind.IMMEDIATE, ord(ch), repr(ch)) for ch in text],
    ]


def _resolve(
    token: str,
    labels: dict[str, int],
    constants: dict[str, int],
    allow_unresolved: bool,
) -> int:
    if token in constants:
        return constants[token]
    if token in labels:
        return labels[token]
    try:
        return _parse_number(token)
    except ValueError:
        if allow_unresolved:
            return 0
        raise ValueError(f"Unknown symbol: {token}") from None


def _parse_operand(
    token: str,
    op: OpCode,
    position: int,
    labels: dict[str, int],
    constants: dict[str, int],
    allow_unresolved: bool,
) -> Operand:
    upper = token.upper()
    if upper in DATA_REGISTERS:
        return Operand(OperandKind.DATA_REG, DATA_REGISTERS[upper], token)
    if upper in ADDR_REGISTERS:
        return Operand(OperandKind.ADDR_REG, ADDR_REGISTERS[upper], token)
    if upper in SPECIAL_REGISTERS:
        return Operand(OperandKind.SPECIAL_REG, SPECIAL_REGISTERS[upper], token)
    if token.startswith("(") and token.endswith(")+"):
        reg = token[1:-2].strip().upper()
        if reg not in ADDR_REGISTERS:
            raise ValueError(f"Bad post-increment operand: {token}")
        return Operand(OperandKind.POST_INC, ADDR_REGISTERS[reg], token)
    if token.startswith("-(") and token.endswith(")"):
        reg = token[2:-1].strip().upper()
        if reg not in ADDR_REGISTERS:
            raise ValueError(f"Bad pre-decrement operand: {token}")
        return Operand(OperandKind.PRE_DEC, ADDR_REGISTERS[reg], token)
    if token.startswith("(") and token.endswith(")"):
        reg = token[1:-1].strip().upper()
        if reg not in ADDR_REGISTERS:
            raise ValueError(f"Bad indirect operand: {token}")
        return Operand(OperandKind.INDIRECT, ADDR_REGISTERS[reg], token)
    if token.startswith("#"):
        return Operand(
            OperandKind.IMMEDIATE,
            _resolve(token[1:], labels, constants, allow_unresolved),
            token,
        )
    if op in {OpCode.BEQ, OpCode.BNE, OpCode.BLT, OpCode.BGT, OpCode.JMP}:
        return Operand(
            OperandKind.CODE_ADDR,
            _resolve(token, labels, constants, allow_unresolved),
            token,
        )
    if (op == OpCode.IN and position == 0) or (op == OpCode.OUT and position == 1):
        return Operand(
            OperandKind.PORT,
            _resolve(token, labels, constants, allow_unresolved),
            token,
        )
    if op == OpCode.OUT_CSTR:
        return Operand(
            OperandKind.DATA_ADDR,
            _resolve(token, labels, constants, allow_unresolved),
            token,
        )
    return Operand(
        OperandKind.DIRECT,
        _resolve(token, labels, constants, allow_unresolved),
        token,
    )


def _parse_operands(
    mnemonic: str,
    operand_text: str | None,
    labels: dict[str, int],
    constants: dict[str, int],
    allow_unresolved: bool = False,
) -> list[Operand]:
    op = _opcode(mnemonic)
    if op == OpCode.CSTR:
        return _parse_cstr_operands(operand_text)
    return [
        _parse_operand(token, op, pos, labels, constants, allow_unresolved)
        for pos, token in enumerate(_split_operands(operand_text))
    ]


def _validate_operands(op: OpCode, operands: list[Operand]) -> None:
    expected = OPERAND_COUNT[op]
    if expected is None:
        if op != OpCode.CSTR:
            raise ValueError(f"Bad operand count for opcode: {op}")
        if not operands or operands[0].kind != OperandKind.ADDR_REG:
            raise ValueError("CSTR expects address register and string")
    elif len(operands) != expected:
        raise ValueError(f"{op.name} expects {expected} operands, got {len(operands)}")


def _line_size(mnemonic: str | None, operand_text: str | None) -> int:
    if mnemonic is None:
        return 0
    op = _opcode(mnemonic)
    operands = _parse_operands(mnemonic, operand_text, {}, {}, allow_unresolved=True)
    _validate_operands(op, operands)
    return len(encode_instruction(op, operands))


def parse_source(source: str):
    lines = preprocess_source(source).splitlines()
    section = "text"
    text_addr = 0
    data_addr = 0
    entry = None
    labels = {}
    constants = {}
    parsed = []

    for line in lines:
        if line.lower().startswith(".const"):
            parts = line.split()
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
            parts = line.split()
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
                text = _parse_string_literal(s)
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
                parts = line.split()
                if len(parts) != 2:
                    raise ValueError(f"Bad .word directive: {line}")
                val_s = parts[1].strip()
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
        operand_text = parts[1].strip() if len(parts) > 1 else None
        parsed.append(
            {
                "section": section,
                "addr": text_addr,
                "label": label,
                "mnemonic": mnemonic,
                "operand": operand_text,
                "value": None,
            }
        )
        text_addr += _line_size(mnemonic, operand_text)

    if entry is None:
        raise ValueError("Missing required _start label in .section text")

    return parsed, labels, entry, constants


def assemble_parsed(parsed, labels, entry, constants) -> bytes:
    cmd = [0] * 65536
    data = [0] * 65536
    max_cmd = 0
    max_data = -1

    for item in parsed:
        if item["section"] == "data":
            if item["value"] is not None:
                data[item["addr"]] = item["value"]
                max_data = max(max_data, item["addr"])
            continue

        if item["mnemonic"] is None:
            continue

        op = _opcode(item["mnemonic"])
        operands = _parse_operands(item["mnemonic"], item["operand"], labels, constants)
        _validate_operands(op, operands)
        encoded = encode_instruction(op, operands)
        cmd[item["addr"] : item["addr"] + len(encoded)] = encoded
        max_cmd = max(max_cmd, item["addr"] + len(encoded) - 1)

    cmd_blob = bytes(cmd[: max_cmd + 1] if max_cmd > 0 else [0])
    data_blob = data[: max_data + 1] if max_data >= 0 else []
    out = bytearray()
    out.extend(b"AK4B")
    out.extend(struct.pack(">H", entry))
    out.extend(struct.pack(">H", len(cmd_blob)))
    out.extend(struct.pack(">H", len(data_blob)))
    out.extend(cmd_blob)
    for value in data_blob:
        out.extend(struct.pack(">i", value))
    return bytes(out)


def make_debug(parsed, labels, constants) -> str:
    lines = []
    for item in parsed:
        if item["section"] != "text" or item["mnemonic"] is None:
            continue
        op = _opcode(item["mnemonic"])
        operands = _parse_operands(item["mnemonic"], item["operand"], labels, constants)
        mnem = item["mnemonic"] + (f" {item['operand']}" if item["operand"] else "")
        lines.append(f"{item['addr']:04X} - {instruction_hex(op, operands)} - {mnem}")
    return "\n".join(lines) + ("\n" if lines else "")


def translate(source: str) -> TranslationResult:
    parsed, labels, entry, constants = parse_source(source)
    return TranslationResult(
        assemble_parsed(parsed, labels, entry, constants), parsed, labels, constants
    )


def write_debug(translation: TranslationResult, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            make_debug(translation.parsed, translation.labels, translation.constants)
        )


def write_output(source: str, output_path: str) -> bytes:
    translation = translate(source)
    with open(output_path, "wb") as f:
        f.write(translation.binary)
    write_debug(translation, output_path + ".log")
    return translation.binary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()

    with open(args.source, encoding="utf-8") as f:
        text = f.read()

    write_output(text, args.output)


if __name__ == "__main__":
    main()
