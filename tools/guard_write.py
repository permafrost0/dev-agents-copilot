"""PreToolUse / PostToolUse フック（GitHub Copilot / VS Code 用）：書き込み先とターミナルを制限し、③の編集内容を記録する。

呼ばれ方は2通り。
- エージェント定義（.github/agents/*.agent.md）の hooks から:  python tools/guard_write.py --role <エージェント名> [--post]
- ワークスペース全体のフック（.github/hooks/guard.json）から:    python tools/guard_write.py --role auto
  auto のときは、実行中のステップ（work/.current.json。gate.py check が作り、完了処理で閉じる）の
  エージェントとして扱う。実行中のステップがなければ、全員共通の禁止事項だけを確かめる。

VS Code のフックの入力（標準入力の JSON）には、どのエージェントの操作かが入らないため、役割は引数で受け取る。
また、ツール名と引数の形は VS Code のバージョンで変わりうるため、名前のパターンと引数の中身から判定する。

- 全員（人が操作するチャットも含む）: input/、*.xlsx 等、状態ファイルへの書き込みを禁止
- 専属エージェント: 書き込み先を役割ごとに限定し、ターミナルは許可したスクリプトだけにする
- implementer: ②実装計画.md の対象 IU に書かれたファイルだけ書き込める。
  PostToolUse で編集内容を _ai/IU-xx/edits.md に記録し、累積差分 diff.md を作り直す
- 人が読むドキュメントを上書きする前に、旧版を _ai/history/ に退避する（質問の回答の消失検知に使う）

ブロックするときは終了コード 2 で終わり、理由を標準エラーに出す。
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

PROTECTED_SUFFIXES = {".xlsx", ".xls", ".xlsm"}

# ツール名の判定（VS Code の内部名・表示名のどちらでも当たるように、パターンで見る）
TERMINAL_TOOL_RE = re.compile(r"terminal|bash|shell|powershell|run_?task|runtask|execute|command", re.I)
READ_TOOL_RE = re.compile(r"read|get|search|list|find|fetch|view|usages|problems|summary|todo", re.I)
WRITE_TOOL_RE = re.compile(r"edit|create|replace|insert|patch|write|notebook|delete|remove|rename|move", re.I)
# 引数のうちパスを表すキー
PATH_KEYS = {"filepath", "file_path", "path", "notebook_path", "notebookpath", "uri", "dirpath", "dir_path", "target_file"}
PATCH_FILE_RE = re.compile(r"^\*\*\*\s*(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$", re.M)

# 役割 → 書き込みを許す場所（'feature' は work/<機能名>/、'knowledge' は knowledge/）
WRITE_SCOPE = {
    "project-profiler": {"knowledge", "profile"},
    "profile-reviewer": {"profile"},
    "spec-reader": {"feature"},
    "source-investigator": {"feature"},
    "alignment-reviewer": {"feature"},
    "impl-planner": {"feature"},
    "plan-reviewer": {"feature"},
    "implementer": {"feature", "unit_files"},
    "diff-reviewer": {"feature"},
    "knowledge-curator": {"feature", "knowledge", "checklists"},
}
# 役割 → 担当ステップ（gate.py check で指定してよいステップ）
ROLE_STEP = {
    "project-profiler": "project-profile",
    "profile-reviewer": "profile-review",
    "spec-reader": "spec-extract",
    "source-investigator": "current-survey",
    "alignment-reviewer": "alignment-review",
    "impl-planner": "impl-plan",
    "plan-reviewer": "plan-review",
    "implementer": "implement-unit",
    "diff-reviewer": "diff-review",
    "knowledge-curator": "retrospect",
}
# レビュー役は作成役の成果物を書き換えない（指摘のみ）
REVIEWER_FORBIDDEN = {
    "alignment-reviewer": {"01_requirements.md", "02_current_spec.md"},
    "plan-reviewer": {"②実装計画.md"},
    "diff-reviewer": {"impl.md"},
}
# 役割 → 担当ステップ以外に実行してよいスクリプト
EXTRA_SCRIPTS = {
    "spec-reader": {"xlsx_dump.py"},
    "alignment-reviewer": {"xlsx_dump.py"},
    "knowledge-curator": {"metrics.py"},
}
HUMAN_DOCS = re.compile(r"^(①認識合わせ|②実装計画|③IU-\d{2,}|⓪プロファイル確認)\.md$")
CMD_RE = re.compile(
    r"(?:python3?|py(?:\s+-3)?)(?:\.exe)?\s+[\"']?(?:\.[/\\])?tools[/\\](?P<s>[\w.]+\.py)[\"']?(?P<args>(?:\s+.*)?)",
    re.S,
)


def block(msg: str) -> None:
    print(f"【ガード】{msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- 入力の解釈
def tool_kind(tool: str) -> str:
    if TERMINAL_TOOL_RE.search(tool) and not re.search(r"output|last|selection", tool, re.I):
        return "terminal"
    if WRITE_TOOL_RE.search(tool) and not READ_TOOL_RE.search(tool):
        return "write"
    return "other"


def _collect_paths(obj, out: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k.lower() in PATH_KEYS:
                out.append(v)
            elif isinstance(v, list) and k.lower() in {"filepaths", "files", "paths"}:
                out.extend(x for x in v if isinstance(x, str))
            else:
                _collect_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_paths(v, out)
    elif isinstance(obj, str):
        out.extend(m.group(1) for m in PATCH_FILE_RE.finditer(obj))


def target_paths(tool_input: dict, cwd: str | None) -> list[Path]:
    raw: list[str] = []
    _collect_paths(tool_input, raw)
    out = []
    for s in raw:
        s = s.strip()
        if s.startswith("file://"):
            from urllib.parse import unquote, urlparse
            u = urlparse(s)
            s = unquote(u.path)
            if re.match(r"^/[A-Za-z]:", s):  # file:///C:/... → C:/...
                s = s[1:]
        p = Path(s)
        if not p.is_absolute():
            p = Path(cwd or C.root()) / p
        out.append(p)
    return out


def command_of(tool_input: dict) -> str:
    for k in ("command", "commandLine", "cmd", "script"):
        v = tool_input.get(k)
        if isinstance(v, str):
            return v
    return ""


def resolve_role(arg: str) -> tuple[str, dict]:
    """役割と、その役割で有効な実行中コンテキストを返す。"""
    cur = C.active_current()
    if arg == "auto":
        return (cur.get("agent") or ""), cur
    # エージェント定義からの呼び出し: 実行中のステップが自分のものなら、そのコンテキストを使う
    if cur.get("agent") == arg:
        return arg, cur
    return arg, {}


# ---------------------------------------------------------------- 判定
def allowed_dirs(role: str, cur: dict) -> list[Path]:
    scope = WRITE_SCOPE.get(role, set())
    dirs = []
    feature = cur.get("feature")
    if "feature" in scope and feature:
        dirs.append(C.feature_dir(feature))
    if "profile" in scope:
        dirs.append(C.feature_dir(C.PROFILE_FEATURE))
    if "knowledge" in scope:
        dirs.append(C.knowledge_dir())
    return dirs


def unit_files(cur: dict) -> list[Path]:
    sr = C.source_root()
    feature, iu = cur.get("feature"), cur.get("iu")
    if not (sr and feature and iu):
        return []
    u = C.load_plan_units(feature).get(iu)
    return [sr / f for f in (u or {}).get("files", [])]


def check_common(p: Path) -> None:
    if C.is_under(p, C.root() / "input"):
        block(f"input/ 配下は読み取り専用です: {p.name}")
    if p.suffix.lower() in PROTECTED_SUFFIXES:
        block(f"設計書（Excel）は書き換えられません: {p.name}")
    if p.name in ("status.json", ".current.json", ".last_gate.json") and C.is_under(p, C.work_dir()):
        block("状態ファイルは gate.py / check_artifact.py だけが更新します")
    if C.is_under(p, C.root() / "tools"):
        block("tools/ 配下は書き換えられません")


def check_terminal(role: str, command: str, auto: bool = False) -> None:
    command = re.sub(r"^\s*&\s*", "", command.strip())  # PowerShell の呼び出し演算子は許す
    if re.search(r"[;&|<>`\r\n]|\$\(", command):
        block("コマンドの連結・リダイレクト・置換は使えません。スクリプトを1つずつ、そのまま実行してください")
    m = CMD_RE.fullmatch(command)
    if not m:
        block(f"{role} がターミナルで実行できるのは tools/ のスクリプトだけです: {command[:80]}")
    script, args = m.group("s"), [a.strip("\"'") for a in (m.group("args") or "").split()]
    sub = args[0] if args else ""
    # 全員: 状態の確認と完了処理
    if script == "gate.py" and sub in ("status", "next"):
        return
    if script == "check_artifact.py" and sub == "--finish":
        return
    # 担当ステップのゲート判定
    if script == "gate.py" and sub == "check":
        step = args[1] if len(args) > 1 else ""
        if step != ROLE_STEP.get(role) and not auto:
            block(f"{role} が実行できるゲート判定は `gate.py check {ROLE_STEP.get(role)} …` だけです")
        return
    if script in EXTRA_SCRIPTS.get(role, set()):
        return
    if script == "gate.py" and sub in ("approve", "reject", "reopen", "cancel"):
        block("承認・差し戻し・やり直しは人が行う操作です。AI は実行できません")
    allowed = ["gate.py check " + ROLE_STEP.get(role, "?"), "check_artifact.py --finish", *sorted(EXTRA_SCRIPTS.get(role, set()))]
    block(f"{role} が実行できるのは {', '.join(allowed)} だけです: {command[:80]}")


def backup_human_doc(path: Path, cur: dict) -> None:
    if path.exists() and HUMAN_DOCS.match(path.name):
        hist = C.feature_dir(cur.get("feature") or "_unknown") / "_ai" / "history"
        hist.mkdir(parents=True, exist_ok=True)
        stamp = C.now().replace(":", "")
        shutil.copy2(path, hist / f"{path.stem}.{stamp}{path.suffix}")


def check_write(role: str, cur: dict, paths: list[Path]) -> None:
    for p in paths:
        check_common(p)
    if role not in WRITE_SCOPE:
        return  # 人が操作するチャット・進行役は、共通の禁止事項だけ
    if not cur:
        block(
            f"{role} の作業が始まっていません。最初に `python tools/gate.py check {ROLE_STEP[role]} …` を実行し、"
            "ゲート判定 OK を確認してから書き込んでください"
        )
    if not paths:
        block("書き込み先のファイルを判定できませんでした。ファイルの作成・編集のツールでパスを指定してください")
    dirs = allowed_dirs(role, cur)
    files = unit_files(cur) if "unit_files" in WRITE_SCOPE[role] else []
    for p in paths:
        s = str(p)
        if re.search(r"[/\\]_ai[/\\]IU-\d{2,}[/\\](before|last)[/\\]", s) or (
            p.name in ("edits.md", "diff.md") and C.is_under(p, C.work_dir())
        ):
            block("編集記録（edits.md / diff.md / before / last）はツールだけが作成します")
        if p.name in REVIEWER_FORBIDDEN.get(role, set()):
            block(f"{role} は作成役の成果物（{p.name}）を書き換えられません。指摘はレビュー結果に書いてください")
        in_dir = any(C.is_under(p, d) for d in dirs)
        in_files = any(C.norm(p) == C.norm(f) for f in files)
        if "checklists" in WRITE_SCOPE[role] and p.name == "checklist.md" and C.is_under(p, C.root() / ".github" / "steps"):
            in_dir = True
        if not (in_dir or in_files):
            where = [d.relative_to(C.root()).as_posix() + "/" for d in dirs]
            if files:
                where.append(f"{cur.get('iu')} の対象ファイル")
            block(
                f"{role} はここに書き込めません: {p}\n許可されている書き込み先: {', '.join(where) or 'なし'}\n"
                "範囲外の変更が必要な場合は、作業を中断して質問（Q）を起票してください"
            )
        if in_dir:
            backup_human_doc(p, cur)
        if in_files:
            C.snapshot_before(p, cur["feature"], cur["iu"])


# ---------------------------------------------------------------- ③の編集記録
def log_edit(path: Path, tool: str, cur: dict) -> None:
    d = C.unit_dir(cur["feature"], cur["iu"])
    rel = C.rel_to_source(path)
    last = d / "last" / rel
    old = C.read_lines(last)
    new = C.read_lines(path)
    diff = "".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", n=2))
    log = d / "edits.md"
    if not log.exists():
        log.write_text(f"# 編集記録 {cur['iu']}（フックが自動で記録。手で編集しない）\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n## {C.now()} {tool} `{rel}`\n```diff\n{diff or '（差分なし）'}\n```\n")
    last.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, last)
    C.rebuild_cumulative(cur["feature"], cur["iu"])


# ---------------------------------------------------------------- 入口
def pre(data: dict, role_arg: str) -> None:
    tool = str(data.get("tool_name", ""))
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {"input": ti}
    role, cur = resolve_role(role_arg)
    kind = tool_kind(tool)
    if kind == "write":
        check_write(role, cur, target_paths(ti, data.get("cwd")))
    elif kind == "terminal":
        if role in WRITE_SCOPE:
            # auto（実行中のステップから推定した役割）のときは、別のステップの開始（gate.py check）も許す
            check_terminal(role, command_of(ti), auto=(role_arg == "auto"))
    else:
        # 名前で判定できないツールでも、引数に書き込み先らしいパスがあれば共通の禁止事項は確かめる
        if re.search(r"(content|newString|new_string|edits|replacements)", json.dumps(ti, ensure_ascii=False), re.I):
            for p in target_paths(ti, data.get("cwd")):
                check_common(p)


def post(data: dict, role_arg: str) -> None:
    tool = str(data.get("tool_name", ""))
    role, cur = resolve_role(role_arg)
    if role != "implementer" or tool_kind(tool) != "write" or not cur.get("iu"):
        return
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {"input": ti}
    files = unit_files(cur)
    for p in target_paths(ti, data.get("cwd")):
        if any(C.norm(p) == C.norm(f) for f in files):
            log_edit(p, tool, cur)


def main() -> int:
    argv = sys.argv[1:]
    role = "auto"
    if "--role" in argv:
        i = argv.index("--role")
        role = argv[i + 1] if i + 1 < len(argv) else "auto"
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return 0
    if "--post" in argv:
        post(data, role)
    else:
        pre(data, role)
    return 0


if __name__ == "__main__":
    sys.exit(main())
