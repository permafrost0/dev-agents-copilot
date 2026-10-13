# 出力形式：実装メモ（work/<機能名>/_ai/<IU>/impl.md）

## 通常

```markdown
# 実装メモ：IU-02
## 変更箇所
| No | ファイル | 変更内容 | REQ | 根拠 |
|---|---|---|---|---|
| 1 | `src/main/resources/jp/example/lostitem/LostItemMapper.xml` | INSERT 文に hokan_basho 列を追加 | REQ-01 | [設計書: 詳細設計書（落としもの）.xlsx/【落としもの登録】画面項目定義!B12:J12] |

## 倣った既存実装
- [ソース: src/main/resources/jp/example/lostitem/LostItemMapper.xml:20-30]（列の並べ方と #{} の書き方）

## 使った共通部品
- なし（計画どおり）

## 意図
- （diff-review はこの欄を判定に使わない。人向けのメモ）

## テスト観点
- 保管場所を入力して登録すると、DB に保存される
```

## 中断する場合

```markdown
# 実装メモ：IU-02
## 中断
| Q | 内容 | 根拠 | 回答 |
|---|---|---|---|
| Q-10 | 保管場所の列を追加するには LostItem.java（対象ファイル外）の変更も必要 | [ソース: src/main/java/…/LostItem.java:10-30] | |
```

- 人は回答を記入するか、②実装計画を見直す（`gate.py reopen <機能名> plan`）

## ルール
- 『変更箇所』の各行に REQ と `[設計書: …]` を書く（形式チェックで確認される）
- ファイルはソースルートからの相対パス
- test_viewpoints.md には `- [IU-02] …` の形で追記する
