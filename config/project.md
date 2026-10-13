# 対象プロジェクトの設定

ツールが `key: value` の行を読み取ります。行の形式は変えないでください。

> 対象PJのソースルートは、ここではなく、パッケージ直下の `dev-agents.code-workspace`（name が `"source"` のフォルダの `path`）に書きます。

## 調査の対象外
カンマ区切りで、ソースルートからのフォルダ名を書きます。

exclude: target, bin, .settings, .metadata, node_modules
