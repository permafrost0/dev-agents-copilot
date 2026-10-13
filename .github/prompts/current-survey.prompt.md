---
name: current-survey
description: ①認識合わせ・作成役：REQ に関係する現行ソースを調べる
argument-hint: "<機能名> [--fix-review]"
agent: source-investigator
---
ステップ `current-survey` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> [--fix-review]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `source-investigator` の定義（[.github/agents/source-investigator.agent.md](../agents/source-investigator.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
