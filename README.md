# 設計書駆動 追加開発エージェント（GitHub Copilot 版）：運用手順

Excel の詳細設計書で加筆した箇所をもとに、既存の Java（Spring）プロジェクトへ追加開発します。
VS Code の GitHub Copilot（エージェントモード）で動きます。
AI は「作成役 → 中立なレビュー役」の順に動き、各段階の最後に**人が確認・承認**してから次へ進みます。

## 前提
- VS Code と GitHub Copilot（カスタムエージェント、プロンプトファイル、サブエージェント、フックが使えるバージョン）
- Python 3 と openpyxl（`pip install openpyxl`）。ターミナルで `python` が動くこと
- フック（Preview 機能）が組織のポリシーで無効でも動きます。その場合、一部の制限が「指示ベース」になります（下の『守られていること』）

## 準備（初回のみ）
1. このフォルダ一式を、作業用のフォルダに置く
2. `config/project.md` の `source_root` に、対象PJのソースルート（pom.xml があるフォルダ。Eclipse のワークスペース内の実物）を書く
3. `templates/dev-agents.code-workspace` をこのフォルダ直下にコピーし、2つ目の `path` を同じソースルートに書き換える
4. VS Code で「ファイル → ファイルでワークスペースを開く」から、コピーした `dev-agents.code-workspace` を開く
   - 1つ目のフォルダは必ずこのパッケージにする（スクリプトとフックの実行場所になる）
   - 「このフォルダの作成者を信頼する」を選ぶ（フックを有効にするため）
5. `input/設計方針/` に、設計方針ドキュメントやコーディング規約を置く
6. Copilot Chat を開き、エージェントモードで `/proceed _profile` を実行する（⓪プロジェクト把握）
   → 人が `work/_profile/⓪プロファイル確認.md` と `knowledge/` の2ファイルを確認 → `python tools/gate.py approve _profile profile`

## 進め方（おすすめ）：進行役に任せる
設計書を `input/設計書/` の**直下**に置き、`templates/00_instruction.md` を `work/<機能名>/00_instruction.md` にコピーして、加筆したシート名とセル範囲を書きます。

その後は、チャットで次を実行するだけです。

```
/proceed <機能名>
```

進行役（`orchestrator`）は `python tools/gate.py next <機能名>` で次のステップを判断し、作成役 → レビュー役を**サブエージェント**（別のコンテキスト）で実行します。
AI 同士のレビューが NG なら作成役に直させ（最大2往復）、**人の確認・承認が必要なところで止まって**、何を読んで何をすればよいかを案内します。
人の操作が終わったら、もう一度 `/proceed <機能名>` を実行します。

| 段階 | 進行役が動かすエージェント | 人が読むもの | 人の操作 |
|---|---|---|---|
| ⓪ プロジェクト把握 | project-profiler → profile-reviewer | `work/_profile/⓪プロファイル確認.md`、`knowledge/` の2ファイル | 承認欄にチェック → `python tools/gate.py approve _profile profile` |
| ① 認識合わせ | spec-reader → source-investigator → alignment-reviewer | `work/<機能名>/①認識合わせ.md` | 質問（Q）の『回答』列に記入し、承認欄にチェック → `python tools/gate.py approve <機能名> alignment` |
| ② 実装計画 | impl-planner → plan-reviewer | `work/<機能名>/②実装計画.md` | 承認欄にチェック → `python tools/gate.py approve <機能名> plan` |
| ③ 実装（IU ごと） | implementer → diff-reviewer | `work/<機能名>/③IU-01.md`（差分の全文は `_ai/IU-01/diff.md`） | Eclipse で `maven clean install`（必要なら Tomcat で確認）→ 承認欄にビルド結果を書きチェック → `python tools/gate.py approve <機能名> IU-01` |
| 振り返り | knowledge-curator | `work/<機能名>/_ai/retro.md` | 採用する提案にチェック → `/proceed <機能名>`（採用分だけ反映される） |

- ビルドが失敗したら、③IU-xx.md の承認欄に『ビルド結果: 失敗』とエラー全文を貼って `/proceed <機能名>` → AI がエラーの箇所だけ直します
- 「要人判断」の IU は AI に実装させません。人が実装して承認するか、方針を決めて②を見直します（`python tools/gate.py reopen <機能名> plan`）
- 承認・差し戻し・やり直しは、**人が自分のターミナルで**実行します（AI は実行できません）

## 進め方（個別）：ステップごとにコマンドを実行する
従来どおり、各ステップをコマンドで実行することもできます。
**コマンドごとに新しいチャット（New Chat）で実行してください**。同じチャットで続けると、レビュー役が作成役のやり取りを見てしまい、中立なレビューになりません。

| 段階 | 実行するもの |
|---|---|
| ⓪ | `/project-profile` → `/profile-review` |
| ① | `/spec-extract <機能名>` → `/current-survey <機能名>` → `/alignment-review <機能名>` |
| ② | `/impl-plan <機能名>` → `/plan-review <機能名>` |
| ③ | `/implement-unit <機能名> IU-01` → `/diff-review <機能名> IU-01` |
| 振り返り | `/retrospect <機能名>` → `/retrospect <機能名> --apply` |

- 前の段階が承認されていないと、各エージェントは最初の `gate.py check` で止まります
- 次に何をすればよいか分からなくなったら、ターミナルで `python tools/gate.py next <機能名>` を実行すると表示されます

## うまくいかなかったとき
| 状況 | 操作 |
|---|---|
| AI のレビューが NG | 進行役なら自動で直します。個別なら作成役のコマンドを `--fix-review` 付きで再実行 → もう一度レビュー（AI 同士は最大2往復。超えたら人が判断） |
| 人が差し戻したい | `python tools/gate.py reject <機能名> <ゲート> "理由"` → `/proceed <機能名>`（個別なら作成役を `--fix-review` 付きで再実行） |
| Eclipse でビルドエラー | ③IU-xx.md の承認欄に『ビルド結果: 失敗』とエラー全文を貼る → `/proceed <機能名>`（個別なら `/implement-unit <機能名> IU-xx --fix-build` → `/diff-review`） |
| 実装が中断した（範囲外の変更が必要） | `_ai/IU-xx/impl.md` の『## 中断』の質問に回答して `/proceed <機能名>`、または `gate.py reopen <機能名> plan` で計画を見直す |
| 形式エラーで止まった | `work/<機能名>/status.json` の history の最後で原因を確認 → `python tools/gate.py reopen <機能名> <ゲート>` |
| エージェントが途中で止まり、その後の書き込みが拒否される | `python tools/gate.py cancel`（実行中のステップを閉じる）→ もう一度実行 |
| 状態を確認したい | `python tools/gate.py status <機能名>`、次の操作は `python tools/gate.py next <機能名>` |
| 承認済みの段階をやり直したい | `python tools/gate.py reopen <機能名> <ゲート>` |
| フックが「can't open file」で失敗する | ワークスペースの1つ目のフォルダがこのパッケージになっているか確認する |

ゲート名：`profile`（⓪）、`alignment`（①）、`plan`（②）、`IU-01` など（③）

## 守られていること
| 内容 | 仕組み | フックが無効な環境 |
|---|---|---|
| 前の段階が未承認なら次に進まない | `gate.py check`（各エージェントが最初に実行） | 同じ |
| 成果物の形式（根拠の書き方、全要件の割り当てなど）の検査と、状態の更新 | `check_artifact.py --finish`（各エージェントが最後に実行）。終わり忘れはフック（Stop）が止める | `--finish` だけで動く |
| `input/`、設計書（Excel）、状態ファイル、`tools/` は書き換えられない | フック（`.github/hooks/guard.json`） | 指示ベース |
| エージェントごとの書き込み先の制限（⓪①②のエージェントは `work/` と `knowledge/` だけ、レビュー役は作成役の成果物を書き換えられない） | エージェントのフック（`hooks:`）と guard.json | 指示ベース |
| ③のエージェントは、②で承認した対象ファイル以外を変更できない | 同上 | 指示ベース（範囲外の変更はレビュー役と人が差分で確認） |
| ③の変更内容は `diff.md`（IU 開始前からの累積差分）に自動で記録 | `gate.py check` が変更前を保存し、`--finish` が差分を作る（フックが有効なら `edits.md` に編集ごとの記録も残る） | `diff.md` は作られる |
| AI が実行できるコマンドは tools/ のスクリプトだけ。承認・差し戻しは実行できない | フックと、各エージェントのツールの制限 | 指示ベース（`.vscode/settings.json` の自動承認の対象外なので、実行前に確認が出る） |
| 人が書いた質問の回答を AI が消すと、形式チェックで止まる | フックが旧版を `_ai/history/` に退避し、`--finish` が比べる | 検知しない |

## フォルダ
| フォルダ | 内容 |
|---|---|
| `input/設計書/` | 設計書（直下に置く） |
| `input/設計方針/` | 設計方針ドキュメント |
| `work/<機能名>/` | 人が読む文書（①②③）、状態、`_ai/`（AI の中間成果物） |
| `knowledge/` | 使うほど育つナレッジ（人が採用したものだけ） |
| `.github/agents/` | 専属エージェント（10）と進行役 |
| `.github/prompts/` | コマンド（`/proceed` と各ステップ） |
| `.github/steps/<ステップ>/` | 各ステップの出力形式（output-template.md）とレビュー観点（checklist.md） |
| `.github/hooks/` | ワークスペース全体のフック |
| `.github/copilot-instructions.md` | 全エージェント共通の原則 |
| `tools/` | 補助スクリプト（ゲート、形式チェック、書き込み制限、設計書の抽出、指標） |
| `templates/` | 指示書、テスト観点、ワークスペースファイルのひな形 |

## Claude Code 版からの変更点
| Claude Code 版 | Copilot 版 |
|---|---|
| `.claude/agents/*.md` ＋ `.claude/skills/*/SKILL.md` | `.github/agents/*.agent.md`（役割と手順を1つにまとめた）＋ `.github/prompts/*.prompt.md`（コマンド） |
| スキルの `context: fork` で専属エージェントが別コンテキストで動く | 進行役がサブエージェントとして呼ぶ（個別コマンドは新しいチャットで実行） |
| SKILL.md の `` !`gate.py check` `` でスキル起動前に判定 | エージェントが最初にターミナルで `gate.py check` を実行 |
| SubagentStop フックで形式チェックと状態の更新 | エージェントが最後に `check_artifact.py --finish` を実行（Stop フックは安全網） |
| `.claude/settings.json` の permissions とフック | エージェントごとの `tools` と `hooks`、`.github/hooks/guard.json` |
| CLAUDE.md | `.github/copilot-instructions.md` |
| `.claude/skills/<スキル>/checklist.md` など | `.github/steps/<ステップ>/checklist.md` など |
| （なし） | 進行役（`/proceed`）と `gate.py next`／`gate.py cancel` |

## リポジトリで管理するときの注意
- `work/`、`input/` の中身、PJ 固有のナレッジ（`project_profile.md`、`common_components.md`、`metrics.csv`）、ワークスペースファイルは `.gitignore` で除外しています
- `knowledge/` のほかのファイル（qa_log.md など）や `.github/steps/*/checklist.md` も、使ううちに PJ の情報が追記されます。公開リポジトリには、使い始める前の状態だけを置いてください
