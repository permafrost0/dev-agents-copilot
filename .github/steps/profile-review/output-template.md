# 出力形式：⓪プロファイルのレビュー

## work/_profile/_ai/review.md

```markdown
# レビュー結果：⓪プロファイル
判定: OK

## 指摘
| No | 種別 | 内容 | 根拠 |
|---|---|---|---|
| 1 | 根拠の実在 | DateUtil の行番号が実際と異なる | [ソース: src/main/java/…/DateUtil.java:20] |
```

- 判定は `判定: OK` か `判定: NG` の1行で書く
- 種別は checklist.md の観点名を使う。根拠列は必須
- 指摘がなければ表の行は空でよい（判定 OK）

## work/_profile/⓪プロファイル確認.md（人が読む文書）

```markdown
# ⓪ プロファイル確認
> 人が確認する文書です。確認対象は knowledge/project_profile.md と knowledge/common_components.md です。

## 概要
- 技術構成: …（project_profile.md の要約を3行以内で）
- 共通部品: …件

## 人が確認すること
- 不明点（Q）への回答（project_profile.md の『不明点』に追記してください）
- …

## AIレビュー結果
- 判定: OK
- 指摘の要約: なし

## 承認
- [ ] 承認
- 差し戻し理由:
```
