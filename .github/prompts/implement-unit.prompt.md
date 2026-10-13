---
name: implement-unit
description: ③実装・作成役：指定した1つの IU だけを最小の差分で実装する
argument-hint: "<機能名> IU-xx [--fix-review|--fix-build]"
agent: implementer
---
ステップ `implement-unit` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> IU-xx [--fix-review|--fix-build]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `implementer` の定義（[.github/agents/implementer.agent.md](../agents/implementer.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
