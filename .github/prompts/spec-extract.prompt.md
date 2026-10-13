---
name: spec-extract
description: ①認識合わせ・作成役：設計書の指示範囲から要件（REQ）を抽出する
argument-hint: "<機能名> [--fix-review]"
agent: spec-reader
---
ステップ `spec-extract` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> [--fix-review]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `spec-reader` の定義（[.github/agents/spec-reader.agent.md](../agents/spec-reader.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
