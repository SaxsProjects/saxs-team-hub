"""Updates must never damage the data: a migration's upgrade() may not drop tables or columns, or delete rows.

Run in CI before the migrations are applied. A drop that is genuinely needed (after the data was copied
elsewhere in the same migration) must carry the comment `# data-safe: <why>` on the same line, so it is a
deliberate, reviewed decision. Downgrades are not checked: they are only run by hand.
"""

import ast
import re
import sys
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
DANGEROUS = {"drop_table", "drop_column", "execute"}
# Statements that remove data. Match the start only: CREATE TRIGGER ... BEFORE TRUNCATE protects data.
DELETE_SQL = re.compile(r"^\s*(DROP\s+TABLE|ALTER\s+TABLE\s+\S+\s+DROP\s+COLUMN|DELETE\s+FROM|TRUNCATE)\b", re.I)


def problems(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    upgrade = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None)
    if upgrade is None:
        return []
    out = []
    for node in ast.walk(upgrade):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name not in DANGEROUS:
            continue
        if name == "execute":
            text = " ".join(a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
            if not DELETE_SQL.search(text):
                continue
        if "# data-safe:" in lines[node.lineno - 1]:
            continue
        out.append(f"{path.name}:{node.lineno}: upgrade() calls {name}() without a '# data-safe: <why>' note")
    return out


def main() -> int:
    found = [p for f in sorted(VERSIONS.glob("*.py")) for p in problems(f)]
    for line in found:
        print(f"::error::{line}")
    if not found:
        print(f"ok: {len(list(VERSIONS.glob('*.py')))} migrations, none drops or deletes data on upgrade")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
