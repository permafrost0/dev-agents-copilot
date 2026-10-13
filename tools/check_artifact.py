"""成果物の形式チェックと、状態（status.json）の更新。

- 完了処理として（エージェントが作業の最後に実行する）:
    python tools/check_artifact.py --finish
    実行中のステップ（work/.current.json）の成果物を検査する。不正なら理由を表示して終了コード 1 で終わる
    （直して再実行する。3回を超えたら形式エラーとして人に回す）。
    正しければ、ゲートの状態を更新する（作成役 → AI作成済み、レビュー役 → 判定に応じて承認待ち／NG）。
- フックとして（.github/agents/*.agent.md の hooks の Stop。サブエージェントとして動くときは SubagentStop として扱われる）:
    python tools/check_artifact.py --hook --agent <エージェント名>
    完了処理をしないまま終わろうとしたときの安全網。--finish と同じ検査をし、不正なら終了コード 2 で止める。
- コマンドとして:
    python tools/check_artifact.py <ステップ> <機能名> [IU-xx]   （検査結果だけを表示し、状態は変えない）
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402
from gate import STEPS, AGENT_TO_STEP  # noqa: E402

MAX_STOP_BLOCKS = 3
REQ_KINDS = {"画面項目", "イベント", "処理", "メッセージ", "設定", "その他"}
FINDING_KINDS_UNIT = {"範囲外", "仕様不一致", "規約違反", "共通部品未使用"}
VERDICT_RE = re.compile(r"判定[ \t]*[:：][ \t]*\**[ \t]*(OK|NG)\b")


# ---------------------------------------------------------------- 参照の検証
_sheet_cache: dict[str, set[str]] = {}


def sheet_names(book: str) -> set[str] | None:
    p = C.design_doc_dir() / book
    if not p.is_file():
        return None
    if book not in _sheet_cache:
        with zipfile.ZipFile(p) as z:
            xml = z.read("xl/workbook.xml").decode("utf-8")
        names = re.findall(r'<sheet\b[^>]*\bname="([^"]+)"', xml)
        import html
        _sheet_cache[book] = {html.unescape(n) for n in names}
    return _sheet_cache[book]


def check_doc_refs(text: str, feature: str, where: str, within_instruction: bool = True) -> list[str]:
    errs = []
    inst = C.load_instruction(feature) if within_instruction else []
    for m in C.DOC_REF_RE.finditer(text):
        book, sheet, rng = m.group("book"), m.group("sheet"), m.group("range")
        names = sheet_names(book)
        if names is None:
            errs.append(f"{where}: 設計書が input/設計書/ 直下にありません: {m.group(0)}")
            continue
        if sheet not in names:
            errs.append(f"{where}: シートが存在しません: {m.group(0)}")
            continue
        if within_instruction:
            ok = any(
                r["book"] == book and r["sheet"] == sheet and C.range_within(rng, r["range"])
                for r in inst
            )
            if not ok:
                errs.append(f"{where}: 指示された対象範囲の外を参照しています: {m.group(0)}")
    return errs


_line_cache: dict[str, int] = {}


def count_lines(p: Path) -> int:
    key = str(p)
    if key not in _line_cache:
        data = p.read_bytes()
        _line_cache[key] = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
    return _line_cache[key]


def check_src_refs(text: str, where: str) -> list[str]:
    errs = []
    sr = C.source_root()
    for m in C.SRC_REF_RE.finditer(text):
        rel = m.group("path").strip().strip("`")
        p = (sr / rel) if sr else Path(rel)
        if not p.is_file():
            errs.append(f"{where}: ソースが存在しません（ソースルートからの相対パスで書く）: {m.group(0)}")
            continue
        start = int(m.group("start"))
        end = int(m.group("end") or start)
        n = count_lines(p)
        if start < 1 or end < start or end > n:
            errs.append(f"{where}: 行番号がファイルの範囲外です（全 {n} 行）: {m.group(0)}")
    return errs


def check_policy_refs(text: str, where: str) -> list[str]:
    errs = []
    for m in C.POLICY_REF_RE.finditer(text):
        name = m.group("file").strip()
        if not (C.policy_doc_dir() / name).exists():
            errs.append(f"{where}: 設計方針ドキュメントが input/設計方針/ にありません: {m.group(0)}")
    return errs


def read(p: Path) -> str | None:
    return p.read_text(encoding="utf-8") if p.exists() else None


def req_sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(REQ-\d{2,})\b", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1), []
        elif re.match(r"^##\s", line):
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = None, []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def requirement_ids(feature: str) -> list[str]:
    t = read(C.feature_dir(feature) / "_ai" / "01_requirements.md") or ""
    return list(req_sections(t).keys())


def need_sections(text: str, names: list[str], where: str) -> list[str]:
    errs = []
    for n in names:
        if not re.search(r"^#{1,4}\s+" + re.escape(n), text, re.M):
            errs.append(f"{where}: 見出し『{n}』がありません（output-template.md の形式に従う）")
    return errs


def verdict(text: str) -> str | None:
    m = VERDICT_RE.search(text)
    return m.group(1) if m else None


def answers(text: str) -> dict[str, str]:
    out = {}
    for tbl in C.md_tables(C.section(text, "質問")):
        idx = next((i for i, h in enumerate(tbl[0]) if "回答" in h), None)
        if idx is None:
            continue
        for cells in tbl[1:]:
            m = C.Q_RE.search(cells[0]) if cells else None
            if m and idx < len(cells) and cells[idx] not in ("", "-", "－", "未回答"):
                out[m.group(0)] = cells[idx]
    return out


def check_answers_kept(doc: Path, feature: str) -> list[str]:
    """人が書いた質問の回答が、AI の再作成で消えていないか（直前の旧版と比べる）。"""
    hist = C.feature_dir(feature) / "_ai" / "history"
    olds = sorted(hist.glob(f"{doc.stem}.*{doc.suffix}")) if hist.exists() else []
    if not olds or not doc.exists():
        return []
    before = answers(olds[-1].read_text(encoding="utf-8"))
    after = answers(doc.read_text(encoding="utf-8"))
    return [
        f"{doc.name}: 人が記入した {q} の回答が消えたか変わっています（回答欄は人のものなので、そのまま残す）"
        for q, a in before.items()
        if after.get(q) != a
    ]


def check_review_file(p: Path, kinds: set[str] | None = None) -> list[str]:
    t = read(p)
    if t is None:
        return [f"{p.name} がありません"]
    errs = []
    v = verdict(t)
    if v is None:
        errs.append(f"{p.name}: 『判定: OK』か『判定: NG』の行がありません")
    rows = [r for tbl in C.md_tables(C.section(t, "指摘")) for r in tbl[1:] if any(r)]
    if v == "NG" and not rows:
        errs.append(f"{p.name}: 判定が NG なのに『指摘』表に行がありません")
    for r in rows:
        if len(r) < 4 or not r[3]:
            errs.append(f"{p.name}: 指摘には根拠（セル番地・path:line・規約の該当箇所）が必要です: {' | '.join(r)[:60]}")
        if kinds and len(r) > 1 and r[1] not in kinds:
            errs.append(f"{p.name}: 指摘の種別は {'/'.join(sorted(kinds))} のいずれかです: {r[1]}")
    return errs


# ---------------------------------------------------------------- ステップ別の検査
def v_project_profile(feature, iu, mode):
    errs = []
    k = C.knowledge_dir()
    prof, comp = read(k / "project_profile.md"), read(k / "common_components.md")
    if prof is None or comp is None:
        return ["knowledge/project_profile.md と common_components.md を作成してください"]
    errs += need_sections(prof, ["技術構成", "レイヤー構成", "トランザクション", "例外処理", "入力チェック",
                                 "メッセージ", "ログ", "命名規則"], "project_profile.md")
    nref = len(C.SRC_REF_RE.findall(prof)) + len(C.POLICY_REF_RE.findall(prof))
    if nref < 5:
        errs.append("project_profile.md: 根拠（[ソース: …] / [方針: …]）が少なすぎます（各項目に付ける）")
    errs += check_src_refs(prof, "project_profile.md") + check_policy_refs(prof, "project_profile.md")
    rows = [r for tbl in C.md_tables(comp) for r in tbl[1:]]
    for r in rows:
        if not C.SRC_REF_RE.search(" ".join(r)):
            errs.append(f"common_components.md: 場所の根拠 [ソース: …] がない行があります: {r[0]}")
    errs += check_src_refs(comp, "common_components.md")
    return errs


def v_profile_review(feature, iu, mode):
    fdir = C.feature_dir(C.PROFILE_FEATURE)
    errs = check_review_file(fdir / "_ai" / "review.md")
    doc = read(fdir / C.HUMAN_DOC_PROFILE)
    if doc is None:
        return errs + [f"{C.HUMAN_DOC_PROFILE} を作成してください"]
    errs += need_sections(doc, ["AIレビュー結果", "承認"], C.HUMAN_DOC_PROFILE)
    return errs


def v_spec_extract(feature, iu, mode):
    fdir = C.feature_dir(feature)
    p = fdir / "_ai" / "01_requirements.md"
    t = read(p)
    if t is None:
        return ["_ai/01_requirements.md を作成してください"]
    errs = []
    if not list((fdir / "_ai" / "extract").glob("*.md")):
        errs.append("_ai/extract/ に抽出結果がありません（python tools/xlsx_dump.py --feature を実行する）")
    secs = req_sections(t)
    if not secs:
        errs.append("01_requirements.md: 『## REQ-01』形式の要件がありません")
    for rid, body in secs.items():
        m = re.search(r"-[ \t]*種別[ \t]*[:：][ \t]*(\S+)", body)
        if not m or m.group(1) not in REQ_KINDS:
            errs.append(f"{rid}: 種別は {'/'.join(sorted(REQ_KINDS))} のいずれかです")
        if not re.search(r"-[ \t]*区分[ \t]*[:：][ \t]*(新規|既存変更|不明)", body):
            errs.append(f"{rid}: 区分（新規／既存変更／不明）がありません")
        if not C.DOC_REF_RE.search(body):
            errs.append(f"{rid}: 根拠 [設計書: ブック/シート!セル] がありません")
        if not re.search(r"-[ \t]*原文[ \t]*[:：][ \t]*\S", body):
            errs.append(f"{rid}: 原文の引用がありません")
    errs += check_doc_refs(t, feature, "01_requirements.md")
    return errs


def v_current_survey(feature, iu, mode):
    t = read(C.feature_dir(feature) / "_ai" / "02_current_spec.md")
    if t is None:
        return ["_ai/02_current_spec.md を作成してください"]
    errs = need_sections(t, ["技術構成", "調査したファイル"], "02_current_spec.md")
    secs = req_sections(t)
    for rid in requirement_ids(feature):
        if rid not in secs:
            errs.append(f"02_current_spec.md: {rid} の節がありません")
        elif not C.SRC_REF_RE.search(secs[rid]) and "該当なし" not in secs[rid]:
            errs.append(f"02_current_spec.md: {rid} に現行ソースの根拠 [ソース: path:line] がありません"
                        "（新規で該当がなければ『該当なし』と理由を書く）")
    errs += check_src_refs(t, "02_current_spec.md") + check_doc_refs(t, feature, "02_current_spec.md")
    return errs


def v_alignment_review(feature, iu, mode):
    fdir = C.feature_dir(feature)
    errs = check_review_file(fdir / "_ai" / "review_①.md")
    doc_p = fdir / C.HUMAN_DOC_ALIGNMENT
    t = read(doc_p)
    if t is None:
        return errs + [f"{C.HUMAN_DOC_ALIGNMENT} を作成してください"]
    errs += need_sections(t, ["要件一覧", "対象外", "質問", "差異", "AIレビュー結果", "承認"], C.HUMAN_DOC_ALIGNMENT)
    body = C.section(t, "要件一覧")
    for rid in requirement_ids(feature):
        if rid not in body:
            errs.append(f"{C.HUMAN_DOC_ALIGNMENT}: 要件一覧に {rid} がありません")
    if not re.search(r"-\s*\[[ xX]\]\s*承認", C.section(t, "承認")):
        errs.append(f"{C.HUMAN_DOC_ALIGNMENT}: 承認欄に `- [ ] 承認` がありません")
    qt = C.md_tables(C.section(t, "質問"))
    if qt and not any("回答" in h for h in qt[0][0]):
        errs.append(f"{C.HUMAN_DOC_ALIGNMENT}: 質問の表に『回答』列がありません")
    errs += check_doc_refs(t, feature, C.HUMAN_DOC_ALIGNMENT) + check_src_refs(t, C.HUMAN_DOC_ALIGNMENT)
    errs += check_answers_kept(doc_p, feature)
    return errs


def v_impl_plan(feature, iu, mode):
    fdir = C.feature_dir(feature)
    doc_p = fdir / C.HUMAN_DOC_PLAN
    t = read(doc_p)
    if t is None:
        return [f"{C.HUMAN_DOC_PLAN} を作成してください"]
    errs = need_sections(t, ["実装単位一覧", "IU詳細", "質問", "承認"], C.HUMAN_DOC_PLAN)
    trace = C.md_tables(C.section(t, "実装単位一覧"))
    if not trace:
        return errs + [f"{C.HUMAN_DOC_PLAN}: 実装単位一覧（トレース表）がありません"]
    head = trace[0][0]
    need_cols = ["IU", "REQ", "設計書の場所", "実装予定の箇所", "再利用する共通部品", "参照実装", "新規/変更", "AI実装可否"]
    for col in need_cols:
        if not any(h.startswith(col) for h in head):
            errs.append(f"{C.HUMAN_DOC_PLAN}: トレース表に『{col}』列がありません")
    if errs:
        return errs
    ix = {col: next(i for i, h in enumerate(head) if h.startswith(col)) for col in need_cols}
    covered = set()
    for r in trace[0][1:]:
        if not r or not C.IU_RE.search(r[0]):
            continue
        uid = C.IU_RE.search(r[0]).group(0)
        cell = lambda col: r[ix[col]] if ix[col] < len(r) else ""  # noqa: E731
        covered |= set(C.REQ_RE.findall(cell("REQ")))
        ai = cell("AI実装可否")
        if ai not in ("可", "要人判断"):
            errs.append(f"{uid}: AI実装可否は『可』か『要人判断』です（現在: {ai or '空'}）")
        if not C.DOC_REF_RE.search(cell("設計書の場所")):
            errs.append(f"{uid}: 設計書の場所 [設計書: …] がありません")
        if ai == "可":
            if not C.SRC_REF_RE.search(cell("参照実装")):
                errs.append(f"{uid}: 参照実装 [ソース: path:line] がありません")
            reuse = cell("再利用する共通部品")
            if not (C.SRC_REF_RE.search(reuse) or reuse.startswith("なし")):
                errs.append(f"{uid}: 再利用する共通部品は [ソース: …] か『なし（理由）』で書きます")
    for rid in requirement_ids(feature):
        if rid not in covered:
            errs.append(f"{C.HUMAN_DOC_PLAN}: {rid} がどの IU にも割り当てられていません")
    units = C.load_plan_units(feature)
    sr = C.source_root()
    for uid, u in units.items():
        if not u["files"]:
            errs.append(f"{uid}: IU詳細に『対象ファイル』（`path` の箇条書き）がありません")
        for f in u["files"]:
            p = sr / f if sr else Path(f)
            if not p.exists() and not p.parent.exists():
                errs.append(f"{uid}: 対象ファイルもその親フォルダも存在しません（ソースルートからの相対パス）: {f}")
        if u.get("ai") == "要人判断" and "人の判断が必要な理由" not in C.section(t, "IU詳細"):
            errs.append(f"{uid}: 要人判断の理由（『人の判断が必要な理由』）がありません")
    errs += check_doc_refs(t, feature, C.HUMAN_DOC_PLAN) + check_src_refs(t, C.HUMAN_DOC_PLAN)
    errs += check_answers_kept(doc_p, feature)
    return errs


def v_plan_review(feature, iu, mode):
    fdir = C.feature_dir(feature)
    p = fdir / "_ai" / "review_②.md"
    errs = check_review_file(p)
    t = read(p) or ""
    if not re.search(r"^##\s+要約", t, re.M):
        errs.append("review_②.md: 『## 要約』（②実装計画.md に転記される）がありません")
    return errs


def write_plan_review_summary(feature: str) -> None:
    """plan-review の要約を②実装計画.md の『AIレビュー結果』に転記する（レビュー役は計画書を直接編集しない）。"""
    fdir = C.feature_dir(feature)
    plan_p = fdir / C.HUMAN_DOC_PLAN
    rv = read(fdir / "_ai" / "review_②.md") or ""
    g = C.gate_of(C.load_status(feature), "plan")
    summary = C.section(rv, "要約").strip() or "（要約なし）"
    block = (
        f"## AIレビュー結果\n- 判定: {verdict(rv)}（往復 {g.get('rounds', 0)}/{C.MAX_REVIEW_ROUNDS}）\n"
        f"- 詳細: _ai/review_②.md\n\n{summary}\n\n"
    )
    text = plan_p.read_text(encoding="utf-8")
    if re.search(r"^## AIレビュー結果", text, re.M):
        text = re.sub(r"^## AIレビュー結果.*?(?=^## )", lambda m: block, text, count=1, flags=re.M | re.S)
    else:
        text = re.sub(r"^## 承認", lambda m: block + "## 承認", text, count=1, flags=re.M)
    plan_p.write_text(text, encoding="utf-8")


def v_implement_unit(feature, iu, mode):
    d = C.feature_dir(feature) / "_ai" / iu
    t = read(d / "impl.md")
    if t is None:
        return [f"_ai/{iu}/impl.md を作成してください"]
    if re.search(r"^##\s+中断", t, re.M):
        if not C.Q_RE.search(C.section(t, "中断")):
            return [f"impl.md: 中断する場合は『## 中断』に質問（Q-xx）を書いてください"]
        return []
    errs = need_sections(t, ["変更箇所"], "impl.md")
    if C.rebuild_cumulative(feature, iu) == 0:
        errs.append("対象ファイルに変更がありません（②実装計画.md の対象ファイルを編集してから完了する）")
    rows = [r for tbl in C.md_tables(C.section(t, "変更箇所")) for r in tbl[1:]]
    if not rows:
        errs.append("impl.md: 『変更箇所』表に行がありません")
    for r in rows:
        joined = " ".join(r)
        if not C.REQ_RE.search(joined) or not C.DOC_REF_RE.search(joined):
            errs.append(f"impl.md: 変更箇所ごとに REQ と根拠 [設計書: …] が必要です: {joined[:60]}")
    errs += check_doc_refs(t, feature, "impl.md")
    return errs


def v_diff_review(feature, iu, mode):
    fdir = C.feature_dir(feature)
    errs = check_review_file(fdir / "_ai" / iu / "review.md", FINDING_KINDS_UNIT)
    doc = read(fdir / C.human_doc_unit(iu))
    if doc is None:
        return errs + [f"{C.human_doc_unit(iu)} を作成してください"]
    errs += need_sections(doc, ["判定", "変更一覧", "指摘", "承認"], C.human_doc_unit(iu))
    if not re.search(r"ビルド結果\s*[:：]", C.section(doc, "承認")):
        errs.append(f"{C.human_doc_unit(iu)}: 承認欄に『ビルド結果:』の記入欄がありません")
    errs += check_doc_refs(doc, feature, C.human_doc_unit(iu)) + check_src_refs(doc, C.human_doc_unit(iu))
    return errs


def v_retrospect(feature, iu, mode):
    p = C.feature_dir(feature) / "_ai" / "retro.md"
    t = read(p)
    if t is None:
        return ["_ai/retro.md を作成してください"]
    errs = []
    blocks = re.split(r"^###\s+(P-\d{2,})", t, flags=re.M)
    if len(blocks) < 2 and "提案なし" not in t:
        errs.append("retro.md: 『### P-01』形式の提案がありません（なければ『提案なし』と書く）")
    for i in range(1, len(blocks), 2):
        pid, body = blocks[i], blocks[i + 1]
        for key in ("反映先", "内容", "根拠"):
            if not re.search(rf"-[ \t]*{key}[ \t]*[:：][ \t]*\S", body):
                errs.append(f"{pid}: 『{key}』がありません")
        if not re.search(r"-\s*\[[ xX]\]\s*採用", body):
            errs.append(f"{pid}: 採否欄 `- [ ] 採用` がありません")
    if mode == "apply":
        cl = read(C.knowledge_dir() / "CHANGELOG.md") or ""
        if feature not in cl:
            errs.append("knowledge/CHANGELOG.md に今回の反映（機能名と提案番号）を記録してください")
    return errs


VALIDATORS = {
    "project-profile": v_project_profile,
    "profile-review": v_profile_review,
    "spec-extract": v_spec_extract,
    "current-survey": v_current_survey,
    "alignment-review": v_alignment_review,
    "impl-plan": v_impl_plan,
    "plan-review": v_plan_review,
    "implement-unit": v_implement_unit,
    "diff-review": v_diff_review,
    "retrospect": v_retrospect,
}


# ---------------------------------------------------------------- 状態の更新
def review_file(step: str, feature: str, iu: str | None) -> Path:
    fdir = C.feature_dir(feature)
    return {
        "profile-review": fdir / "_ai" / "review.md",
        "alignment-review": fdir / "_ai" / "review_①.md",
        "plan-review": fdir / "_ai" / "review_②.md",
        "diff-review": fdir / "_ai" / (iu or "") / "review.md",
    }[step]


def fix_targets(p: Path) -> list[str]:
    """①のレビュー結果の『修正対象』列から、直す作成役を順番に返す（不明なら両方）。"""
    t = read(p) or ""
    found = set()
    for tbl in C.md_tables(C.section(t, "指摘")):
        idx = next((i for i, h in enumerate(tbl[0]) if "修正対象" in h), None)
        for r in tbl[1:]:
            cell = r[idx] if idx is not None and idx < len(r) else " ".join(r)
            for step in ("spec-extract", "current-survey"):
                if step in cell:
                    found.add(step)
    return [s for s in ("spec-extract", "current-survey") if s in found] or ["spec-extract", "current-survey"]


def update_status(cur: dict) -> str:
    step, feature, iu, gate = cur["step"], cur["feature"], cur.get("iu"), cur["gate"]
    _, role, agent = STEPS[step]
    st = C.load_status(feature)
    if step == "retrospect":
        C.record(st, "retro", "applied" if cur.get("mode") == "apply" else "proposed", agent)
        C.save_status(feature, st)
        return "振り返りを記録しました"
    g = C.gate_of(st, gate)
    if role == "creator" and cur.get("mode") == "fix-review" and g.get("pending_fix"):
        g["pending_fix"] = [x for x in g["pending_fix"] if x != step]
    if role == "creator":
        impl = C.feature_dir(feature) / "_ai" / (iu or "") / "impl.md"
        if step == "implement-unit" and impl.exists() and re.search(
            r"^##\s+中断", impl.read_text(encoding="utf-8"), re.M
        ):
            g["state"] = "blocked_q"
            C.record(st, gate, "blocked_q", agent)
        else:
            g["state"] = "drafted"
            C.record(st, gate, "drafted", agent, cur.get("mode") or "")
        msg = f"{gate}: {C.GATE_STATES[g['state']]}"
    else:
        v = verdict(review_file(step, feature, iu).read_text(encoding="utf-8"))
        if v == "OK":
            g["state"] = "review_ok"
            C.record(st, gate, "review_ok", agent)
        else:
            g["rounds"] = g.get("rounds", 0) + 1
            if g["rounds"] >= C.MAX_REVIEW_ROUNDS:
                g["state"] = "escalated"
                C.record(st, gate, "escalated", agent)
            else:
                g["state"] = "review_ng"
                C.record(st, gate, "review_ng", agent)
                if step == "alignment-review":
                    g["pending_fix"] = fix_targets(review_file(step, feature, iu))
        msg = f"{gate}: {C.GATE_STATES[g['state']]}"
    C.save_status(feature, st)
    if step == "plan-review":
        write_plan_review_summary(feature)
    return msg


# ---------------------------------------------------------------- 入口
def complete(cur: dict) -> tuple[str, list[str]]:
    """実行中のステップを検査し、OK なら状態を更新して閉じる。
    戻り値: ("ok" | "ng" | "gave_up", メッセージ行)"""
    agent = cur["agent"]
    errs = VALIDATORS[cur["step"]](cur["feature"], cur.get("iu"), cur.get("mode"))
    if errs:
        cur["stop_blocks"] = cur.get("stop_blocks", 0) + 1
        if cur["stop_blocks"] <= MAX_STOP_BLOCKS:
            cur["last_errors"] = errs[:30]
            C.save_current(cur)
            return "ng", [f"【形式チェック NG】（{cur['stop_blocks']}/{MAX_STOP_BLOCKS}）次を直してから、もう一度 "
                          "`python tools/check_artifact.py --finish` を実行してください:", *[f"- {e}" for e in errs[:30]]]
        st = C.load_status(cur["feature"])
        if cur["gate"] != "retro":
            C.gate_of(st, cur["gate"])["state"] = "format_error"
        C.record(st, cur["gate"], "format_error", agent, "; ".join(errs[:5]))
        C.save_status(cur["feature"], st)
        cur["finished"] = True
        C.save_current(cur)
        return "gave_up", ["【形式チェック】修正の上限に達したため、人の確認に回します。作業を終えてください", *[f"- {e}" for e in errs[:10]]]
    msg = update_status(cur)
    cur["finished"] = True
    cur.pop("last_errors", None)
    C.save_current(cur)
    return "ok", [f"【形式チェック OK】{msg}"]


def run_finish() -> int:
    cur = C.active_current()
    if not cur:
        last = C.load_current()
        if last.get("finished"):
            print(f"完了処理は済んでいます（{last.get('step', '')} {last.get('args', '')}）")
            return 0
        print("実行中のステップがありません（gate.py check を通っていないか、時間が経ちすぎています）")
        return 1
    result, lines = complete(cur)
    print("\n".join(lines))
    return 0 if result in ("ok", "gave_up") else 1


def run_hook(data: dict, agent: str) -> int:
    agent = agent or data.get("agent_type") or ""
    if agent not in AGENT_TO_STEP:
        return 0
    cur = C.active_current()
    if cur.get("agent") != agent:
        return 0  # gate.py check を通らずに動いた場合や、完了処理が済んでいる場合は対象外
    result, lines = complete(cur)
    if result == "ng":
        print("\n".join(lines), file=sys.stderr)
        return 2
    print("\n".join(lines), file=sys.stderr if result == "gave_up" else sys.stdout)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--finish" in argv:
        return run_finish()
    if "--hook" in argv:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        agent = argv[argv.index("--agent") + 1] if "--agent" in argv and argv.index("--agent") + 1 < len(argv) else ""
        return run_hook(data, agent)
    if not argv:
        print(__doc__)
        return 1
    step = argv[0]
    feature = C.PROFILE_FEATURE if step in ("project-profile", "profile-review") else (argv[1] if len(argv) > 1 else "")
    iu = next((a for a in argv[1:] if C.IU_RE.fullmatch(a)), None)
    mode = "apply" if "--apply" in argv else None
    errs = VALIDATORS[step](feature, iu, mode)
    if errs:
        print("NG\n- " + "\n- ".join(errs))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
