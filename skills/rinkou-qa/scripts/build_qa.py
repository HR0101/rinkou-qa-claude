#!/usr/bin/env python3
"""想定質問の元データから，Markdown ノート（Obsidian など）の「## 想定質問」節を組み立てて差し替える．

使い方:
  python3 build_qa.py 元データ.txt ノート.md             ノートの節を差し替える（先にバックアップを作る）
  python3 build_qa.py 元データ.txt ノート.md --dry-run   差し替えずに，組み立てた節を標準出力に出す
  python3 build_qa.py 元データ.txt                       ノートなしで，組み立てた節を標準出力に出す

元データの書式は ../references/source-format.md を参照．
"""
import argparse
import datetime
import re
import shutil
import string
import sys
from pathlib import Path

MIN_LEVEL = 1
MAX_LEVEL = 3
LEVEL_NAMES = {1: "レベル1（基礎）", 2: "レベル2（標準）", 3: "レベル3（発展）"}
LEVEL_DESCRIPTIONS = {
  1: "定義や意味を聞く質問．1文で即答する．",
  2: "理由，式や図の読み取り，簡単な計算を聞く質問．結論の後に理由を1つ足す．",
  3: "導出，資料の範囲外，意地悪な質問．結論と直感的な理由だけを言い，詳しい話は聞かれたら続ける．",
}
STAR_FLAG = "★"
PRIORITY_FLAG = "!"
SECTION_HEADING = "## 想定質問"
# 想定質問の節の終わり（次の見出し2．直前の区切り線 --- は節に含めない）
NEXT_SECTION_PATTERN = re.compile(r"\n(?:---\n+)?## ")
CATEGORY_PATTERN = re.compile(r"^# ([A-Z]+)\|([^|]+)(?:\|([^|]+))?$")
QUESTION_PATTERN = re.compile(r"^@(\d+)\|([^|]*)\|([^|]*)\|(.+)$")
# 「@数字」で始まるのに QUESTION_PATTERN に合わない行（区切りの | の数の間違いなど）
MALFORMED_QUESTION_PATTERN = re.compile(r"^@\d")
DIRECTIVE_PATTERN = re.compile(r"^%(head|practice|tail)$")
REF_PATTERN = re.compile(r"@@([a-z0-9_-]+)@@")
KEY_PREFIX = "key="
# Markdown でコード扱いになる TeX の引用符
TEX_QUOTE_PATTERN = re.compile(r"``|''")
BACKUP_DATE_FORMAT = "%Y%m%d"
BACKUP_LETTERS = string.ascii_lowercase
RECOMMENDED_PRIORITY_RANGE = (10, 25)


def newQuestion(lineNumber, match):
  """質問行の正規表現の一致から，質問の辞書を作る．"""
  level = int(match.group(1))
  if not MIN_LEVEL <= level <= MAX_LEVEL:
    raise ValueError(f"{lineNumber}行目: レベルは{MIN_LEVEL}〜{MAX_LEVEL}にしてください: {level}")
  flags = match.group(2)
  key = match.group(3)
  if key and not key.startswith(KEY_PREFIX):
    raise ValueError(f"{lineNumber}行目: 参照キーは {KEY_PREFIX}xxx の形にしてください: {key}")
  return {
    "line": lineNumber,
    "level": level,
    "star": STAR_FLAG in flags,
    "priority": PRIORITY_FLAG in flags,
    "key": key.removeprefix(KEY_PREFIX),
    "text": match.group(4),
    "answer": [],
  }


def parseSource(path):
  """元データを読み込み，自由記述のブロックと分類ごとの質問を返す．"""
  blocks = {"head": [], "practice": [], "tail": []}
  categories = []
  mode = None
  category = None
  question = None
  with open(path, encoding="utf-8") as fileObj:
    for lineNumber, rawLine in enumerate(fileObj, 1):
      line = rawLine.rstrip("\n")
      directive = DIRECTIVE_PATTERN.match(line)
      categoryMatch = CATEGORY_PATTERN.match(line)
      questionMatch = QUESTION_PATTERN.match(line)
      if directive:
        mode = directive.group(1)
        category = question = None
      elif categoryMatch:
        mode = "category"
        category = {
          "prefix": categoryMatch.group(1),
          "title": categoryMatch.group(2),
          "short": categoryMatch.group(3) or categoryMatch.group(2),
          "questions": [],
        }
        categories.append(category)
        question = None
      elif questionMatch:
        if mode != "category":
          raise ValueError(f"{lineNumber}行目: 質問が分類（# 接頭辞|題名）の外にあります")
        question = newQuestion(lineNumber, questionMatch)
        category["questions"].append(question)
      elif mode == "category" and MALFORMED_QUESTION_PATTERN.match(line):
        raise ValueError(f"{lineNumber}行目: 質問行の書式が違います（@レベル|フラグ|key=xxx|質問）: {line}")
      elif mode in blocks:
        blocks[mode].append(line)
      elif line.strip():
        if question is None:
          raise ValueError(f"{lineNumber}行目: 質問（@レベル|…）より前に本文があります: {line}")
        question["answer"].append(line)
  return {name: trimBlankLines(lines) for name, lines in blocks.items()}, categories


def trimBlankLines(lines):
  """前後の空行を取り除く．"""
  start = 0
  end = len(lines)
  while start < end and not lines[start].strip():
    start += 1
  while end > start and not lines[end - 1].strip():
    end -= 1
  return lines[start:end]


def countDollars(text):
  """エスケープされていないドル記号の数を数える．"""
  return len(re.findall(r"(?<!\\)\$", text))


def validateCategories(categories):
  """分類の接頭辞の重複と，空の分類を調べる．"""
  if not categories:
    raise ValueError("分類（# 接頭辞|題名）が1つもありません")
  seen = set()
  for category in categories:
    if category["prefix"] in seen:
      raise ValueError(f"分類の接頭辞が重複しています: {category['prefix']}")
    seen.add(category["prefix"])
    if not category["questions"]:
      raise ValueError(f"質問のない分類があります: {category['prefix']} {category['title']}")


def assignIds(categories):
  """分類ごとに通し番号を振り，参照キーと番号の対応を返す．"""
  keyToId = {}
  for category in categories:
    for index, question in enumerate(category["questions"], 1):
      question["id"] = f"{category['prefix']}{index}"
      if not question["answer"]:
        raise ValueError(f"{question['line']}行目: 答えがありません: {question['id']} {question['text']}")
      if question["key"]:
        if question["key"] in keyToId:
          raise ValueError(f"{question['line']}行目: 参照キーが重複しています: {question['key']}")
        keyToId[question["key"]] = question["id"]
  return keyToId


def checkQuestionText(categories):
  """ドル記号の対応と TeX の引用符を調べ，警告の一覧を返す．"""
  warnings = []
  for category in categories:
    for question in category["questions"]:
      body = "\n".join([question["text"]] + question["answer"])
      if countDollars(body) % 2:
        raise ValueError(f"{question['line']}行目: ドル記号の数が奇数です（数式の閉じ忘れ）: {question['id']}")
      if TEX_QUOTE_PATTERN.search(body):
        warnings.append(f"{question['id']}: `` や '' は Markdown でコード扱いになります．「」に置き換えてください")
  return warnings


def resolveRefs(text, keyToId):
  """@@key@@ を質問番号に置き換える．"""
  def replace(match):
    key = match.group(1)
    if key not in keyToId:
      raise ValueError(f"未定義の参照キーです: {key}")
    return keyToId[key]
  return REF_PATTERN.sub(replace, text)


def compressIds(ids):
  """P1，P2，P3 のような3つ以上の連番を P1〜P3 にまとめる．"""
  if not ids:
    return "―"
  prefix = re.match(r"[A-Z]+", ids[0]).group(0)
  numbers = [int(i[len(prefix):]) for i in ids]
  parts = []
  start = prev = numbers[0]
  for number in numbers[1:] + [None]:
    if number is not None and number == prev + 1:
      prev = number
      continue
    if prev - start >= 2:
      parts.append(f"{prefix}{start}〜{prefix}{prev}")
    elif prev == start:
      parts.append(f"{prefix}{start}")
    else:
      parts.append(f"{prefix}{start}，{prefix}{prev}")
    if number is not None:
      start = prev = number
  return "，".join(parts)


def tableCell(text):
  """表のセルで縦棒が列の区切りにならないよう，数式内の | を \\vert に置き換える．"""
  return re.sub(r"\$[^$]*\$", lambda m: m.group(0).replace("|", r"\vert "), text)


def fillPlaceholders(lines, categories, updateDate):
  """自由記述のブロックの {{total}} などを実際の値に置き換える．"""
  values = {
    "{{total}}": str(sum(len(c["questions"]) for c in categories)),
    "{{stars}}": str(sum(q["star"] for c in categories for q in c["questions"])),
    "{{date}}": updateDate,
    "{{categories}}": "，".join(f"{c['prefix']} {c['short']}" for c in categories),
  }
  filled = []
  for line in lines:
    for placeholder, value in values.items():
      line = line.replace(placeholder, value)
    filled.append(line)
  return filled


def buildPriorityTable(categories, keyToId):
  """最優先で練習する質問の表を組み立てる．"""
  lines = ["**本番前にこれだけは声に出して答える（最優先）**", "", "| 番号 | 質問 |", "|---|---|"]
  for category in categories:
    for question in category["questions"]:
      if question["priority"]:
        lines.append(f"| {question['id']} | {tableCell(resolveRefs(question['text'], keyToId))} |")
  lines += ["", "表：最優先で練習する質問．"]
  return lines


def buildLevelIndex(categories):
  """難易度別の索引の表を組み立てる．"""
  levels = range(MIN_LEVEL, MAX_LEVEL + 1)
  lines = ["**難易度別の索引（易しい順に練習する）**", ""]
  lines += [f"- **{LEVEL_NAMES[level]}**：{LEVEL_DESCRIPTIONS[level]}" for level in levels]
  lines += ["", "| 分類 | 問数 | " + " | ".join(LEVEL_NAMES[level] for level in levels) + f" | {STAR_FLAG} |"]
  lines.append("|---|---|" + "---|" * len(levels) + "---|")
  for category in categories:
    questions = category["questions"]
    cells = [compressIds([q["id"] for q in questions if q["level"] == level]) for level in levels]
    stars = compressIds([q["id"] for q in questions if q["star"]])
    lines.append(f"| {category['prefix']} {category['title']} | {len(questions)} | " + " | ".join(cells) + f" | {stars} |")
  lines += ["", "表：想定質問の難易度別の索引．"]
  return lines


def buildCategory(category, keyToId):
  """1つの分類の見出しと質問・答えを組み立てる．"""
  lines = ["", f"### {category['prefix']}. {category['title']}", ""]
  for question in category["questions"]:
    star = STAR_FLAG if question["star"] else ""
    lines.append(f"**{question['id']}．{star}{resolveRefs(question['text'], keyToId)}**")
    lines += [resolveRefs(answer, keyToId) for answer in question["answer"]]
    lines.append("")
  return lines


def buildSection(blocks, categories, keyToId, updateDate):
  """想定質問の節全体（見出しを含む）を組み立てる．"""
  lines = [SECTION_HEADING, ""]
  lines += fillPlaceholders(blocks["head"], categories, updateDate)
  lines += [""] + buildPriorityTable(categories, keyToId)
  lines += [""] + buildLevelIndex(categories)
  if blocks["practice"]:
    lines += [""] + fillPlaceholders(blocks["practice"], categories, updateDate)
  for category in categories:
    lines += buildCategory(category, keyToId)
  lines += fillPlaceholders(blocks["tail"], categories, updateDate)
  return "\n".join(lines).rstrip("\n") + "\n"


def replaceSection(noteText, section):
  """ノートの「## 想定質問」から次の見出し2の手前までを差し替えた本文を返す．"""
  heading = SECTION_HEADING + "\n"
  count = noteText.count(heading)
  if count != 1:
    raise ValueError(f"ノートに「{SECTION_HEADING}」の見出しが{count}個あります．ちょうど1個にしてください")
  head, rest = noteText.split(heading, 1)
  nextSection = NEXT_SECTION_PATTERN.search(rest)
  tail = rest[nextSection.start():] if nextSection else ""
  return head + section + tail


def backupPath(notePath):
  """ノートと同じフォルダに，日付付きで重ならないバックアップのパスを返す．"""
  stamp = datetime.date.today().strftime(BACKUP_DATE_FORMAT)
  candidate = notePath.with_name(f"{notePath.name}.bak_{stamp}")
  for letter in BACKUP_LETTERS[1:]:
    if not candidate.exists():
      return candidate
    candidate = notePath.with_name(f"{notePath.name}.bak_{stamp}{letter}")
  if candidate.exists():
    raise ValueError(f"今日のバックアップが多すぎます: {notePath.name}.bak_{stamp}*")
  return candidate


def printSummary(categories, warnings):
  """問数の集計と警告を標準エラーに出す．"""
  total = sum(len(c["questions"]) for c in categories)
  stars = sum(q["star"] for c in categories for q in c["questions"])
  priority = sum(q["priority"] for c in categories for q in c["questions"])
  print(f"想定質問 {total}問（{STAR_FLAG} {stars}問，最優先 {priority}問）", file=sys.stderr)
  for category in categories:
    print(f"  {category['prefix']}: {len(category['questions'])}問", file=sys.stderr)
  low, high = RECOMMENDED_PRIORITY_RANGE
  if not low <= priority <= high:
    warnings.append(f"最優先の質問が{priority}問です．{low}〜{high}問を目安にしてください")
  for warning in warnings:
    print(f"警告: {warning}", file=sys.stderr)


def parseArgs():
  parser = argparse.ArgumentParser(description="想定質問の元データからノートの「## 想定質問」節を組み立てる")
  parser.add_argument("source", type=Path, help="元データのテキストファイル")
  parser.add_argument("note", type=Path, nargs="?", help="差し替える Obsidian ノート（省略すると標準出力に出す）")
  parser.add_argument("--dry-run", action="store_true", help="ノートを書き換えず，組み立てた節を標準出力に出す")
  parser.add_argument("--date", default=datetime.date.today().isoformat(), help="{{date}} に入れる更新日（既定は今日）")
  parser.add_argument("--no-backup", action="store_true", help="差し替え前のバックアップを作らない")
  return parser.parse_args()


def main():
  args = parseArgs()
  blocks, categories = parseSource(args.source)
  validateCategories(categories)
  keyToId = assignIds(categories)
  warnings = checkQuestionText(categories)
  section = buildSection(blocks, categories, keyToId, args.date)
  if args.note is None or args.dry_run:
    if args.note is not None:
      replaceSection(args.note.read_text(encoding="utf-8"), section)
    sys.stdout.write(section)
  else:
    noteText = args.note.read_text(encoding="utf-8")
    newText = replaceSection(noteText, section)
    if not args.no_backup:
      backup = backupPath(args.note)
      shutil.copy2(args.note, backup)
      print(f"バックアップ: {backup}", file=sys.stderr)
    args.note.write_text(newText, encoding="utf-8")
    print(f"書き込みました: {args.note}", file=sys.stderr)
  printSummary(categories, warnings)


if __name__ == "__main__":
  try:
    main()
  except (ValueError, OSError) as error:
    print(f"エラー: {error}", file=sys.stderr)
    sys.exit(1)
