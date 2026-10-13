# 対象プロジェクトの設定

ツールが `key: value` の行を読み取ります。行の形式は変えないでください。

## ソースルート
pom.xml があるフォルダを、絶対パスで書きます（区切りは `/`）。ソースはコピーせず、Eclipse のワークスペースにある実物を参照します。
同じフォルダを、VS Code のワークスペースの2つ目のフォルダにも登録してください（`templates/dev-agents.code-workspace`）。

source_root: C:/pleiades/2026-06/workspace/<PJ名>

## 調査の対象外
カンマ区切りで、ソースルートからのフォルダ名を書きます。

exclude: target, bin, .settings, .metadata, node_modules
