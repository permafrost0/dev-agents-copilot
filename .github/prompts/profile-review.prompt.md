---
name: profile-review
description: ⓪プロジェクト把握・レビュー役：プロファイルを中立にレビューする
argument-hint: "（引数なし）"
agent: profile-reviewer
---
ステップ `profile-review` を実行してください。

- 引数：このコマンドの後ろに書かれたもの（このステップは引数なし）。必要な引数がなければ、作業せずに書き方を伝えて終える
- 手順は、エージェント `profile-reviewer` の定義（[.github/agents/profile-reviewer.agent.md](../agents/profile-reviewer.agent.md)）のとおり。最初に `gate.py check`、最後に `check_artifact.py --finish` を実行する
