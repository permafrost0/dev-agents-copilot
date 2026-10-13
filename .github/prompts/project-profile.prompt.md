---
name: project-profile
description: ⓪プロジェクト把握・作成役：設計思想と共通部品の台帳を作る
argument-hint: "[--fix-review]"
agent: project-profiler
---
ステップ `project-profile` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `[--fix-review]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `project-profiler` の定義（[.github/agents/project-profiler.agent.md](../agents/project-profiler.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
