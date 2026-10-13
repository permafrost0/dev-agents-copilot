---
name: retrospect
description: 振り返り：ナレッジとレビュー観点の更新案を作る（--apply で採用分を反映）
argument-hint: "<機能名> [--apply]"
agent: knowledge-curator
---
ステップ `retrospect` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（形式: `<機能名> [--apply]`）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `knowledge-curator` の定義（[.github/agents/knowledge-curator.agent.md](../agents/knowledge-curator.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
