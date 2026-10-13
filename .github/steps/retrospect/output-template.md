# 出力形式：振り返り

## work/<機能名>/_ai/retro.md

```markdown
# 振り返り：<機能名>

## 指標（metrics.py）
- 質問数: 3（うち過去回答の参照 0）
- AIレビューNG: 2、人の差し戻し: 1、手直し: 1、ビルドエラー: 0、共通部品の再利用漏れ: 1

## 提案
### P-01
- 反映先: knowledge/qa_log.md
- 内容: 「メッセージ一覧の新しい ID は、既存の採番の続きで新規追加とする」（Q-01 の回答）
- 根拠: ①認識合わせ.md Q-01 の人の回答
- [ ] 採用

### P-02
- 反映先: .github/steps/diff-review/checklist.md
- 内容: 観点「Mapper XML の列の並びは既存の順序に合わせる」を追加
- 根拠: ③IU-02.md の差し戻し理由
- [ ] 採用
```

- 提案がなければ『## 提案』の下に「提案なし」と書く
- 反映先は、knowledge/ のファイル、`.github/steps/<ステップ>/checklist.md`、「エージェント定義（構築環境で反映）」（.github/agents/ と .github/prompts/ は自分では書き換えない）のいずれか

## 反映時の書き方（--apply）

knowledge/ の各ファイルには、1項目1行で出典を付けて追記する。

```markdown
- メッセージ一覧の新しい ID は既存の採番の続きで新規追加とする（出典: 落としもの Q-01 / 2026-10-20）
```

knowledge/CHANGELOG.md:

```markdown
- 2026-10-20 落としもの P-01 → knowledge/qa_log.md
```
