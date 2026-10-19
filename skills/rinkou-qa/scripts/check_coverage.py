#!/usr/bin/env python3
"""発表資料に出てくる式番号・図番号・表番号が，ノートの見出しにすべてあるかを調べる．

「式の解説」「図の解説」に，資料のすべての式と図を並べたかを確かめるために使う．
--qa を付けると，想定質問・逆質問・発表者への質問が，資料のページ数と式・図の数に
見合うだけあるか（問数の目安）も調べる．--sentences は資料の文を番号付きで書き出す．

使い方:
  python3 check_coverage.py 資料.pdf ノート.md
  python3 check_coverage.py 資料.pdf ノート.md --ignore 1.38 --ignore 図1.2
  python3 check_coverage.py --text 資料.txt ノート.md     （テキストを取り出し済みのとき）
  python3 check_coverage.py 資料.pdf ノート.md --qa 元データ.txt
  python3 check_coverage.py 資料.pdf ノート.md --qa 解説・質問.md --min-per-page 5 --min-per-equation 1 --min-per-figure 1
  python3 check_coverage.py 資料.pdf ノート.md --sentences

PDF のテキストは pdftotext（Poppler）で取り出す．
見出しにない番号があるか，--qa の問数が目安に届かなければ，一覧を出して終了コード1で終わる．
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

# 問数の目安（逆質問・想定質問の既定値．発表者への質問では --min-per-page などで下げる）
DEFAULT_MIN_PER_PAGE = 25
DEFAULT_MIN_PER_EQUATION = 5
DEFAULT_MIN_PER_FIGURE = 6
# 質問のまとまりの始まり（元データの @行，組み立てた節の **A1．，番号付きの質問）
SOURCE_QUESTION = re.compile(r"^@\d+\|")
BUILT_QUESTION = re.compile(r"^\*\*[A-Z]+\d+．")
NUMBERED_QUESTION = re.compile(r"^\d+\.\s")
BLOCK_END = re.compile(r"^(#{1,6}\s|# |%)")
QUESTION_SECTION_WORDS = ("質問", "指摘")
# 文の区切り（全角・半角の句点）と，文として数えない短すぎる断片の長さ
SENTENCE_END = re.compile(r"(?<=[．。])")
MIN_SENTENCE_LENGTH = 8
CJK_GAP = re.compile(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])")
MULTI_SPACE = re.compile(r"\s{2,}")


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


def countPages(sourceText):
  """pdftotext の改ページ（\\f）から資料のページ数を数える．"""
  pages = [page for page in sourceText.split("\f") if page.strip()]
  return max(len(pages), 1)


def splitSourceBlocks(lines):
  """元データ（@行で始まる質問）を，質問ごとのテキストに分ける．

  分類の行（# ）や自由記述のブロック（%head など）が来たら，次の質問まで数えない．
  """
  blocks = []
  active = False
  for line in lines:
    if SOURCE_QUESTION.match(line):
      blocks.append(line)
      active = True
    elif BLOCK_END.match(line):
      active = False
    elif active and line.strip():
      blocks[-1] += "\n" + line
  return blocks


def splitNoteBlocks(lines):
  """Markdown のノートを質問ごとのテキストに分ける．

  組み立てた節（**A1．）があればそれを，なければ見出し2（## ）に「質問」「指摘」を含む節の
  番号付きの項目（1. 2. …）を，1問として数える．小見出し（### 6-1 など）の下も同じ節とみなす．
  """
  if any(BUILT_QUESTION.match(line) for line in lines):
    starter, inSection = BUILT_QUESTION, (lambda heading: True)
  else:
    starter = NUMBERED_QUESTION
    inSection = lambda heading: any(word in heading for word in QUESTION_SECTION_WORDS)
  blocks = []
  section = ""
  current = None
  for line in lines:
    if HEADING_PATTERN.match(line):
      if line.startswith("## ") or line.startswith("# "):
        section = line
      current = None
      continue
    if starter.match(line) and inSection(section):
      blocks.append(line)
      current = len(blocks) - 1
    elif current is not None and line.strip():
      blocks[current] += "\n" + line
  return blocks


def loadQuestionBlocks(path):
  """元データ（.txt）かノート（.md）から，質問ごとのテキストを取り出す．"""
  lines = path.read_text(encoding="utf-8").splitlines()
  if any(SOURCE_QUESTION.match(line) for line in lines):
    return splitSourceBlocks(lines)
  return splitNoteBlocks(lines)


def countMentions(kind, numbers, blocks):
  """式・図の番号ごとに，その番号に触れている質問の数を数える．"""
  counts = {number: 0 for number in numbers}
  for block in blocks:
    found = findNumbers(block, expand=True)[kind]
    for number in numbers:
      if isCovered(kind, number, found):
        counts[number] += 1
  return counts


def reportQuestionCounts(args, sourceText, inSource, ignored):
  """--qa のファイルの問数が，ページ数と式・図の数に見合うかを表示し，不足の数を返す．"""
  blocks = []
  for path in args.qa:
    blocks += loadQuestionBlocks(path)
  pages = args.pages or countPages(sourceText)
  target = pages * args.min_per_page
  shortage = 0
  print(f"\n質問：全{len(blocks)}問（資料{pages}ページ × 1ページ{args.min_per_page}問 = 目安{target}問以上）")
  if len(blocks) < target:
    print(f"  あと{target - len(blocks)}問足りない")
    shortage += 1
  minimums = {"式": args.min_per_equation, "図": args.min_per_figure}
  for kind, minimum in minimums.items():
    numbers = [n for n in inSource[kind] if (kind, n) not in ignored]
    if not numbers or minimum <= 0:
      continue
    counts = countMentions(kind, numbers, blocks)
    few = [n for n in numbers if counts[n] < minimum]
    print(f"{kind}：{len(numbers)}個のうち，{minimum}問未満が{len(few)}個")
    if few:
      print("  " + "，".join(f"{formatNumbers(kind, [n])} {counts[n]}問" for n in few))
      shortage += len(few)
  if shortage:
    print("\n問数が目安に届いていません．言い換えではなく，触れていない文・式・図・記号・数値について足してください")
  else:
    print("\n問数は目安に届いています")
  return shortage


def printSentences(sourceText):
  """資料の文をページごとに番号付きで書き出す（1文に1問以上を作るための作業表）．"""
  pages = [page for page in sourceText.split("\f") if page.strip()]
  total = 0
  for pageIndex, page in enumerate(pages, start=1):
    flat = CJK_GAP.sub("", " ".join(line.strip() for line in page.splitlines() if line.strip()))
    flat = MULTI_SPACE.sub(" ", flat)
    sentences = [s.strip() for s in SENTENCE_END.split(flat) if len(s.strip()) >= MIN_SENTENCE_LENGTH]
    for sentenceIndex, sentence in enumerate(sentences, start=1):
      print(f"p.{pageIndex}-{sentenceIndex:02d} {sentence}")
    total += len(sentences)
  print(f"\n全{total}文（{len(pages)}ページ）")


def parseArgs():
  parser = argparse.ArgumentParser(description="資料の式・図・表の番号が，ノートの見出しにすべてあるかを調べる")
  parser.add_argument("source", type=Path, help="発表資料の PDF（--text のときは取り出し済みのテキスト）")
  parser.add_argument("note", type=Path, help="調べる Markdown ノート")
  parser.add_argument("--text", action="store_true", help="source を PDF ではなくテキストとして読む")
  parser.add_argument("--ignore", action="append", default=[], help="調べない番号（例：1.38，図1.2）．何度でも指定できる")
  parser.add_argument("--qa", action="append", type=Path, default=[], help="問数を調べる元データ（.txt）かノート（.md）．何度でも指定できる")
  parser.add_argument("--pages", type=int, default=0, help="資料のページ数（省略すると改ページから数える）")
  parser.add_argument("--min-per-page", type=int, default=DEFAULT_MIN_PER_PAGE, help=f"1ページあたりの問数の目安（既定 {DEFAULT_MIN_PER_PAGE}）")
  parser.add_argument("--min-per-equation", type=int, default=DEFAULT_MIN_PER_EQUATION, help=f"式1つに触れる問数の目安（既定 {DEFAULT_MIN_PER_EQUATION}）")
  parser.add_argument("--min-per-figure", type=int, default=DEFAULT_MIN_PER_FIGURE, help=f"図1つに触れる問数の目安（既定 {DEFAULT_MIN_PER_FIGURE}）")
  parser.add_argument("--sentences", action="store_true", help="資料の文をページごとに番号付きで書き出して終わる")
  args = parser.parse_args()
  for name in ("pages", "min_per_page", "min_per_equation", "min_per_figure"):
    if getattr(args, name) < 0:
      parser.error(f"--{name.replace('_', '-')} は0以上にしてください")
  return args


def main():
  args = parseArgs()
  if args.text:
    sourceText = args.source.read_text(encoding="utf-8")
  else:
    sourceText = extractPdfText(args.source)
  if args.sentences:
    printSentences(sourceText)
    return 0
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
  else:
    print("\n資料の式・図・表は，すべてノートの見出しにあります")
  shortage = reportQuestionCounts(args, sourceText, inSource, ignored) if args.qa else 0
  return 1 if missingCount or shortage else 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except (OSError, RuntimeError) as error:
    print(f"エラー: {error}", file=sys.stderr)
    sys.exit(2)
