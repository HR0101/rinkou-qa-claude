#!/usr/bin/env python3
"""プラグインとスキルの定義ファイルを検証する．

配布前に次を確認する．

- plugin.json と marketplace.json がJSONとして妥当であること
- 必須フィールドが存在し，プラグイン名が両者で一致すること
- SKILL.md のフロントマターに name と description があること
- スキル名がディレクトリ名と一致すること
- SKILL.md から参照される相対パスのファイルが実在すること
- 同梱スクリプトに実行権限があり，構文エラーがないこと
- build_qa.py が同梱の実例とひな形から全問を組み立てられ，ノートの節の外を
  変えず，書式の誤りではエラーで止まること
- build_qa.py が %levels 5 で5段階の索引を作り，配分が偏れば警告すること
- check_coverage.py が見出しにない式・図を見つけ，すべてあれば成功すること
- check_coverage.py の --qa が問数の不足を見つけ（元データと番号付きの質問の両方），
  目安に届けば成功し，--sentences が資料の文を番号付きで書き出すこと
- check_coverage.py の --qa が，5段階のレベルの配分（各レベルの割合，レベル1〜2の割合）の
  不足を元データとノートの小見出しの両方から見つけること
- check_coverage.py の --min-open-share が，答えが「はい」で始まる質問ばかりのときに
  説明してもらう質問の不足を見つけること
- check_coverage.py の --sentences が，手順の文と理由が書かれていない文に印を付けること
- check_coverage.py の --min-deep-per-page が，考えて答える質問（〔組み合わせ〕などの印）の不足を見つけること
- check_coverage.py の --require-intent が，「意図：」「言い換え：」の行が欠けた質問を見つけること
- check_coverage.py の --quality が，重複の候補と二つ以上聞いている質問を見つけ，終了コードを変えないこと
- スキル内のすべての Markdown から張った相対リンクの先が実在すること

使い方:
    python3 tools/validate.py
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# リポジトリのルート（このファイルの1つ上）
ROOT = Path(__file__).resolve().parent.parent

# build_qa.py の検査に使う値
BUILD_SCRIPT = ROOT / "skills" / "rinkou-qa" / "scripts" / "build_qa.py"
EXAMPLES_DIR = ROOT / "skills" / "rinkou-qa" / "examples"
TEMPLATES_DIR = ROOT / "skills" / "rinkou-qa" / "templates"
COVERAGE_SCRIPT = ROOT / "skills" / "rinkou-qa" / "scripts" / "check_coverage.py"
FIXED_DATE = "2000-01-01"
QUESTION_LINE = re.compile(r"^@\d+\|", re.M)
BUILT_QUESTION_LINE = re.compile(r"^\*\*[A-Z]+\d+．", re.M)
NOTE_HEAD = "# ノート\n\n本文．\n\n"
NOTE_TAIL = "\n---\n\n## 解説\n\n解説の本文．\n"

# 検証結果を蓄積する
errors: list[str] = []
warnings: list[str] = []


def fail(message: str) -> None:
  """致命的な問題を記録する．"""
  errors.append(message)


def warn(message: str) -> None:
  """修正が望ましい問題を記録する．"""
  warnings.append(message)


def loadJson(path: Path) -> dict | None:
  """JSONファイルを読み込む．読めない場合はNoneを返す．"""
  if not path.exists():
    fail(f"{path.relative_to(ROOT)} が存在しない")
    return None
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except json.JSONDecodeError as error:
    fail(f"{path.relative_to(ROOT)} のJSONが不正: {error}")
    return None


def parseFrontmatter(path: Path) -> dict[str, str] | None:
  """SKILL.md 等のYAMLフロントマターを最小限の規則で読み取る．

  外部ライブラリに依存しないため，`key: value` の1行形式のみを扱う．
  """
  if not path.exists():
    fail(f"{path.relative_to(ROOT)} が存在しない")
    return None
  text = path.read_text(encoding="utf-8")
  match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
  if not match:
    fail(f"{path.relative_to(ROOT)} にフロントマターがない")
    return None
  fields: dict[str, str] = {}
  for line in match.group(1).split("\n"):
    if not line.strip() or line.lstrip().startswith("#"):
      continue
    keyValue = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
    if keyValue:
      fields[keyValue.group(1)] = keyValue.group(2).strip()
  return fields


def checkPluginManifest() -> str | None:
  """plugin.json を検証し，プラグイン名を返す．"""
  manifest = loadJson(ROOT / ".claude-plugin" / "plugin.json")
  if manifest is None:
    return None
  # name はClaude Codeがプラグインを識別するために必須
  if "name" not in manifest:
    fail("plugin.json に name がない")
    return None
  for field in ("version", "description"):
    if field not in manifest:
      warn(f"plugin.json に {field} がない")
  return manifest["name"]


def checkMarketplace(pluginName: str | None) -> None:
  """marketplace.json を検証する．"""
  marketplace = loadJson(ROOT / ".claude-plugin" / "marketplace.json")
  if marketplace is None:
    return
  for field in ("name", "owner", "plugins"):
    if field not in marketplace:
      fail(f"marketplace.json に {field} がない")
  plugins = marketplace.get("plugins", [])
  if not plugins:
    fail("marketplace.json の plugins が空")
    return
  names = [plugin.get("name") for plugin in plugins]
  if pluginName and pluginName not in names:
    fail(f"marketplace.json に plugin.json と同じ名前 {pluginName} の登録がない")
  for plugin in plugins:
    source = plugin.get("source")
    if source is None:
      fail(f"marketplace.json の {plugin.get('name')} に source がない")
      continue
    # source がリポジトリ内の相対パスなら実在を確認する
    if isinstance(source, str) and source.startswith("."):
      if not (ROOT / source).exists():
        fail(f"marketplace.json の source が存在しない: {source}")


def checkSkills() -> None:
  """skills/ 配下の各スキルを検証する．"""
  skillsDir = ROOT / "skills"
  if not skillsDir.is_dir():
    fail("skills/ ディレクトリがない")
    return
  skillDirs = [path for path in skillsDir.iterdir() if path.is_dir()]
  if not skillDirs:
    fail("skills/ にスキルが1つもない")
    return
  for skillDir in skillDirs:
    skillFile = skillDir / "SKILL.md"
    fields = parseFrontmatter(skillFile)
    if fields is None:
      continue
    # name と description はスキルの読み込み判断に必須
    for field in ("name", "description"):
      if field not in fields:
        fail(f"{skillFile.relative_to(ROOT)} のフロントマターに {field} がない")
    if fields.get("name") and fields["name"] != skillDir.name:
      fail(
        f"スキル名 {fields['name']} がディレクトリ名 {skillDir.name} と一致しない"
      )
    # description が長すぎるとスキル選択の判断材料として扱いにくい
    description = fields.get("description", "")
    if len(description) > 1024:
      warn(f"{skillFile.relative_to(ROOT)} の description が長い（{len(description)}文字）")
    for markdownFile in sorted(skillDir.rglob("*.md")):
      checkSkillLinks(markdownFile)


def checkSkillLinks(skillFile: Path) -> None:
  """スキル内の Markdown の相対リンクと参照パスの実在を確認する．"""
  text = skillFile.read_text(encoding="utf-8")
  base = skillFile.parent
  # Markdownリンクと，コードブロック内の scripts/... 形式の呼び出しを拾う
  targets = set(re.findall(r"\]\((?!https?://)([^)#]+)\)", text))
  targets |= set(re.findall(r"(?:^|\s)(scripts/[\w./-]+)", text, re.M))
  for target in targets:
    if not (base / target).exists():
      fail(f"{skillFile.relative_to(ROOT)} が参照する {target} が存在しない")


def checkScripts() -> None:
  """同梱スクリプトの実行権限と構文を確認する．"""
  for path in sorted(ROOT.glob("skills/*/scripts/*")):
    if not path.is_file():
      continue
    if not os.access(path, os.X_OK):
      fail(f"{path.relative_to(ROOT)} に実行権限がない")
    if path.suffix == ".py":
      try:
        # バイトコードを残さないよう一時ディレクトリへ出力する
        with tempfile.TemporaryDirectory() as tmp:
          py_compile.compile(
            str(path), cfile=str(Path(tmp) / "out.pyc"), doraise=True
          )
      except py_compile.PyCompileError as error:
        fail(f"{path.relative_to(ROOT)} に構文エラー: {error}")
    if path.suffix == ".sh":
      result = subprocess.run(
        ["bash", "-n", str(path)], capture_output=True, text=True
      )
      if result.returncode != 0:
        fail(f"{path.relative_to(ROOT)} に構文エラー: {result.stderr.strip()}")


def runBuild(*args: str) -> subprocess.CompletedProcess:
  """build_qa.py を実行する．"""
  return subprocess.run(
    [sys.executable, "-I", str(BUILD_SCRIPT), *args],
    capture_output=True, text=True,
  )


def checkExamples() -> None:
  """同梱の実例とひな形から，元データの全問が節に組み立てられることを確認する．"""
  examples = sorted(EXAMPLES_DIR.glob("*.txt")) + sorted(TEMPLATES_DIR.glob("*_source.txt"))
  if not examples:
    warn("examples/ に元データの実例がない")
  for example in examples:
    result = runBuild(str(example), "--date", FIXED_DATE)
    name = example.relative_to(ROOT)
    if result.returncode != 0:
      fail(f"{name} から節を組み立てられない: {result.stderr.strip()}")
      continue
    expected = len(QUESTION_LINE.findall(example.read_text(encoding="utf-8")))
    built = len(BUILT_QUESTION_LINE.findall(result.stdout))
    if built != expected:
      fail(f"{name} の質問 {expected}問のうち {built}問しか組み立てられていない")


def checkNoteReplacement(tmp: Path) -> None:
  """ノートの「## 想定質問」節だけが差し替わり，前後が変わらないことを確認する．"""
  source = tmp / "source.txt"
  source.write_text("%head\n全{{total}}問．\n# A|分類\n@1|★!||質問\n答え．\n", encoding="utf-8")
  note = tmp / "note.md"
  note.write_text(NOTE_HEAD + "## 想定質問\n\n古い節．\n" + NOTE_TAIL, encoding="utf-8")
  result = runBuild(str(source), str(note), "--date", FIXED_DATE)
  if result.returncode != 0:
    fail(f"ノートの節を差し替えられない: {result.stderr.strip()}")
    return
  text = note.read_text(encoding="utf-8")
  if not text.startswith(NOTE_HEAD + "## 想定質問\n") or not text.endswith(NOTE_TAIL):
    fail("ノートの「## 想定質問」節の外が変わっている")
  if "古い節" in text or "**A1．★質問**" not in text:
    fail("ノートの「## 想定質問」節が差し替わっていない")
  if not list(tmp.glob("note.md.bak_*")):
    fail("差し替え前のバックアップが作られていない")


def checkBrokenSources(tmp: Path) -> None:
  """書式の誤りがある元データで，エラーで止まることを確認する．"""
  brokenSources = {
    "ドル記号の閉じ忘れ": "# A|分類\n@1|-||質問 $x\n答え．\n",
    "未定義の参照キー": "# A|分類\n@1|-||質問\n@@nokey@@ を見る．\n",
    "区切りの数の誤り": "# A|分類\n@1|-|質問\n答え．\n",
    "答えのない質問": "# A|分類\n@1|-||質問\n",
    "宣言のないレベル4": "# A|分類\n@4|-||質問\n答え．\n",
    "%levels の値の誤り": "%levels 4\n# A|分類\n@1|-||質問\n答え．\n",
    "分類の後の %levels": "# A|分類\n@1|-||質問\n答え．\n%levels 5\n",
  }
  for label, content in brokenSources.items():
    source = tmp / "broken.txt"
    source.write_text(content, encoding="utf-8")
    if runBuild(str(source)).returncode == 0:
      fail(f"build_qa.py が{label}でも成功終了している")


def fiveLevelSource(levels: list[int]) -> str:
  """指定したレベルの質問を1問ずつ並べた，5段階の元データを返す．"""
  questions = "".join(f"@{level}|-||質問{index}\n答え．\n" for index, level in enumerate(levels, 1))
  return "%levels 5\n# A|分類\n" + questions


def checkFiveLevels(tmp: Path) -> None:
  """%levels 5 で5段階の索引ができ，配分が偏ると警告が出ることを確認する．"""
  source = tmp / "five.txt"
  source.write_text(fiveLevelSource([1, 2, 3, 4, 5]), encoding="utf-8")
  result = runBuild(str(source), "--date", FIXED_DATE)
  header = "| 分類 | 問数 | レベル1（超基礎） | レベル2（基礎） | レベル3（標準） | レベル4（応用） | レベル5（発展） | ★ |"
  if result.returncode != 0 or header not in result.stdout:
    fail(f"build_qa.py が %levels 5 で5段階の索引を作っていない: {result.stderr.strip()}")
  elif "届きません" in result.stderr:
    fail("build_qa.py が，5段階の配分がそろっているのに警告している")
  source.write_text(fiveLevelSource([1, 1, 2]), encoding="utf-8")
  skewed = runBuild(str(source), "--date", FIXED_DATE)
  if skewed.returncode != 0 or "レベル5（発展）が0問" not in skewed.stderr:
    fail("build_qa.py が，5段階の配分の偏り（レベル3〜5がない）を警告していない")


def checkBuildScript() -> None:
  """想定質問の節を組み立てるスクリプトの動作を確認する．"""
  if not BUILD_SCRIPT.exists():
    fail(f"{BUILD_SCRIPT.relative_to(ROOT)} が存在しない")
    return
  checkExamples()
  with tempfile.TemporaryDirectory() as tmp:
    checkNoteReplacement(Path(tmp))
    checkBrokenSources(Path(tmp))
    checkFiveLevels(Path(tmp))


def runCoverageProcess(sourceText: str, noteText: str, tmp: Path, *extra: str) -> subprocess.CompletedProcess:
  """取り出し済みのテキストとノートで check_coverage.py を実行する．"""
  source = tmp / "source.txt"
  note = tmp / "coverage_note.md"
  source.write_text(sourceText, encoding="utf-8")
  note.write_text(noteText, encoding="utf-8")
  return subprocess.run(
    [sys.executable, "-I", str(COVERAGE_SCRIPT), "--text", str(source), str(note), *extra],
    capture_output=True, text=True,
  )


def runCoverage(sourceText: str, noteText: str, tmp: Path, *extra: str) -> int:
  """check_coverage.py を実行し，終了コードを返す．"""
  return runCoverageProcess(sourceText, noteText, tmp, *extra).returncode


def checkCoverageScript() -> None:
  """資料の式・図が見出しにあるかを調べるスクリプトの動作を確認する．"""
  if not COVERAGE_SCRIPT.exists():
    fail(f"{COVERAGE_SCRIPT.relative_to(ROOT)} が存在しない")
    return
  sourceText = "式 (1.47a) と (1.55) を使う．図 1.15 に示す．\n"
  fullNote = "#### 式(1.47)　畳み込み\n#### 式(1.54)–(1.57)　歪みのない伝送\n### 図1.15　スペクトル\n"
  missingFigure = "#### 式(1.47)　畳み込み\n#### 式(1.54)–(1.57)　歪みのない伝送\n本文に 図1.15 とだけ書く\n"
  with tempfile.TemporaryDirectory() as tmp:
    if runCoverage(sourceText, fullNote, Path(tmp)) != 0:
      fail("check_coverage.py が，すべて見出しにあるのに失敗している（枝番・範囲の扱い）")
    if runCoverage(sourceText, missingFigure, Path(tmp)) != 1:
      fail("check_coverage.py が，見出しにない図を見つけられていない")
    if runCoverage(sourceText, missingFigure, Path(tmp), "--ignore", "図1.15") != 0:
      fail("check_coverage.py の --ignore が効いていない")
    checkQuestionCounts(Path(tmp), sourceText, fullNote)


def checkQuestionCounts(tmp: Path, sourceText: str, fullNote: str) -> None:
  """--qa が問数の不足を見つけ，目安に届けば成功し，--sentences が文を書き出すことを確認する．"""
  twoPages = sourceText + "\f2ページ目の文です．式 (1.55) をもう一度使う．\n"
  fewSource = tmp / "few.txt"
  fewSource.write_text("# A|分類\n@1|-||式(1.55)は何ですか．\n答え．\n", encoding="utf-8")
  enoughSource = tmp / "enough.txt"
  enoughSource.write_text(
    "# A|分類\n@1|-||式(1.55)は何ですか．\n答え．\n@1|-||図1.15は何ですか．\n答え．\n"
    "@1|-||式(1.47a)は何ですか．\n答え．\n@1|-||ほかの質問．\n答え．\n%tail\n式(1.55)の説明は数えない．\n",
    encoding="utf-8",
  )
  small = ("--min-per-page", "2", "--min-per-equation", "1", "--min-per-figure", "1")
  if runCoverage(twoPages, fullNote, tmp, "--qa", str(fewSource), *small) != 1:
    fail("check_coverage.py の --qa が，問数の不足を見つけられていない")
  if runCoverage(twoPages, fullNote, tmp, "--qa", str(enoughSource), *small) != 0:
    fail("check_coverage.py の --qa が，目安に届いているのに失敗している")
  numbered = tmp / "numbered.md"
  numbered.write_text(
    "## 6. 質問\n\n### 6-1. 節\n\n1. 【式(1.55)】質問．\n   - → 答え．\n2. 【図1.15】質問．\n"
    "3. 【式(1.47a)】質問．\n4. 質問．\n\n## 使い分け\n\n1. 数えない．\n",
    encoding="utf-8",
  )
  result = runCoverageProcess(twoPages, fullNote, tmp, "--qa", str(numbered), *small)
  if result.returncode != 0 or "全4問" not in result.stdout:
    fail("check_coverage.py の --qa が，番号付きの質問（質問の節だけ）を正しく数えていない")
  sentences = runCoverageProcess(twoPages, fullNote, tmp, "--sentences")
  if sentences.returncode != 0 or "p.2-01" not in sentences.stdout:
    fail("check_coverage.py の --sentences が，ページごとの文を書き出していない")
  procedure = "まず信号を高い率で標本化する．次に標本化率を下げる．帯域が広いため標本化率を上げる．ステップ幅は1 Vである．\n"
  marked = runCoverageProcess(procedure, fullNote, tmp, "--sentences").stdout
  if "p.1-01 〔手順〕" not in marked or "p.1-02 〔手順〕〔理由なし〕" not in marked:
    fail("check_coverage.py の --sentences が，手順の文と理由が書かれていない文に印を付けていない")
  if "p.1-03 〔" in marked or "p.1-04 〔" in marked:
    fail("check_coverage.py の --sentences が，理由のある文やステップ幅の文にまで印を付けている")
  checkLevelCounts(tmp, twoPages, fullNote, small)


def checkLevelCounts(tmp: Path, sourceText: str, fullNote: str, small: tuple[str, ...]) -> None:
  """--qa が5段階のレベルの配分を，元データとノートの小見出しの両方から調べることを確認する．"""
  mentions = "@1|-||式(1.55)，図1.15，式(1.47a)の質問．\n答え．\n"
  skewed = tmp / "skewed.txt"
  skewed.write_text(fiveLevelSource([1, 1, 2]) + mentions, encoding="utf-8")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(skewed), *small) != 1:
    fail("check_coverage.py の --qa が，元データのレベルの偏り（レベル3〜5がない）を見つけていない")
  balanced = tmp / "balanced.txt"
  balanced.write_text(fiveLevelSource([1, 2, 3, 4, 5]) + mentions, encoding="utf-8")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(balanced), *small) != 0:
    fail("check_coverage.py の --qa が，レベルがそろった元データで失敗している")
  leveled = tmp / "leveled.md"
  leveled.write_text(
    "## 6. 質問\n\n### 6-1. レベル1（言葉の確認）\n\n1. 【式(1.55)】質問．\n   - → 答え．\n2. 【図1.15】質問．\n"
    "\n### 6-2. レベル2（読み取り）\n\n3. 【式(1.47a)】質問．\n\n### 6-3. レベル3（理由）\n\n4. 質問．\n"
    "\n### 6-4. レベル4（式・数値・つながり）\n\n5. 質問．\n\n### 6-5. レベル5（発展・誤り）\n\n6. 質問．\n"
    "\n## 7. 表記・文体の指摘\n\n7. 指摘．\n",
    encoding="utf-8",
  )
  result = runCoverageProcess(sourceText, fullNote, tmp, "--qa", str(leveled), *small)
  if result.returncode != 0 or "レベル1 2問" not in result.stdout or "レベルなし 1問" not in result.stdout:
    fail("check_coverage.py の --qa が，ノートの小見出しからレベルを読めていない")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(leveled), *small, "--min-easy-share", "0.9") != 1:
    fail("check_coverage.py の --min-easy-share が，易しい質問の不足を見つけていない")
  checkAnswerKinds(tmp, sourceText, fullNote, small)


def checkAnswerKinds(tmp: Path, sourceText: str, fullNote: str, small: tuple[str, ...]) -> None:
  """--min-open-share が，「はい」で答える質問と説明してもらう質問の割合を調べることを確認する．"""
  answers = tmp / "answers.md"
  answers.write_text(
    "## 6. 質問\n\n1. 【式(1.55)】〜ですね．\n   - → はい．\n2. 【図1.15】〜という理解でよいですか．\n   - → はい．補足．\n"
    "3. 【式(1.47a)】〇〇とは何ですか．\n   - → 〜のこと．\n4. なぜですか．\n   - → 〜だから．\n\n"
    "## 7. 表記・文体の指摘\n\n5. 指摘（答えの行なし）．\n",
    encoding="utf-8",
  )
  result = runCoverageProcess(sourceText, fullNote, tmp, "--qa", str(answers), *small, "--min-open-share", "0.5")
  if result.returncode != 0 or "「はい」で答える質問 2問，説明してもらう質問 2問" not in result.stdout:
    fail("check_coverage.py が，「はい」で答える質問と説明してもらう質問を正しく数えていない")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(answers), *small, "--min-open-share", "0.6") != 1:
    fail("check_coverage.py の --min-open-share が，説明してもらう質問の不足を見つけていない")
  deep = tmp / "deep.md"
  deep.write_text(
    "## 6. 質問\n\n1. 〔もし〕【式(1.55)】〜を変えるとどうなりますか．\n   - → 〜．\n"
    "2. 〔組み合わせ〕【図1.15】〜のとき〜はどうなりますか．\n   - → 〜．\n"
    "3. 【式(1.47a)】〇〇とは何ですか．\n   - → 〜のこと．\n4. 〔理由なし〕は印ではない．\n   - → 〜．\n",
    encoding="utf-8",
  )
  result = runCoverageProcess(sourceText, fullNote, tmp, "--qa", str(deep), *small, "--min-deep-per-page", "1")
  if result.returncode != 0 or "：2問" not in result.stdout:
    fail("check_coverage.py が，考えて答える質問（印付き）を正しく数えていない")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(deep), *small, "--min-deep-per-page", "2") != 1:
    fail("check_coverage.py の --min-deep-per-page が，考えて答える質問の不足を見つけていない")
  intents = tmp / "intents.md"
  complete = (
    "## 6. 質問\n\n1. 【式(1.55)】〜はどうなりますか．\n   - → 〜．\n   - 意図：〜を確かめたい．\n   - 言い換え：〜という意味です．\n"
    "2. 【図1.15】〜は何ですか．\n   - → 〜．\n   - 意図：〜が気になった．\n   - 言い換え：〜という意味です．\n"
    "3. 【式(1.47a)】〜ですか．\n   - → 〜．\n   - 意図：〜．\n   - 言い換え：〜．\n\n## 7. 表記・文体の指摘\n\n4. 指摘．\n"
  )
  intents.write_text(complete, encoding="utf-8")
  if runCoverage(sourceText, fullNote, tmp, "--qa", str(intents), *small, "--require-intent") != 0:
    fail("check_coverage.py の --require-intent が，意図と言い換えがそろっているのに失敗している")
  intents.write_text(complete.replace("   - 言い換え：〜という意味です．\n2.", "\n2."), encoding="utf-8")
  result = runCoverageProcess(sourceText, fullNote, tmp, "--qa", str(intents), *small, "--require-intent")
  if result.returncode != 1 or "欠けている番号：1．" not in result.stdout:
    fail("check_coverage.py の --require-intent が，言い換えの欠けた質問を見つけていない")
  quality = tmp / "quality.md"
  quality.write_text(
    "## 6. 質問\n\n1. 【式(1.55)】入力の帯域幅を半分にすると，出力の帯域幅はどうなりますか．\n   - → 〜．\n"
    "2. 【式(1.55)】入力の帯域幅を半分にすると，出力の帯域幅はどうなりますか？\n   - → 〜．\n"
    "3. 【図1.15】〜は何ですか．それはなぜですか．\n   - → 〜．\n4. 【式(1.47a)】〜はいくらですか．\n   - → 〜．\n",
    encoding="utf-8",
  )
  result = runCoverageProcess(sourceText, fullNote, tmp, "--qa", str(quality), *small, "--quality")
  if result.returncode != 0:
    fail("check_coverage.py の --quality が，終了コードを変えている")
  if "1と2" not in result.stdout or "二つ以上聞いている（一問一義にする）：1問" not in result.stdout:
    fail("check_coverage.py の --quality が，重複の候補や二つ以上聞いている質問を見つけていない")


def main() -> int:
  """すべての検証を実行し，結果を表示する．"""
  pluginName = checkPluginManifest()
  checkMarketplace(pluginName)
  checkSkills()
  checkScripts()
  checkBuildScript()
  checkCoverageScript()

  for message in warnings:
    print(f"警告: {message}")
  for message in errors:
    print(f"エラー: {message}")

  if errors:
    print(f"\n検証失敗: エラー{len(errors)}件，警告{len(warnings)}件")
    return 1
  print(f"検証成功: 警告{len(warnings)}件")
  return 0


if __name__ == "__main__":
  sys.exit(main())
