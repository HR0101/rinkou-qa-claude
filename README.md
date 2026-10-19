# rinkou-qa-claude

書籍輪講やゼミ発表の準備ノート（Markdown）を作るための Claude Code 用スキルです．
資料のどの文・式・図・記号を突かれても詰まらないことを目標に，次の4種類のノートを同じ型で作ります．

| ノート | 中身 |
|---|---|
| 自分の発表原稿 | 時間配分，資料のやさしい言い換え，原稿，時間調整，想定質問，資料のすべての式・図・用語の解説 |
| 自分の課題原稿 | 質疑で宿題になった課題を説明する回の時間配分，発表時の注意，記号の読み方，原稿，想定質問，数学の解説 |
| ほかの人の回の解説・質問と逆質問 | 資料のすべての式・図・用語の解説，その人に聞く質問（想定回答つき），質問しなかったときに司会から来る逆質問への答え |
| 回のメモ | 資料とファイルへのリンク，聞いた質問，当日のメモ |

表：このスキルで作るノート．

想定質問と逆質問は，次の型でまとめます．

- 本番前に声に出して練習する**最優先の表**
- 分類ごとにレベル1〜3と★の質問番号を並べた**難易度別の索引**
- 分類ごとの全問と答え（課題・節ごと，図，表記，前提知識，他の節とのつながり，発展，数値，一問一答）
- **答えに詰まったときの返し方**

作者は，担当範囲の発表原稿で344問，質疑で宿題になった4問の課題原稿で268問，ほかの人の回の逆質問で163問（7ページ）と351問（11ページ）をこの型で作りました．

質問が少なくならないよう，資料のページ数と式・図の数から**問数の目安**を決めています（逆質問なら1ページ25問，式1つに5問，図1つに6問以上）．目安に届いているかは同梱のスクリプトで確かめられます．

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
1.6節の発表原稿を作って．資料は 1.6-1.6.3.2_TaroChiba.pdf
課題原稿の想定質問をできる限り詰めて
次の回の〇〇さんの発表の解説と質問，逆質問を作って
```

明示的に呼び出すときは，プラグインなら `/rinkou-qa:rinkou-qa`，手動で置いた場合は `/rinkou-qa` と入力します．

対象のノート，資料（tex や PDF），関係するノート（課題の元になった発表原稿など）を伝えると安定します．
メモリやノートに研究室の書式，添削の指摘，ノートの置き場所の決まりを残している場合は，それを最初に読み，スキルの例より優先します．

## 同梱のひな形

`skills/rinkou-qa/templates/` に，各ノートのひな形があります．

| ファイル | ノート |
|---|---|
| `own-talk.md` | 自分の発表原稿 |
| `assignment-talk.md` | 自分の課題原稿 |
| `peer-notes.md` | ほかの人の回の解説・質問 |
| `peer-reverse-qa_source.txt` | ほかの人の回の逆質問（build_qa.py の元データ） |
| `session-memo.md` | 回のメモ |

表：ひな形の一覧．

## 同梱スクリプト

どちらも Python 3.9 以上で動き，外部ライブラリは要りません．

### build_qa.py

想定質問の元データ（テキスト）から，ノートの「## 想定質問」節を組み立てて差し替えます．

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

### check_coverage.py

発表資料の PDF に出てくる式・図・表の番号が，ノートの見出し（`#### 式(1.66)　…`，`### 図1.15　…`）にすべてあるかを調べます．「資料のすべての式と図を解説する」ノートの抜けを見つけるために使います．

```bash
skills/rinkou-qa/scripts/check_coverage.py 資料.pdf ノート.md
skills/rinkou-qa/scripts/check_coverage.py 資料.pdf ノート.md --ignore 1.38 --ignore 図1.2
```

見出しにない番号があれば一覧を出して終了コード1で終わります．式の枝番（`(1.47a)` と `(1.47)`）と，見出しの範囲（`式(1.54)–(1.57)`）も扱います．
PDF のテキストは `pdftotext`（Poppler）で取り出します．取り出し済みのテキストを `--text` で渡すこともできます．

**問数の確認（`--qa`）**：想定質問・逆質問の元データ（`.txt`），組み立てたノート，番号付きの質問を並べた解説・質問ファイル（`.md`）の問数が，目安に届いているかを調べます．

```bash
# 逆質問：1ページ25問，式1つに5問，図1つに6問（既定値）
skills/rinkou-qa/scripts/check_coverage.py 資料.pdf ノート.md --qa 元データ.txt
# 発表者への質問：1ページ5問，式・図それぞれに1問
skills/rinkou-qa/scripts/check_coverage.py 資料.pdf 解説・質問.md --qa 解説・質問.md --min-per-page 5 --min-per-equation 1 --min-per-figure 1
```

総数と，目安に届かない式・図（「(2.11) 1問」など）を一覧にし，届いていなければ終了コード1で終わります．質問か答えに式番号・図番号が出てくる問を，その式・図に触れる問として数えます．ページ数は改ページから数え，`--pages` で指定もできます．

**文の書き出し（`--sentences`）**：資料の文を `p.1-01` の形で番号付きで書き出します．1文に1問以上を立てるための作業表です．

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
│       │   ├── own-talk.md
│       │   ├── peer-notes.md
│       │   └── source-format.md
│       ├── scripts/
│       │   ├── build_qa.py
│       │   └── check_coverage.py
│       └── templates/
│           ├── assignment-talk.md
│           ├── own-talk.md
│           ├── peer-notes.md
│           ├── peer-reverse-qa_source.txt
│           └── session-memo.md
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

plugin.json と marketplace.json，SKILL.md のフロントマター，スキル内の Markdown のリンク先，同梱スクリプトの実行権限と構文を確認します．
あわせて，build_qa.py が実例とひな形から全問を組み立てられること，ノートの節の外を変えないこと，書式の誤りで止まること，check_coverage.py が見出しの抜けと問数の不足を見つけ，資料の文を書き出せることを確かめます．
同じ検証が push とプルリクエストのたびに GitHub Actions でも実行されます．

## 著作権上の注意

このスキルは作業の手順を提供するものです．第三者の原著・図・翻訳を再配布する権利を与えるものではありません．
ノートを共有するときは，原典の引用の範囲，所属機関の規程を確認してください．

## ライセンス

スキル本体と付属スクリプトは [MIT License](LICENSE) で公開します．
