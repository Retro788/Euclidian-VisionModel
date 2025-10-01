#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_EXTS = {".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}

SPECIFIC_REPLACEMENTS = [
    ("MiniRetroModel", "MiniRetroModel"),
    ("mini_retro_model", "mini_retro_model"),
    ("mini_retro_spec", "mini_retro_spec"),
    ("mini_retroov", "mini_retroov"),
    ("mini_retroonevision", "mini_retroonevision"),
    (
        "multimodal_mini_retro",
        "multimodal_mini_retro",
    ),
    (
        "pretrain_mini_retro",
        "pretrain_mini_retro",
    ),
    (
        "sft_mini_retro",
        "sft_mini_retro",
    ),
]


CAMEL_CASE_RE = re.compile(r"MiniRetro")
UPPER_CASE_RE = re.compile(r"MINI_RETRO")
LOWER_CASE_RE = re.compile(r"mini-retro")


def apply_general_replacements(text: str) -> str:
    for old, new in SPECIFIC_REPLACEMENTS:
        text = text.replace(old, new)
    text = UPPER_CASE_RE.sub("MINI_RETRO", text)
    text = CAMEL_CASE_RE.sub("MiniRetro", text)

    def lower_repl(match: re.Match) -> str:
        before = match.string[match.start() - 1] if match.start() > 0 else ""
        after = match.string[match.end()] if match.end() < len(match.string) else ""
        if before == '-' or after == '-':
            return "mini-retro"
        if before.isupper() and after.isupper():
            return "MINI_RETRO"
        if before.isidentifier() or after.isidentifier():
            return "mini_retro"
        return "mini-retro"

    text = LOWER_CASE_RE.sub(lower_repl, text)
    text = re.sub(r"Mini_Retro_", "Mini_Retro_", text)
    text = re.sub(r"mini-retro(?=[A-Za-z0-9])", "mini_retro", text)
    text = re.sub(r"MINI_RETRO", "MINI_RETRO", text)
    return text


def should_process(path: Path) -> bool:
    return path.suffix.lower() in CODE_EXTS


def main() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if not should_process(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = apply_general_replacements(text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    main()
