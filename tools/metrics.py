"""機能ごとの品質指標を集計し、knowledge/metrics.csv に1行ずつ記録する（同じ機能は上書き）。

使い方: python tools/metrics.py <機能名>

指標は「使うほど良くなっているか」を見るためのもの。機能を重ねるごとに
AIレビューNG・人の差し戻し・手直し・ビルドエラー・共通部品の再利用漏れが減っていくのが望ましい。
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

FIELDS = [
    "機能名", "集計日時", "要件数", "質問数", "過去回答の参照数", "差異数", "IU数", "要人判断IU数",
    "AIレビューNG", "AIレビュー上限到達", "人の差し戻し", "手直し", "ビルドエラー",
    "共通部品の再利用漏れ", "形式エラー", "人が読む文書の行数",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def collect(feature: str) -> dict:
    fdir = C.feature_dir(feature)
    st = C.load_status(feature)
    hist = st.get("history", [])
    ev = lambda name: sum(1 for h in hist if h["event"] == name)  # noqa: E731
    req = _read(fdir / "_ai" / "01_requirements.md")
    align = _read(fdir / C.HUMAN_DOC_ALIGNMENT)
    plan = _read(fdir / C.HUMAN_DOC_PLAN)
    unit_docs = sorted(fdir.glob("③IU-*.md"))
    reviews = sorted((fdir / "_ai").glob("IU-*/review.md"))
    units = C.load_plan_units(feature)
    qs = {
        m.group(0)
        for doc in (align, plan)
        for tbl in C.md_tables(C.section(doc, "質問"))
        for r in tbl[1:]
        if r and (m := C.Q_RE.match(r[0]))
    }
    past = len(re.findall(r"過去の回答\s*Q-\d+", align + plan))
    diffs = set(re.findall(r"\bD-\d{2,}\b", C.section(align, "差異")))
    reuse_miss = sum(_read(r).count("共通部品未使用") for r in reviews)
    lines = sum(len(_read(p).splitlines()) for p in [fdir / C.HUMAN_DOC_ALIGNMENT, fdir / C.HUMAN_DOC_PLAN, *unit_docs])
    return {
        "機能名": feature,
        "集計日時": C.now(),
        "要件数": len(re.findall(r"^##\s+REQ-\d+", req, re.M)),
        "質問数": len(qs),
        "過去回答の参照数": past,
        "差異数": len(diffs),
        "IU数": len(units),
        "要人判断IU数": sum(1 for u in units.values() if u.get("ai") == "要人判断"),
        "AIレビューNG": ev("review_ng") + ev("escalated"),
        "AIレビュー上限到達": ev("escalated"),
        "人の差し戻し": ev("rejected"),
        "手直し": ev("human_rework"),
        "ビルドエラー": ev("build_error"),
        "共通部品の再利用漏れ": reuse_miss,
        "形式エラー": ev("format_error"),
        "人が読む文書の行数": lines,
    }


def upsert(row: dict) -> Path:
    p = C.knowledge_dir() / "metrics.csv"
    rows = []
    if p.exists():
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("機能名") != row["機能名"]]
    rows.append(row)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    row = collect(argv[0])
    p = upsert(row)
    print(f"集計しました: {p.relative_to(C.root()).as_posix()}")
    for k in FIELDS[2:]:
        print(f"- {k}: {row[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
