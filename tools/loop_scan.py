import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--roots", nargs="*", default=["."])
parser.add_argument(
    "--exclude",
    nargs="*",
    default=["node_modules", "dist", "build", ".git", ".venv", "__pycache__", ".mypy_cache"],
)
args = parser.parse_args()

patterns = {
    "while_true": re.compile(r"while\s*\(\s*true\s*\)|while\s+True\b", re.IGNORECASE),
    "for_ever": re.compile(r"for\s*\(\s*;\s*;\s*\)"),
    "do_while_1": re.compile(r"do\s*\{[\s\S]*?\}\s*while\s*\(\s*1\s*\)", re.IGNORECASE),
    "float_eq": re.compile(r"while\s*\([^)]*==[^)]*\)"),
}

exclude_tokens = set(args.exclude)


def is_excluded(path: Path) -> bool:
    return any(part in exclude_tokens for part in path.parts)


report_lines = []
for root in [Path(r).resolve() for r in args.roots]:
    for file in root.rglob("*"):
        if file.is_dir() or is_excluded(file):
            continue
        if file.suffix not in {".py", ".js", ".ts", ".tsx"}:
            continue
        try:
            text = file.read_text(errors="ignore")
        except (UnicodeDecodeError, OSError):
            continue
        relative = file.relative_to(root)
        if is_excluded(relative):
            continue
        for name, pattern in patterns.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                snippet = text[match.start() : match.start() + 160].replace("\n", " ")
                report_lines.append((name, str(relative), line, snippet))

report_lines.sort()
report_path = Path("tools/loop_scan_report.txt")
report_path.parent.mkdir(parents=True, exist_ok=True)
with report_path.open("w") as f:
    for name, file, line, snippet in report_lines:
        f.write(f"[{name}] {file}:{line} {snippet}\n")
print(f"Wrote {len(report_lines)} candidates to {report_path}")
