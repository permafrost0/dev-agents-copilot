# 出力形式：現行仕様（work/<機能名>/_ai/02_current_spec.md）

```markdown
# 現行仕様：<機能名>
> AI の中間成果物。現行仕様はソースを正とする。

## 技術構成
- knowledge/project_profile.md のとおり。追加で分かったこと: なし

## REQ-01
- 現行の振る舞い: 登録画面には保管場所の項目がない。登録処理は LostItemService#register で行う [ソース: src/main/java/jp/example/lostitem/service/LostItemService.java:30-48]
- 関係する共通部品: StringUtil#isBlank [ソース: src/main/java/jp/example/common/StringUtil.java:10]
- 影響範囲: register の呼び出し元は LostItemController#register だけ [ソース: src/main/java/jp/example/lostitem/controller/LostItemController.java:55]

## REQ-02
- 現行の振る舞い: 該当なし（メッセージ E0012 は messages.properties に存在しないため新規）
- 確認した箇所: [ソース: src/main/resources/messages.properties:1-40]

## 差異（D）
| D | 内容 | 設計書の記載 | 現行ソース |
|---|---|---|---|
| D-01 | 拾得日の桁数が設計書は8桁、ソースは10桁（yyyy/MM/dd） | [設計書: …!F14] 「8」 | [ソース: …/LostItemForm.java:22] |

## 質問（Q）
| Q | 内容 | 根拠 | 回答 |
|---|---|---|---|

## 調査したファイル
- `src/main/java/jp/example/lostitem/service/LostItemService.java`
```

## ルール
- REQ ごとに `## REQ-xx` の節を作る（01_requirements.md の全 REQ 分）
- 各節に `[ソース: パス:行]` を1つ以上書く。新規で該当がなければ「該当なし」と理由を書く
- パスはソースルートからの相対パス（スラッシュ区切り）。行番号は実際に開いて確認したもの
- 差異（D）では、どちらが正しいかを判断しない
