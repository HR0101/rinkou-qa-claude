#!/usr/bin/env python3
"""プラグインとスキルの定義ファイルを検証する．

配布前に次を確認する．

- plugin.json と marketplace.json がJSONとして妥当であること
- 必須フィールドが存在し，プラグイン名が両者で一致すること
- SKILL.md のフロントマターに name と description があること
- スキル名がディレクトリ名と一致すること
- SKILL.md から参照される相対パスのファイルが実在すること
- 同梱スクリプトに実行権限があり，構文エラーがないこと
- build_qa.py が同梱の実例から全問を組み立てられ，ノートの節の外を変えず，
  書式の誤りではエラーで止まること

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
    checkSkillLinks(skillFile)


def checkSkillLinks(skillFile: Path) -> None:
  """SKILL.md 内の相対リンクと参照パスの実在を確認する．"""
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
  """同梱の実例から，元データの全問が節に組み立てられることを確認する．"""
  examples = sorted(EXAMPLES_DIR.glob("*.txt"))
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
  }
  for label, content in brokenSources.items():
    source = tmp / "broken.txt"
    source.write_text(content, encoding="utf-8")
    if runBuild(str(source)).returncode == 0:
      fail(f"build_qa.py が{label}でも成功終了している")


def checkBuildScript() -> None:
  """想定質問の節を組み立てるスクリプトの動作を確認する．"""
  if not BUILD_SCRIPT.exists():
    fail(f"{BUILD_SCRIPT.relative_to(ROOT)} が存在しない")
    return
  checkExamples()
  with tempfile.TemporaryDirectory() as tmp:
    checkNoteReplacement(Path(tmp))
    checkBrokenSources(Path(tmp))


def main() -> int:
  """すべての検証を実行し，結果を表示する．"""
  pluginName = checkPluginManifest()
  checkMarketplace(pluginName)
  checkSkills()
  checkScripts()
  checkBuildScript()

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
