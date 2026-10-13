---
name: plan-review
description: ②実装計画・レビュー役：実装計画を中立にレビューする
argument-hint: "<機能名>"
agent: plan-reviewer
---
ステップ `plan-review` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名>`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `plan-reviewer` の定義（[.github/agents/plan-reviewer.agent.md](../agents/plan-reviewer.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
