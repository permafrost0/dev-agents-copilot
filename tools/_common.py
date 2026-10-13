"""tools/ 配下のスクリプトで共有する処理。

パスの解決、設定の読み込み、実行中コンテキスト（work/.current.json）、
状態ファイル（work/<機能名>/status.json）、成果物の参照書式の解析、
③の変更前スナップショットと累積差分をまとめる。
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------- 出力の文字コード
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - reconfigure できないストリーム
        pass


# ---------------------------------------------------------------- ルートとパス
def root() -> Path:
    """配布物のルート（.github/copilot-instructions.md がある場所）。"""
    env = os.environ.get("AGENT_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def work_dir() -> Path:
    return root() / "work"


def feature_dir(feature: str) -> Path:
    return work_dir() / feature


def knowledge_dir() -> Path:
    return root() / "knowledge"


def design_doc_dir() -> Path:
    return root() / "input" / "設計書"


def policy_doc_dir() -> Path:
    return root() / "input" / "設計方針"


PROFILE_FEATURE = "_profile"

# 人が読むドキュメント（ゲートごとに1つ）
HUMAN_DOC_ALIGNMENT = "①認識合わせ.md"
HUMAN_DOC_PLAN = "②実装計画.md"
HUMAN_DOC_PROFILE = "⓪プロファイル確認.md"


def human_doc_unit(iu: str) -> str:
    return f"③{iu}.md"


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def norm(p: str | os.PathLike) -> str:
    """比較用に正規化した絶対パス（大文字小文字と区切り文字を吸収する）。"""
    return os.path.normcase(os.path.abspath(str(p)))


def is_under(path: str | os.PathLike, base: str | os.PathLike) -> bool:
    p, b = norm(path), norm(base)
    try:
        return os.path.commonpath([p, b]) == b
    except ValueError:  # 別ドライブ
        return False


# ---------------------------------------------------------------- 設定
def load_config() -> dict:
    """config/project.md の `key: value` 行を読む。"""
    cfg = {"source_root": "", "exclude": []}
    path = root() / "config" / "project.md"
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(source_root|exclude)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == "exclude":
            cfg["exclude"] = [v.strip() for v in val.split(",") if v.strip()]
        else:
            cfg[key] = val
    return cfg


def source_root() -> Path | None:
    sr = load_config().get("source_root")
    return Path(sr) if sr else None


# ---------------------------------------------------------------- 実行中コンテキスト
def current_path() -> Path:
    return work_dir() / ".current.json"


def load_current() -> dict:
    p = current_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_current(data: dict) -> None:
    p = current_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


CURRENT_TTL_HOURS = 3


def active_current() -> dict:
    """実行中（gate.py check を通り、完了処理がまだ）のステップ。古すぎるもの・完了済みは {}。"""
    cur = load_current()
    if not cur or cur.get("finished"):
        return {}
    try:
        started = _dt.datetime.fromisoformat(cur.get("started", ""))
    except ValueError:
        return {}
    if _dt.datetime.now() - started > _dt.timedelta(hours=CURRENT_TTL_HOURS):
        return {}
    return cur


# ---------------------------------------------------------------- 状態ファイル
GATE_STATES = {
    "not_started": "未着手",
    "drafted": "AI作成済み（レビュー待ち）",
    "review_ng": "レビューNG（修正待ち）",
    "review_ok": "承認待ち",
    "escalated": "AIレビュー上限到達（人の判断待ち）",
    "blocked_q": "中断（質問の回答待ち）",
    "format_error": "形式エラー（人の確認が必要）",
    "approved": "承認済み",
}

MAX_REVIEW_ROUNDS = 2


def status_path(feature: str) -> Path:
    return feature_dir(feature) / "status.json"


def load_status(feature: str) -> dict:
    p = status_path(feature)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"feature": feature, "gates": {}, "history": []}


def save_status(feature: str, st: dict) -> None:
    p = status_path(feature)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def gate_of(st: dict, gate: str) -> dict:
    return st["gates"].setdefault(
        gate, {"state": "not_started", "rounds": 0, "human_rejects": 0}
    )


def record(st: dict, gate: str, event: str, by: str, note: str = "") -> None:
    st.setdefault("history", []).append(
        {"ts": now(), "gate": gate, "event": event, "by": by, "note": note}
    )


# ---------------------------------------------------------------- 参照書式
CELL_RE = r"[A-Z]{1,3}[0-9]{1,7}"
DOC_REF_RE = re.compile(
    r"\[設計書:\s*(?P<book>[^/\]]+?)\s*/\s*(?P<sheet>[^!\]]+?)\s*!\s*"
    r"(?P<range>" + CELL_RE + r"(?::" + CELL_RE + r")?)\s*\]"
)
SRC_REF_RE = re.compile(r"\[ソース:\s*(?P<path>[^\]]+?):(?P<start>\d+)(?:-(?P<end>\d+))?\s*\]")
POLICY_REF_RE = re.compile(r"\[方針:\s*(?P<file>[^\]#]+?)\s*(?:#[^\]]*)?\]")
REQ_RE = re.compile(r"\bREQ-\d{2,}\b")
IU_RE = re.compile(r"\bIU-\d{2,}\b")
Q_RE = re.compile(r"\bQ-\d{2,}\b")


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_cell(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]{1,3})([0-9]+)", ref.strip().upper())
    if not m:
        raise ValueError(f"セル番地の形式が不正です: {ref}")
    return int(m.group(2)), col_to_num(m.group(1))


def parse_range(rng: str) -> tuple[int, int, int, int]:
    """'A1:C3' または 'B2' を (min_row, min_col, max_row, max_col) にする。"""
    parts = rng.strip().upper().split(":")
    if len(parts) == 1:
        r, c = parse_cell(parts[0])
        return r, c, r, c
    r1, c1 = parse_cell(parts[0])
    r2, c2 = parse_cell(parts[1])
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def range_within(inner: str, outer: str) -> bool:
    a = parse_range(inner)
    b = parse_range(outer)
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def ranges_intersect(a: tuple, b: tuple) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


# ---------------------------------------------------------------- Markdown 表
def md_tables(text: str) -> list[list[list[str]]]:
    """Markdown 中の表を [表][行][列] で返す（見出し行を含み、区切り行は除く）。"""
    tables, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) > 1:
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", s[1:-1])]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            cur.append(cells)
        else:
            if cur:
                tables.append(cur)
                cur = []
    if cur:
        tables.append(cur)
    return tables


def section(text: str, heading: str) -> str:
    """'## 見出し' から次の同レベル以上の見出しまでの本文を返す。無ければ ''。"""
    lines = text.splitlines()
    out, level, inside = [], 0, False
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            if inside and len(m.group(1)) <= level:
                break
            if not inside and m.group(2).startswith(heading):
                inside, level = True, len(m.group(1))
                continue
        if inside:
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 指示書
def load_instruction(feature: str) -> list[dict]:
    """00_instruction.md の『対象範囲』表を読む。"""
    p = feature_dir(feature) / "00_instruction.md"
    if not p.exists():
        return []
    body = section(p.read_text(encoding="utf-8"), "対象範囲")
    rows = []
    for tbl in md_tables(body):
        for cells in tbl[1:]:
            if len(cells) < 3 or not cells[0] or not cells[1] or not cells[2]:
                continue
            for rng in re.split(r"[,、\s]+", cells[2]):
                if rng:
                    rows.append(
                        {
                            "book": cells[0],
                            "sheet": cells[1],
                            "range": rng.upper(),
                            "note": cells[3] if len(cells) > 3 else "",
                        }
                    )
    return rows


# ---------------------------------------------------------------- 計画書の IU
def load_plan_units(feature: str) -> dict[str, dict]:
    """②実装計画.md から IU ごとの情報（対象ファイル、AI実装可否、順序）を読む。"""
    p = feature_dir(feature) / HUMAN_DOC_PLAN
    units: dict[str, dict] = {}
    if not p.exists():
        return units
    text = p.read_text(encoding="utf-8")
    trace = section(text, "実装単位一覧")
    for tbl in md_tables(trace):
        head = tbl[0]
        if not head or not head[0].startswith("IU"):
            continue
        idx_ai = next((i for i, h in enumerate(head) if "AI実装可否" in h), None)
        idx_req = next((i for i, h in enumerate(head) if h.startswith("REQ")), None)
        for order, cells in enumerate(tbl[1:]):
            m = IU_RE.search(cells[0]) if cells else None
            if not m:
                continue
            u = units.setdefault(m.group(0), {"files": [], "order": order})
            u["order"] = order
            if idx_ai is not None and idx_ai < len(cells):
                u["ai"] = cells[idx_ai].strip()
            if idx_req is not None and idx_req < len(cells):
                u["reqs"] = REQ_RE.findall(cells[idx_req])
    detail = section(text, "IU詳細")
    cur = None
    in_files = False
    for line in detail.splitlines():
        m = re.match(r"^###\s+(IU-\d{2,})", line)
        if m:
            cur = units.setdefault(m.group(1), {"files": [], "order": len(units)})
            in_files = False
            continue
        if cur is None:
            continue
        if re.match(r"^\s*-\s*対象ファイル", line):
            in_files = True
            continue
        if in_files:
            fm = re.match(r"^\s+-\s*`([^`]+)`", line)
            if fm:
                cur["files"].append(fm.group(1).strip())
                continue
            if re.match(r"^\s*-\s", line) or line.strip() == "":
                in_files = False
    return units


# ---------------------------------------------------------------- ③の変更前スナップショットと累積差分
def unit_dir(feature: str, iu: str) -> Path:
    return feature_dir(feature) / "_ai" / iu


def rel_to_source(p: Path) -> str:
    """ソースルートからの相対パス（表記の大文字小文字は元のまま）。"""
    sr = source_root()
    if sr is None or not is_under(p, sr):
        return Path(p).as_posix()
    ap, asr = os.path.abspath(str(p)), os.path.abspath(str(sr))
    return Path(ap[len(asr):].lstrip("\\/")).as_posix()


def read_lines(p: Path) -> list[str]:
    if not p.exists():
        return []
    data = p.read_bytes()
    for enc in ("utf-8", "cp932"):
        try:
            return data.decode(enc).splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").splitlines(keepends=True)


def snapshot_before(path: Path, feature: str, iu: str) -> None:
    """IU で初めて触るファイルの元の内容を保存する（存在しないファイルは新規として記録）。"""
    d = unit_dir(feature, iu)
    rel = rel_to_source(path)
    before = d / "before" / rel
    marker = d / "before" / (rel + ".new")
    if before.exists() or marker.exists():
        return
    before.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, before)
    else:
        marker.write_text("", encoding="utf-8")
    last = d / "last" / rel
    last.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, last)


def snapshot_unit_files(feature: str, iu: str) -> None:
    """IU の対象ファイルをすべて、変更前の状態として保存する（gate.py check implement-unit が呼ぶ）。"""
    sr = source_root()
    if sr is None:
        return
    u = load_plan_units(feature).get(iu) or {}
    for f in u.get("files", []):
        snapshot_before(sr / f, feature, iu)


def rebuild_cumulative(feature: str, iu: str) -> int:
    """IU 開始前からの累積差分を diff.md に作り直す。差分のあるファイル数を返す。"""
    d = unit_dir(feature, iu)
    base = d / "before"
    sr = source_root()
    parts = [f"# 累積差分 {iu}（IU 開始前 → 現在。ツールが自動で作成。手で編集しない）\n"]
    changed = 0
    if base.exists() and sr is not None:
        for f in sorted(base.rglob("*")):
            if f.is_dir():
                continue
            if f.name.endswith(".new"):
                rel = f.relative_to(base).as_posix()[:-4]
                old = []
            else:
                rel = f.relative_to(base).as_posix()
                old = read_lines(f)
            new = read_lines(sr / rel)
            diff = "".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", n=3))
            if diff:
                changed += 1
            parts.append(f"\n## `{rel}`{'（新規）' if not old else ''}\n```diff\n{diff or '（差分なし）'}\n```\n")
    d.mkdir(parents=True, exist_ok=True)
    (d / "diff.md").write_text("".join(parts), encoding="utf-8")
    return changed
