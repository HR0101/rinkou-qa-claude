# rinkou-qa-claude

書籍輪講やゼミ発表の発表原稿・課題原稿（Markdown ノート）に，想定質問と答えを「できる限り詰めて」作るための Claude Code 用スキルです．
資料のどの文・式・図・記号を突かれても詰まらないことを目標に，質問を洗い出し，次の型でノートの「## 想定質問」節にまとめます．

- 本番前に声に出して練習する**最優先の表**
- 分類ごとにレベル1〜3と★の質問番号を並べた**難易度別の索引**
- 分類ごとの全問と答え（課題ごと，図，表記，前提知識，他の節とのつながり，発展，数値，一問一答）
- **答えに詰まったときの返し方**

作者は，担当範囲の発表原稿で344問，質疑で宿題になった4問の課題原稿で268問をこの型で作りました．

このリポジトリには，原著の本文・図・翻訳や，発表資料そのものは含まれていません．
`skills/rinkou-qa/examples/` には，作者が書いた想定質問の元データの実例（原著の式番号・図番号への言及を含む）だけが入っています．

輪講資料（LaTeX）そのものを作るスキルは [rinkou-handout-builder-claude](https://github.com/HR0101/rinkou-handout-builder-claude) にあります．

## インストール

### プラグインとして導入する

Claude Code で次の2つを実行します．

```text
/plugin marketplace add HR0101/rinkou-qa-claude
/plugin install rinkou-qa@rinkou-qa-claude
```

更新するときは次を実行します．

```text
/plugin marketplace update rinkou-qa-claude
```

### スキルだけを手動で置く

```bash
git clone --depth 1 https://github.com/HR0101/rinkou-qa-claude.git /tmp/rinkou-qa-claude
mkdir -p "$HOME/.claude/skills"
cp -R /tmp/rinkou-qa-claude/skills/rinkou-qa "$HOME/.claude/skills/"
rm -rf /tmp/rinkou-qa-claude
```

導入後に Claude Code がスキルを認識しない場合は，セッションを再起動してください．
プラグインと手動の両方で入れると同じスキルが2つ並ぶので，どちらか一方にしてください．

## 使い方

スキルは説明文にもとづいて自動で読み込まれます．たとえば次のように頼みます．

```text
課題原稿_1.6線形システムの4つの課題.md の想定質問をできる限り詰めて
```

明示的に呼び出すときは，プラグインなら `/rinkou-qa:rinkou-qa`，手動で置いた場合は `/rinkou-qa` と入力します．

対象のノート，対象の資料（tex や PDF），関係するノート（課題の元になった発表原稿など）を伝えると安定します．
メモリに研究室の書式や添削の指摘を残している場合は，それも最初に読みます．

## 同梱スクリプト

### build_qa.py

想定質問の元データ（テキスト）から，ノートの「## 想定質問」節を組み立てて差し替えます．Python 3.9 以上で動き，外部ライブラリは要りません．

```bash
# 差し替えずに，組み立てた節を標準出力に出す
skills/rinkou-qa/scripts/build_qa.py 元データ.txt ノート.md --dry-run

# 差し替える（先にノートと同じフォルダへ ノート.md.bak_YYYYMMDD を作る）
skills/rinkou-qa/scripts/build_qa.py 元データ.txt ノート.md
```

元データは次の形で書きます．質問の番号（Z1，A1，…），最優先の表，難易度別の索引はスクリプトが作ります．

```text
%head
課題資料について聞かれうる質問を集めた（全{{total}}問，{{date}} 更新）．

# A|課題1.1　RC フィルタの振幅特性が滑らかに変化する理由|課題1.1
@2|★!||一言で言うと，なぜ RC フィルタの振幅特性は滑らかなのですか．
キャパシタのインピーダンスが周波数とともに連続的に変わるからです．
@1|-|key=smooth|「滑らか」とはどういう意味ですか．
グラフに段差も角もないことです．
```

`@レベル|フラグ|key=参照キー|質問` の行が質問で，次の行から答えです．フラグの `★` は聞かれやすい質問，`!` は最優先の表に載せる質問です．
答えの中の `@@参照キー@@` は質問番号に置き換わります．
書式の詳細は [skills/rinkou-qa/references/source-format.md](skills/rinkou-qa/references/source-format.md) を見てください．

数式の閉じ忘れ（ドル記号の数が奇数），未定義の参照，区切りの誤り，答えのない質問があると，ノートを書き換えずにエラーで止まります．

## リポジトリ構成

```text
.
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .github/
│   └── workflows/
│       └── validate.yml
├── skills/
│   └── rinkou-qa/
│       ├── SKILL.md
│       ├── examples/
│       │   └── Kadai20261013_source.txt
│       ├── references/
│       │   ├── checklist.md
│       │   └── source-format.md
│       └── scripts/
│           └── build_qa.py
├── tools/
│   └── validate.py
├── CHANGELOG.md
├── LICENSE
└── README.md
```

## 開発者向け

変更を加えたら，公開前に検証してください．

```bash
python3 tools/validate.py
```

plugin.json と marketplace.json，SKILL.md のフロントマターと参照先のファイル，同梱スクリプトの実行権限と構文を確認します．
あわせて，build_qa.py が実例から全問を組み立てられること，ノートの節の外を変えないこと，書式の誤りで止まることを確かめます．
同じ検証が push とプルリクエストのたびに GitHub Actions でも実行されます．

## 著作権上の注意

このスキルは作業の手順を提供するものです．第三者の原著・図・翻訳を再配布する権利を与えるものではありません．
想定質問のノートを共有するときは，原典の引用の範囲，所属機関の規程を確認してください．

## ライセンス

スキル本体と付属スクリプトは [MIT License](LICENSE) で公開します．
