---
name: proceed
description: 進行役：指定した機能を、人の確認・承認が必要なところまで自動で進める
argument-hint: "<機能名>（⓪プロジェクト把握だけなら _profile）"
agent: orchestrator
---
このコマンドの後ろに書かれた機能名で、進行役の手順（[.github/agents/orchestrator.agent.md](../agents/orchestrator.agent.md)）どおりに進めてください。

- 機能名が書かれていなければ、作業せずに機能名を聞く
- 次にやることは `python tools/gate.py next <機能名>` の出力に従う
- 人の確認・承認が必要なところで止まり、何を読んで何をすればよいかを案内する
