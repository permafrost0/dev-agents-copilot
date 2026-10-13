---
name: impl-plan
description: ②実装計画・作成役：要件を小さな実装単位（IU）に分けて計画する
argument-hint: "<機能名> [--fix-review]"
agent: impl-planner
---
ステップ `impl-plan` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> [--fix-review]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `impl-planner` の定義（[.github/agents/impl-planner.agent.md](../agents/impl-planner.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
