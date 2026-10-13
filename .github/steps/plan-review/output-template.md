# 出力形式：②実装計画のレビュー（work/<機能名>/_ai/review_②.md）

```markdown
# レビュー結果：② <機能名>
判定: NG

## 指摘
| No | 種別 | 内容 | 根拠 |
|---|---|---|---|
| 1 | 共通部品の再利用漏れ | IU-03 で必須チェックを自前で書く計画だが、ValidationUtil#required がある | [ソース: src/main/java/jp/example/common/ValidationUtil.java:12] |

## 要約
- 指摘 1 件（共通部品の再利用漏れ 1）
- IU-03 は ValidationUtil#required を使う計画に直す必要がある
```

## ルール
- 判定は `判定: OK` か `判定: NG` の1行で書く。NG のときは指摘を1件以上書く
- 種別は checklist.md の観点名を使う。根拠列は必須
- 『## 要約』は3〜5行で書く（②実装計画.md の『AIレビュー結果』に転記され、人が読む）
