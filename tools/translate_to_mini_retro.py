#!/usr/bin/env python3
import re
import sys
from pathlib import Path

try:
    from deep_translator import GoogleTranslator
except ImportError as exc:
    raise SystemExit("deep-translator no está instalado. Ejecuta `python -m pip install --user deep-translator`." ) from exc

PLACEHOLDER_PREFIX = "__MINIRETRO_"


def replace_terms(text: str) -> str:
    """Reemplaza distintas variantes de 'mini-retro' por formas de mini-retro conservando mayúsculas"""
    def repl(match: re.Match) -> str:
        token = match.group(0)
        if token.isupper():
            return "MINI_RETRO"
        if token[0].isupper():
            return "Mini-retro"
        return "mini-retro"

    return re.sub(r"(?i)mini-retro", repl, text)


def replace_code_terms(text: str) -> str:
    """Ajustes en segmentos de código o comandos donde los guiones son problemáticos"""
    text = re.sub(r"(?i)mini_retro_", "mini_retro_", text)
    text = re.sub(r"(?i)mini-retro-", "mini-retro-", text)
    text = re.sub(r"(?i)mini-retro", "mini-retro", text)
    return text


def protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    pattern = re.compile(r"[\w\-/]*mini-retro[\w\-/]*", re.IGNORECASE)
    tokens = sorted({match.group(0) for match in pattern.finditer(text)}, key=len, reverse=True)
    placeholders: dict[str, str] = {}
    for idx, token in enumerate(tokens):
        placeholder = f"{PLACEHOLDER_PREFIX}{idx}__"
        placeholders[placeholder] = token
        text = text.replace(token, placeholder)
    return text, placeholders


def restore_tokens(text: str, placeholders: dict[str, str]) -> str:
    for placeholder, token in placeholders.items():
        text = text.replace(placeholder, token)
    return text


def cleanup_text(text: str) -> str:
    text = text.replace("mini-retro-anevision", "mini-retro-OneVision")
    text = text.replace("mini-retro-next", "mini-retro-NeXT")
    text = text.replace("WebDataSet", "WebDataset")
    text = text.replace("hf/mini-retro", "HF/mini-retro")
    text = text.replace("alturra", "altura")
    text = re.sub(r"\*\*\s+", "**", text)
    text = re.sub(r"\s+\*\*", "**", text)
    text = re.sub(r"\[\s+", "[", text)
    text = re.sub(r"\s+\]", "]", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+=\s+", "=", text)
    text = re.sub(r"/\s+", "/", text)
    text = re.sub(r"\s+/", "/", text)
    text = re.sub(r"\s+:", ":", text)
    text = re.sub(r" :", ":", text)
    return text


def translate_chunk(translator: GoogleTranslator, chunk: str) -> str:
    chunk = replace_terms(chunk)
    chunk, placeholders = protect_tokens(chunk)
    translated = translator.translate(chunk)
    translated = restore_tokens(translated, placeholders)
    translated = cleanup_text(translated)
    return translated


def translate_table_line(translator: GoogleTranslator, line: str) -> str:
    stripped_line = line.strip()
    if not stripped_line or set(stripped_line.replace("|", "").strip()) <= {"-", ":"}:
        return stripped_line
    cells = [cell.strip() for cell in stripped_line.strip("|").split("|")]
    translated_cells = []
    for cell in cells:
        if not cell or set(cell) <= {"-", ":"}:
            translated_cells.append(cell)
        else:
            translated_cells.append(translate_chunk(translator, cell))
    return "| " + " | ".join(translated_cells) + " |"


def process_file(path: Path) -> None:
    translator = GoogleTranslator(source="auto", target="es")
    lines = path.read_text(encoding="utf-8").splitlines()
    result_lines: list[str] = []
    code_block = False
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        chunk = "\n".join(buffer)
        if chunk.strip():
            parts = chunk.split("\n\n")
            translated_parts = []
            for part in parts:
                if part.strip():
                    translated_parts.append(translate_chunk(translator, part))
                else:
                    translated_parts.append("")
            translated_chunk = "\n\n".join(translated_parts)
        else:
            translated_chunk = chunk
        result_lines.extend(translated_chunk.split("\n"))
        buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_buffer()
            code_block = not code_block
            result_lines.append(line)
            continue
        if code_block:
            result_lines.append(replace_code_terms(line))
            continue
        if stripped.startswith("|"):
            flush_buffer()
            translated_line = translate_table_line(translator, line)
            result_lines.append(translated_line)
            continue
        buffer.append(line)

    flush_buffer()
    path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")


def main(args: list[str]) -> None:
    if not args:
        raise SystemExit("Uso: python translate_mini_retro_to_mini_retro.py <ruta_del_archivo> [más rutas...]")
    for raw_path in args:
        path = Path(raw_path)
        if not path.exists():
            print(f"Omitido {raw_path}: no existe", file=sys.stderr)
            continue
        print(f"Traduciendo {path}")
        process_file(path)


if __name__ == "__main__":
    main(sys.argv[1:])
