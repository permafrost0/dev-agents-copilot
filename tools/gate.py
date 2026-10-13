"""ゲート（前段の承認）を判定し、承認状態を記録する。

各エージェントは作業の最初に、ターミナルで `gate.py check` を実行する。前提を満たさなければ
終了コード 2 で終わり、エージェントは作業をせずに止まる。満たしていれば、エージェントに渡す
コンテキスト（機能名、作業フォルダ、ソースルート、モード）を標準出力に出し、
実行中のステップとして work/.current.json に記録する（フックの書き込み制限と完了処理が使う）。

人が使うコマンド:
  python tools/gate.py status  <機能名>
  python tools/gate.py approve <機能名> <ゲート>          ゲート: profile | alignment | plan | IU-xx
  python tools/gate.py reject  <機能名> <ゲート> "理由"   人による差し戻し
  python tools/gate.py reopen  <機能名> <ゲート>          承認済み・上限到達のゲートをやり直す
  python tools/gate.py cancel                             中断したままのステップを閉じる（書き込み制限を解除する）

エージェントが使うコマンド:
  python tools/gate.py check <ステップ> [<機能名>] [IU-xx] [--fix-review|--fix-build|--apply]
  python tools/gate.py next  <機能名>      次に誰が何をするか（進行役が使う。状態は変えない）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# ステップ → (ゲート, 役割, 専属エージェント)
STEPS = {
    "project-profile": ("profile", "creator", "project-profiler"),
    "profile-review": ("profile", "reviewer", "profile-reviewer"),
    "spec-extract": ("alignment", "creator", "spec-reader"),
    "current-survey": ("alignment", "creator", "source-investigator"),
    "alignment-review": ("alignment", "reviewer", "alignment-reviewer"),
    "impl-plan": ("plan", "creator", "impl-planner"),
    "plan-review": ("plan", "reviewer", "plan-reviewer"),
    "implement-unit": ("unit", "creator", "implementer"),
    "diff-review": ("unit", "reviewer", "diff-reviewer"),
    "retrospect": ("retro", "creator", "knowledge-curator"),
}
AGENT_TO_STEP = {v[2]: k for k, v in STEPS.items()}

NEXT_HINT = {
    "project-profile": "/profile-review",
    "profile-review": "人の確認⓪ → python tools/gate.py approve _profile profile",
    "spec-extract": "/current-survey {f}",
    "current-survey": "/alignment-review {f}",
    "alignment-review": "人の確認① → Q に回答し、python tools/gate.py approve {f} alignment",
    "impl-plan": "/plan-review {f}",
    "plan-review": "人の確認② → python tools/gate.py approve {f} plan",
    "implement-unit": "/diff-review {f} {iu}",
    "diff-review": "人の確認③ → Eclipse でビルドし、python tools/gate.py approve {f} {iu}",
    "retrospect": "採否にチェックを付けて /retrospect {f} --apply",
}


class GateError(Exception):
    pass


# ---------------------------------------------------------------- 判定
def _rel(p: Path) -> str:
    try:
        return p.relative_to(C.root()).as_posix()
    except ValueError:
        return str(p)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise GateError(msg)


def unanswered_questions(text: str, heading: str = "質問") -> list[str]:
    """『質問』節（または指定した節）の表で、回答列が空の Q-xx を返す。"""
    out = []
    body = C.section(text, heading)
    for tbl in C.md_tables(body):
        head = tbl[0]
        idx = next((i for i, h in enumerate(head) if "回答" in h), None)
        if idx is None:
            continue
        for cells in tbl[1:]:
            m = C.Q_RE.search(cells[0]) if cells else None
            if not m:
                continue
            ans = cells[idx] if idx < len(cells) else ""
            if not ans or ans in ("-", "－", "未回答"):
                out.append(m.group(0))
    return out


def approval_checked(text: str) -> bool:
    body = C.section(text, "承認")
    return bool(re.search(r"-\s*\[[xX]\]\s*承認", body))


def build_result(text: str) -> tuple[str, str]:
    """③IU-xx.md の承認欄から（ビルド結果, エラー全文）を読む。"""
    body = C.section(text, "承認")
    m = re.search(r"ビルド結果[ \t]*[:：][ \t]*(\S+)", body)
    result = m.group(1) if m else ""
    em = re.search(r"エラー全文[^\n]*\n```[^\n]*\n(.*?)```", body, re.S)
    return result, (em.group(1).strip() if em else "")


def _fix_allowed(g: dict) -> None:
    if g["state"] == "review_ng":
        return
    # ①は作成役が2人いるため、片方を修正した後（AI作成済み）でも、もう片方の修正を許す
    if g["state"] == "drafted" and (g.get("rounds", 0) > 0 or g.get("human_rejects", 0) > 0):
        return
    if g["state"] == "escalated":
        raise GateError(
            "AI 同士のレビューが上限（2往復）に達しています。人が判断し、"
            "`gate.py reject` で差し戻すか `gate.py approve` で承認してください"
        )
    raise GateError(f"修正モードはレビュー NG のときだけ使えます（現在: {C.GATE_STATES[g['state']]}）")


def check(step: str, feature: str | None, iu: str | None, mode: str | None) -> str:
    if step not in STEPS:
        raise GateError(f"不明なステップです: {step}")
    gate_kind, role, agent = STEPS[step]
    if step in ("project-profile", "profile-review"):
        feature = C.PROFILE_FEATURE
    _require(bool(feature), "機能名を指定してください（例: /spec-extract 落としもの）")
    fdir = C.feature_dir(feature)
    ai = fdir / "_ai"
    st = C.load_status(feature)
    sr = C.source_root()

    if step not in ("retrospect",):
        problem = C.source_root_problem()
        _require(not problem, problem)

    if gate_kind != "profile":
        prof = C.load_status(C.PROFILE_FEATURE)
        _require(C.gate_of(prof, "profile")["state"] == "approved",
                 "⓪プロジェクト把握が未承認です。先に /project-profile と /profile-review を行い、承認してください")

    gate = gate_kind
    if step == "project-profile":
        g = C.gate_of(st, "profile")
        if mode == "fix-review":
            _fix_allowed(g)
    elif step == "profile-review":
        _require((C.knowledge_dir() / "project_profile.md").exists()
                 and (C.knowledge_dir() / "common_components.md").exists(),
                 "knowledge/project_profile.md と common_components.md がありません。先に /project-profile を実行してください")
        _require(C.gate_of(st, "profile")["state"] in ("drafted",),
                 "レビュー対象がありません（/project-profile の完了後に実行してください）")
    elif step == "spec-extract":
        _require(fdir.exists(), f"work/{feature}/ がありません。00_instruction.md を作成してください")
        _require(len(C.load_instruction(feature)) > 0,
                 f"work/{feature}/00_instruction.md の『対象範囲』表が空です")
        g = C.gate_of(st, "alignment")
        _require(g["state"] != "approved", "①は承認済みです。やり直す場合は `gate.py reopen` を実行してください")
        if mode == "fix-review":
            _fix_allowed(g)
    elif step == "current-survey":
        _require((ai / "01_requirements.md").exists(), "先に /spec-extract を実行してください")
        g = C.gate_of(st, "alignment")
        _require(g["state"] != "approved", "①は承認済みです。やり直す場合は `gate.py reopen` を実行してください")
        if mode == "fix-review":
            _fix_allowed(g)
    elif step == "alignment-review":
        _require((ai / "01_requirements.md").exists() and (ai / "02_current_spec.md").exists(),
                 "先に /spec-extract と /current-survey を実行してください")
        _require(C.gate_of(st, "alignment")["state"] in ("drafted",),
                 "レビュー対象がありません（作成役の実行後に行ってください）")
    elif step == "impl-plan":
        ga = C.gate_of(st, "alignment")
        _require(ga["state"] == "approved", "①認識合わせが未承認です")
        g = C.gate_of(st, "plan")
        _require(g["state"] != "approved", "②は承認済みです。やり直す場合は `gate.py reopen` を実行してください")
        if mode == "fix-review":
            _fix_allowed(g)
    elif step == "plan-review":
        _require((fdir / C.HUMAN_DOC_PLAN).exists(), "先に /impl-plan を実行してください")
        _require(C.gate_of(st, "plan")["state"] in ("drafted",),
                 "レビュー対象がありません（/impl-plan の実行後に行ってください）")
    elif step in ("implement-unit", "diff-review"):
        _require(bool(iu) and bool(C.IU_RE.fullmatch(iu or "")), "IU 番号を指定してください（例: IU-01）")
        _require(C.gate_of(st, "plan")["state"] == "approved", "②実装計画が未承認です")
        units = C.load_plan_units(feature)
        _require(iu in units, f"{iu} は②実装計画.md にありません")
        gate = iu
        g = C.gate_of(st, iu)
        if step == "implement-unit":
            _require(units[iu].get("ai", "可") == "可",
                     f"{iu} は『要人判断』です。人が方針を決めて計画を更新するか、人が実装してください")
            _require(units[iu]["files"], f"{iu} の対象ファイルが②実装計画.md に書かれていません")
            for other, u in units.items():
                if u["order"] < units[iu]["order"]:
                    _require(C.gate_of(st, other)["state"] == "approved",
                             f"前の実装単位 {other} が未承認です（順番に進めてください）")
            _require(g["state"] != "approved", f"{iu} は承認済みです。やり直す場合は `gate.py reopen` を実行してください")
            if mode == "fix-review":
                _fix_allowed(g)
            elif mode == "fix-build":
                doc = fdir / C.human_doc_unit(iu)
                _require(doc.exists(), f"{doc.name} がありません")
                result, err = build_result(doc.read_text(encoding="utf-8"))
                _require(result == "失敗" and err,
                         f"{doc.name} の承認欄に『ビルド結果: 失敗』とエラー全文を記入してから実行してください")
                g["build_errors"] = g.get("build_errors", 0) + 1
                C.record(st, iu, "build_error", "human", err[:200])
            else:
                _require(g["state"] in ("not_started", "blocked_q") or _same_step_unfinished(step, feature, iu),
                         f"{iu} は実装済みです（状態: {C.GATE_STATES[g['state']]}）。"
                         "修正は --fix-review / --fix-build を使ってください")
            # 変更前の状態を保存する（累積差分 diff.md の基準。フックが動かない環境でも差分を作れるように）
            C.snapshot_unit_files(feature, iu)
        else:
            _require(g["state"] == "drafted", f"{iu} のレビュー対象がありません（/implement-unit の実行後に行ってください）")
    elif step == "retrospect":
        _require(fdir.exists(), f"work/{feature}/ がありません")
        if mode == "apply":
            _require((ai / "retro.md").exists(), "先に /retrospect を実行してください")

    C.save_status(feature, st)
    prev = C.load_current()
    keep = _same_step_unfinished(step, feature, iu)
    args = " ".join(x for x in ["" if feature == C.PROFILE_FEATURE else feature, iu or "",
                                 f"--{mode}" if mode else ""] if x)
    C.save_current({
        "feature": feature, "step": step, "gate": gate, "iu": iu, "mode": mode,
        "agent": agent, "role": role, "started": C.now(), "args": args,
        "stop_blocks": prev.get("stop_blocks", 0) if keep else 0,
    })

    hint = NEXT_HINT[step].format(f=feature, iu=iu or "")
    lines = [
        "## 実行コンテキスト（gate.py が出力）",
        f"- 前提条件: OK",
        f"- ステップ: {step}（{'作成役' if role == 'creator' else 'レビュー役'}）",
        f"- 機能名: {feature}",
        f"- 作業フォルダ: {_rel(fdir)}/",
        f"- ソースルート: {sr.as_posix() if sr else '（未設定）'}",
        f"- 調査対象外: {', '.join(C.load_config().get('exclude') or []) or 'なし'}",
    ]
    if iu:
        lines.append(f"- 実装単位: {iu}")
        lines.append(f"- 対象ファイル: {', '.join(C.load_plan_units(feature)[iu]['files'])}")
    lines.append(f"- モード: {mode or '通常'}")
    if gate_kind != "retro":
        g = C.gate_of(st, gate)
        lines.append(f"- ゲートの状態: {C.GATE_STATES[g['state']]}（AIレビュー往復 {g['rounds']}/{C.MAX_REVIEW_ROUNDS}）")
    lines.append("- 完了するとき: `python tools/check_artifact.py --finish` を実行し、『形式チェック OK』になるまで直す")
    lines.append(f"- 完了後に人へ案内する次の操作: {hint}（進行役から呼ばれた場合は、進行役が次を判断する）")
    return "\n".join(lines)


def _same_step_unfinished(step: str, feature: str | None, iu: str | None) -> bool:
    """同じステップが完了処理をしないまま残っているか（形式エラーで再実行する場合など）。"""
    prev = C.active_current()
    return bool(prev) and prev.get("step") == step and prev.get("feature") == feature and prev.get("iu") == iu


# ---------------------------------------------------------------- 人の操作
def approve(feature: str, gate: str) -> str:
    st = C.load_status(feature)
    g = C.gate_of(st, gate)
    fdir = C.feature_dir(feature)
    if g["state"] == "approved":
        return f"{gate} は承認済みです"
    if gate == "profile":
        doc = fdir / C.HUMAN_DOC_PROFILE
    elif gate == "alignment":
        doc = fdir / C.HUMAN_DOC_ALIGNMENT
    elif gate == "plan":
        doc = fdir / C.HUMAN_DOC_PLAN
    elif C.IU_RE.fullmatch(gate):
        doc = fdir / C.human_doc_unit(gate)
    else:
        raise GateError(f"不明なゲートです: {gate}")

    units = C.load_plan_units(feature) if C.IU_RE.fullmatch(gate) else {}
    human_unit = bool(units.get(gate)) and units[gate].get("ai") == "要人判断"
    if not human_unit:
        _require(g["state"] in ("review_ok", "escalated"),
                 f"承認できる状態ではありません（現在: {C.GATE_STATES[g['state']]}）")
        _require(doc.exists(), f"{doc.name} がありません")
        text = doc.read_text(encoding="utf-8")
        _require(approval_checked(text), f"{doc.name} の『承認』欄の `- [ ] 承認` にチェック（[x]）を付けてください")
        if gate == "alignment":
            q = unanswered_questions(text)
            _require(not q, f"未回答の質問があります: {', '.join(q)}")
        if gate == "plan":
            q = unanswered_questions(text)
            _require(not q, f"未回答の質問があります: {', '.join(q)}")
        if C.IU_RE.fullmatch(gate):
            result, _ = build_result(text)
            _require(result == "成功", f"{doc.name} の承認欄に『ビルド結果: 成功』を記入してください（Eclipse で clean install）")
            if re.search(r"手直しした内容[ \t]*[:：][ \t]*\S", C.section(text, "承認")):
                C.record(st, gate, "human_rework", "human")
    g["state"] = "approved"
    g["approved_at"] = C.now()
    C.record(st, gate, "approved", "human")
    C.save_status(feature, st)
    return f"{gate} を承認しました"


def reject(feature: str, gate: str, reason: str) -> str:
    _require(bool(reason.strip()), "差し戻しの理由を指定してください")
    st = C.load_status(feature)
    g = C.gate_of(st, gate)
    g["state"] = "review_ng"
    g["rounds"] = 0  # 人の差し戻し後は、AI 同士のやり取りを数え直す
    g["human_rejects"] = g.get("human_rejects", 0) + 1
    if gate == "alignment":
        g["pending_fix"] = ["spec-extract", "current-survey"]
    C.record(st, gate, "rejected", "human", reason)
    C.save_status(feature, st)
    return f"{gate} を差し戻しました。作成役のスキルを --fix-review 付きで実行してください"


def reopen(feature: str, gate: str) -> str:
    st = C.load_status(feature)
    g = C.gate_of(st, gate)
    g["state"] = "not_started"
    g["rounds"] = 0
    g.pop("pending_fix", None)
    C.record(st, gate, "reopened", "human")
    C.save_status(feature, st)
    return f"{gate} をやり直せる状態にしました"


def cancel() -> str:
    cur = C.load_current()
    if not cur or cur.get("finished"):
        return "実行中のステップはありません"
    cur["finished"] = True
    cur["cancelled"] = C.now()
    C.save_current(cur)
    return f"実行中のステップ（{cur.get('step')} {cur.get('args', '')}）を閉じました。必要ならもう一度実行してください"


# ---------------------------------------------------------------- 次の操作（進行役が使う）
AGENT_OF = {k: v[2] for k, v in STEPS.items()}


def _ai(step: str, args: str, note: str = "") -> str:
    lines = [
        "## 次の操作（gate.py next）",
        "- 種別: AI",
        f"- エージェント: {AGENT_OF[step]}",
        f"- 依頼文: ステップ `{step}` を実行してください。引数: {f'`{args}`' if args else 'なし'}",
    ]
    if note:
        lines.append(f"- 補足: {note}")
    return "\n".join(lines)


def _human(situation: str, read: list[str], ops: list[str]) -> str:
    lines = ["## 次の操作（gate.py next）", "- 種別: 人", f"- 状況: {situation}"]
    if read:
        lines.append("- 人が読むもの: " + "、".join(f"`{r}`" for r in read))
    lines.append("- 人の操作:")
    lines += [f"  {i}. {op}" for i, op in enumerate(ops, 1)]
    return "\n".join(lines)


def _gate_wait(feature: str, gate: str, g: dict, doc: str, approve_note: str = "") -> str | None:
    """人の判断待ちの状態なら、その案内を返す。"""
    state = g["state"]
    rel_doc = f"work/{feature}/{doc}"
    if state == "review_ok":
        ops = [f"`{rel_doc}` を確認する"]
        if approve_note:
            ops.append(approve_note)
        ops += ["『承認』欄の `- [ ] 承認` を `- [x] 承認` にする",
                f"`python tools/gate.py approve {feature} {gate}`（直させたい場合は `python tools/gate.py reject {feature} {gate} \"理由\"`）",
                "もう一度、進行役に依頼する"]
        return _human("AI レビューが OK になり、人の承認待ちです", [rel_doc], ops)
    if state == "escalated":
        return _human(
            f"AI 同士のレビューが上限（{C.MAX_REVIEW_ROUNDS}往復）に達しました。人の判断が必要です",
            [rel_doc],
            [f"指摘（`work/{feature}/_ai/` のレビュー結果）を読み、判断する",
             f"直させる: `python tools/gate.py reject {feature} {gate} \"理由\"` → 進行役に依頼",
             f"このまま進める: 承認欄にチェックして `python tools/gate.py approve {feature} {gate}`"])
    if state == "format_error":
        return _human(
            "成果物の形式チェックが上限まで通りませんでした。人の確認が必要です",
            [f"work/{feature}/status.json（history の最後）"],
            ["原因（ファイルの不足・根拠の書き方など）を確認する",
             f"やり直す: `python tools/gate.py reopen {feature} {gate}` → 進行役に依頼"])
    return None


def next_action(feature: str) -> str:
    cur = C.active_current()
    if cur:
        if cur.get("last_errors"):
            return _ai(cur["step"], cur.get("args", ""),
                       "前回の成果物が形式チェックで NG でした。次を直してから完了してください: "
                       + " / ".join(cur["last_errors"][:10]))
        return "\n".join([
            "## 次の操作（gate.py next）",
            "- 種別: 完了処理",
            f"- 状況: ステップ `{(cur.get('step', '') + ' ' + cur.get('args', '')).strip()}` の完了処理が済んでいません",
            "- 実行するコマンド: `python tools/check_artifact.py --finish`",
        ])

    problem = C.source_root_problem()
    if problem:
        return _human("対象PJのソースルートが設定されていません", [f"templates/{C.WORKSPACE_FILE}"],
                      [problem, f"VS Code で {C.WORKSPACE_FILE} を開き直す（ファイル → ファイルでワークスペースを開く）",
                       "もう一度、進行役に依頼する"])

    # ⓪ プロジェクト把握
    prof_st = C.load_status(C.PROFILE_FEATURE)
    gp = C.gate_of(prof_st, "profile")
    if gp["state"] != "approved" or feature == C.PROFILE_FEATURE:
        if gp["state"] == "approved":
            return _human("⓪プロジェクト把握は承認済みです", [], ["機能名を指定して進行役に依頼する"])
        pre = "（機能の作業の前に、⓪プロジェクト把握が必要です）" if feature != C.PROFILE_FEATURE else ""
        if gp["state"] == "not_started":
            return _ai("project-profile", "", pre)
        if gp["state"] == "drafted":
            return _ai("profile-review", "", pre)
        if gp["state"] == "review_ng":
            return _ai("project-profile", "--fix-review", pre)
        if gp["state"] == "review_ok":
            return _human("⓪プロファイルの AI レビューが OK になり、人の承認待ちです",
                          [f"work/_profile/{C.HUMAN_DOC_PROFILE}", "knowledge/project_profile.md", "knowledge/common_components.md"],
                          ["3つのファイルを確認し、不明点（Q）があれば project_profile.md に回答を書く",
                           f"{C.HUMAN_DOC_PROFILE} の承認欄にチェック（[x]）を付ける",
                           "`python tools/gate.py approve _profile profile`",
                           "もう一度、進行役に依頼する"])
        w = _gate_wait(C.PROFILE_FEATURE, "profile", gp, C.HUMAN_DOC_PROFILE)
        if w:
            return w

    fdir = C.feature_dir(feature)
    if not (fdir / "00_instruction.md").exists() or not C.load_instruction(feature):
        return _human(f"work/{feature}/00_instruction.md がないか、『対象範囲』が空です",
                      ["templates/00_instruction.md"],
                      [f"設計書を `input/設計書/` 直下に置く",
                       f"`templates/00_instruction.md` を `work/{feature}/00_instruction.md` にコピーし、加筆したシートとセル範囲を書く",
                       "もう一度、進行役に依頼する"])
    st = C.load_status(feature)
    ai = fdir / "_ai"

    # ① 認識合わせ
    ga = C.gate_of(st, "alignment")
    if ga["state"] != "approved":
        req, cur_spec = ai / "01_requirements.md", ai / "02_current_spec.md"
        pending = ga.get("pending_fix") or []
        if ga["state"] == "not_started":
            return _ai("spec-extract", feature)
        if ga["state"] == "review_ng":
            step = pending[0] if pending else "spec-extract"
            return _ai(step, f"{feature} --fix-review")
        if ga["state"] == "drafted":
            if pending:
                return _ai(pending[0], f"{feature} --fix-review")
            fresh = ga.get("rounds", 0) == 0 and ga.get("human_rejects", 0) == 0
            if not cur_spec.exists() or (fresh and req.exists() and cur_spec.stat().st_mtime < req.stat().st_mtime):
                return _ai("current-survey", feature)
            return _ai("alignment-review", feature)
        w = _gate_wait(feature, "alignment", ga, C.HUMAN_DOC_ALIGNMENT,
                       "質問（Q）の『回答』列に記入する（未回答があると承認できない）")
        if w:
            return w

    # ② 実装計画
    gpl = C.gate_of(st, "plan")
    if gpl["state"] != "approved":
        if gpl["state"] == "not_started":
            return _ai("impl-plan", feature)
        if gpl["state"] == "drafted":
            return _ai("plan-review", feature)
        if gpl["state"] == "review_ng":
            return _ai("impl-plan", f"{feature} --fix-review")
        w = _gate_wait(feature, "plan", gpl, C.HUMAN_DOC_PLAN,
                       "質問（Q）があれば『回答』列に記入する。『要人判断』の IU は人が実装する前提で確認する")
        if w:
            return w

    # ③ 実装（IU を順番に）
    units = C.load_plan_units(feature)
    if not units:
        return _human("②実装計画.md に実装単位（IU）がありません", [f"work/{feature}/{C.HUMAN_DOC_PLAN}"],
                      [f"計画を見直す: `python tools/gate.py reopen {feature} plan` → 進行役に依頼"])
    for iu, u in sorted(units.items(), key=lambda kv: kv[1]["order"]):
        g = C.gate_of(st, iu)
        if g["state"] == "approved":
            continue
        doc = C.human_doc_unit(iu)
        if u.get("ai") == "要人判断":
            return _human(f"{iu} は『要人判断』です（AI は実装しません）",
                          [f"work/{feature}/{C.HUMAN_DOC_PLAN}（{iu} の『人の判断が必要な理由』）"],
                          [f"人が実装し、Eclipse でビルドを確認してから `python tools/gate.py approve {feature} {iu}`",
                           f"または、方針を決めて計画を直す: `python tools/gate.py reopen {feature} plan` → 進行役に依頼"])
        if g["state"] == "not_started":
            return _ai("implement-unit", f"{feature} {iu}")
        if g["state"] == "blocked_q":
            impl = ai / iu / "impl.md"
            text = impl.read_text(encoding="utf-8") if impl.exists() else ""
            q = unanswered_questions(text, "中断")
            if q:
                return _human(f"{iu} の実装が質問で中断しています（{', '.join(q)}）",
                              [f"work/{feature}/_ai/{iu}/impl.md"],
                              ["『## 中断』の表の『回答』列に記入する",
                               f"計画の見直しが必要なら `python tools/gate.py reopen {feature} plan`",
                               "もう一度、進行役に依頼する"])
            return _ai("implement-unit", f"{feature} {iu}", "中断時の質問に人が回答済み。impl.md の回答を読んで再開する")
        if g["state"] == "drafted":
            return _ai("diff-review", f"{feature} {iu}")
        if g["state"] == "review_ng":
            return _ai("implement-unit", f"{feature} {iu} --fix-review")
        if g["state"] == "review_ok" and (fdir / doc).exists():
            result, err = build_result((fdir / doc).read_text(encoding="utf-8"))
            if result == "失敗" and err:
                return _ai("implement-unit", f"{feature} {iu} --fix-build")
            if result == "失敗":
                return _human(f"{iu} のビルド結果が『失敗』ですが、エラー全文がありません", [f"work/{feature}/{doc}"],
                              ["承認欄の『エラー全文』のコードブロックに、Eclipse のエラーを貼る", "もう一度、進行役に依頼する"])
        if g["state"] == "review_ok":
            return _human(f"{iu} の AI レビューが OK になり、人の確認待ちです",
                          [f"work/{feature}/{doc}", f"work/{feature}/_ai/{iu}/diff.md"],
                          ["差分を確認する（変更一覧以外の変更がないこと）",
                           "Eclipse で `maven clean install`（必要なら Tomcat で画面を確認）",
                           f"成功: 承認欄の『ビルド結果:』を `成功` にし、`- [x] 承認` にして `python tools/gate.py approve {feature} {iu}`",
                           "失敗: 『ビルド結果:』を `失敗` にし、『エラー全文』にエラーを貼って、進行役に依頼する（AI が直す）",
                           f"直させたい: `python tools/gate.py reject {feature} {iu} \"理由\"` → 進行役に依頼"])
        w = _gate_wait(feature, iu, g, doc)
        if w:
            return w
        return _human(f"{iu} の状態を判断できません（{g['state']}）", [f"work/{feature}/status.json"],
                      [f"`python tools/gate.py status {feature}` で確認する"])

    # 振り返り
    retro = ai / "retro.md"
    events = [h["event"] for h in st.get("history", []) if h.get("gate") == "retro"]
    if not retro.exists() or not events:
        return _ai("retrospect", feature, "全 IU が承認済み。振り返りの提案を作る")
    text = retro.read_text(encoding="utf-8")
    if events[-1] == "applied":
        return _human("この機能は完了しています（振り返りの反映済み）", ["knowledge/CHANGELOG.md"],
                      ["次の機能は、新しい機能名で 00_instruction.md を作って進行役に依頼する"])
    if re.search(r"-\s*\[[xX]\]\s*採用", text):
        return _ai("retrospect", f"{feature} --apply", "人が採用にチェックした提案だけを反映する")
    if "提案なし" in text:
        return _human("この機能は完了しています（振り返りの提案なし）", [], ["次の機能に進む"])
    return _human("振り返りの提案ができています", [f"work/{feature}/_ai/retro.md"],
                  ["採用する提案の `- [ ] 採用` を `- [x] 採用` にする", "進行役に依頼すると反映する（採用するものがなければ、この機能は完了）"])


def status(feature: str) -> str:
    st = C.load_status(feature)
    lines = [f"# 状態: {feature}", "| ゲート | 状態 | AIレビュー往復 | 人の差し戻し |", "|---|---|---|---|"]
    for name, g in st["gates"].items():
        lines.append(f"| {name} | {C.GATE_STATES.get(g['state'], g['state'])} | {g['rounds']} | {g.get('human_rejects', 0)} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    last = {"ts": C.now(), "command": " ".join(argv)}
    try:
        if cmd == "check":
            mode = None
            for flag in ("--fix-review", "--fix-build", "--apply"):
                if flag in rest:
                    mode = flag[2:]
                    rest.remove(flag)
            step = rest[0] if rest else ""
            feature = rest[1] if len(rest) > 1 else None
            if step in ("project-profile", "profile-review"):
                feature, iu = None, None
            iu = next((r for r in rest[2:] if C.IU_RE.fullmatch(r)), None)
            print(check(step, feature, iu, mode))
        elif cmd == "approve":
            print(approve(rest[0], rest[1]))
        elif cmd == "reject":
            print(reject(rest[0], rest[1], " ".join(rest[2:])))
        elif cmd == "reopen":
            print(reopen(rest[0], rest[1]))
        elif cmd == "status":
            print(status(rest[0]))
        elif cmd == "next":
            print(next_action(rest[0]))
        elif cmd == "cancel":
            print(cancel())
        else:
            print(__doc__)
            return 1
        if cmd == "check":
            _save_last({**last, "ok": True})
        return 0
    except (GateError, IndexError) as e:
        msg = str(e) if isinstance(e, GateError) else "引数が足りません"
        print(f"【ゲート判定 NG】{msg}", file=sys.stderr)
        print(f"【ゲート判定 NG】{msg}")
        if cmd == "check":
            _save_last({**last, "ok": False, "message": msg})
        return 2


def _save_last(data: dict) -> None:
    """直近のゲート判定を残す（スキルが起動しなかった理由を人が確認するため）。"""
    import json

    try:
        p = C.work_dir() / ".last_gate.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
