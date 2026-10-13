#!/usr/bin/env python3
"""発表資料に出てくる式番号・図番号・表番号が，ノートの見出しにすべてあるかを調べる．

「式の解説」「図の解説」に，資料のすべての式と図を並べたかを確かめるために使う．

使い方:
  python3 check_coverage.py 資料.pdf ノート.md
  python3 check_coverage.py 資料.pdf ノート.md --ignore 1.38 --ignore 図1.2
  python3 check_coverage.py --text 資料.txt ノート.md     （テキストを取り出し済みのとき）

PDF のテキストは pdftotext（Poppler）で取り出す．
見出しにない番号があれば一覧を出して終了コード1で終わる．
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 番号の形（章は1〜99，式は 1.47a のように英小文字の枝番を許す）
NUMBER = r"[1-9]\d?\.\d{1,3}"
EQUATION_PATTERN = re.compile(rf"\(({NUMBER}[a-z]?)\)")
EQUATION_RANGE_PATTERN = re.compile(rf"\(({NUMBER})\)\s*[-–—〜~]\s*\(({NUMBER})\)")
FIGURE_PATTERN = re.compile(rf"(?:図|Figure|Fig\.)\s?({NUMBER})(?![\d.])")
TABLE_PATTERN = re.compile(rf"(?:表|Table)\s?({NUMBER})(?![\d.])")
HEADING_PATTERN = re.compile(r"^#{1,6}\s")
KINDS = ("式", "図", "表")
PREFIXES = {"式": "", "図": "図", "表": "表"}
MAX_RANGE_LENGTH = 30
BRANCH_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def extractPdfText(pdfPath):
  """pdftotext で PDF のテキストを取り出す．"""
  if shutil.which("pdftotext") is None:
    raise RuntimeError("pdftotext が見つかりません．Poppler を入れるか，--text で取り出し済みのテキストを渡してください")
  result = subprocess.run(["pdftotext", "-layout", str(pdfPath), "-"], capture_output=True, text=True)
  if result.returncode != 0:
    raise RuntimeError(f"pdftotext に失敗しました: {result.stderr.strip()}")
  return result.stdout


def uniqueInOrder(items):
  """重複を除き，最初に出た順に並べる．"""
  seen = set()
  ordered = []
  for item in items:
    if item not in seen:
      seen.add(item)
      ordered.append(item)
  return ordered


def expandRanges(text):
  """「(1.54)–(1.57)」のような範囲を，間の番号すべてに広げる．"""
  numbers = []
  for match in EQUATION_RANGE_PATTERN.finditer(text):
    startChapter, startIndex = match.group(1).split(".")
    endChapter, endIndex = match.group(2).split(".")
    if startChapter != endChapter:
      continue
    first, last = int(startIndex), int(endIndex)
    if 0 < last - first <= MAX_RANGE_LENGTH:
      numbers += [f"{startChapter}.{index}" for index in range(first, last + 1)]
  return numbers


def findNumbers(text, expand=False):
  """テキストから式・図・表の番号を種類ごとに集める．"""
  equations = EQUATION_PATTERN.findall(text)
  if expand:
    equations += expandRanges(text)
  return {
    "式": uniqueInOrder(equations),
    "図": uniqueInOrder(FIGURE_PATTERN.findall(text)),
    "表": uniqueInOrder(TABLE_PATTERN.findall(text)),
  }


def headingText(notePath):
  """ノートの見出しの行だけをつなげて返す．"""
  lines = notePath.read_text(encoding="utf-8").splitlines()
  return "\n".join(line for line in lines if HEADING_PATTERN.match(line))


def baseNumber(number):
  """式番号の枝番（1.47a の a）を外す．"""
  return number.rstrip(BRANCH_LETTERS)


def isCovered(kind, number, covered):
  """見出しにその番号があるか．式は枝番を外した番号どうしが同じならよい（(1.47) と (1.47a)）．"""
  if number in covered:
    return True
  if kind == "式":
    return any(baseNumber(item) == baseNumber(number) for item in covered)
  return False


def normalizeIgnore(values):
  """--ignore の値（1.38，式1.38，図1.2，表1.1）を種類と番号の組にする．"""
  ignored = set()
  for value in values:
    for kind in ("図", "表"):
      if value.startswith(kind):
        ignored.add((kind, value[len(kind):]))
        break
    else:
      ignored.add(("式", value.removeprefix("式").strip("()")))
  return ignored


def formatNumbers(kind, numbers):
  """表示用に番号を並べる．"""
  if kind == "式":
    return "，".join(f"({number})" for number in numbers)
  return "，".join(f"{PREFIXES[kind]}{number}" for number in numbers)


def parseArgs():
  parser = argparse.ArgumentParser(description="資料の式・図・表の番号が，ノートの見出しにすべてあるかを調べる")
  parser.add_argument("source", type=Path, help="発表資料の PDF（--text のときは取り出し済みのテキスト）")
  parser.add_argument("note", type=Path, help="調べる Markdown ノート")
  parser.add_argument("--text", action="store_true", help="source を PDF ではなくテキストとして読む")
  parser.add_argument("--ignore", action="append", default=[], help="調べない番号（例：1.38，図1.2）．何度でも指定できる")
  return parser.parse_args()


def main():
  args = parseArgs()
  if args.text:
    sourceText = args.source.read_text(encoding="utf-8")
  else:
    sourceText = extractPdfText(args.source)
  inSource = findNumbers(sourceText)
  inNote = findNumbers(headingText(args.note), expand=True)
  ignored = normalizeIgnore(args.ignore)
  missingCount = 0
  for kind in KINDS:
    missing = [n for n in inSource[kind] if (kind, n) not in ignored and not isCovered(kind, n, inNote[kind])]
    extra = [n for n in inNote[kind] if n not in inSource[kind]]
    print(f"{kind}：資料に{len(inSource[kind])}個，見出しにない{len(missing)}個")
    if missing:
      print(f"  見出しがない：{formatNumbers(kind, missing)}")
    if extra:
      print(f"  （参考）見出しにだけある：{formatNumbers(kind, extra)}")
    missingCount += len(missing)
  if missingCount:
    print(f"\n見出しのない番号が{missingCount}個あります．解説を足すか，対象外なら --ignore で外してください")
    return 1
  print("\n資料の式・図・表は，すべてノートの見出しにあります")
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except (OSError, RuntimeError) as error:
    print(f"エラー: {error}", file=sys.stderr)
    sys.exit(2)
