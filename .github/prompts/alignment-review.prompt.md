---
name: alignment-review
description: ①認識合わせ・レビュー役：要件と現行仕様を中立にレビューし、①認識合わせ.md を作る
argument-hint: "<機能名>"
agent: alignment-reviewer
---
ステップ `alignment-review` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名>`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `alignment-reviewer` の定義（[.github/agents/alignment-reviewer.agent.md](../agents/alignment-reviewer.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
