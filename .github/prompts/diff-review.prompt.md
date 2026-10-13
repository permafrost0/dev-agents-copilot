---
name: diff-review
description: ③実装・レビュー役：1つの IU の差分を中立に判定し、③IU-xx.md を作る
argument-hint: "<機能名> IU-xx"
agent: diff-reviewer
---
ステップ `diff-review` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> IU-xx`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `diff-reviewer` の定義（[.github/agents/diff-reviewer.agent.md](../agents/diff-reviewer.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
