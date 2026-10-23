#!/usr/bin/env python3
"""発表資料に出てくる式番号・図番号・表番号が，ノートの見出しにすべてあるかを調べる．

「式の解説」「図の解説」に，資料のすべての式と図を並べたかを確かめるために使う．
--qa を付けると，想定質問・逆質問・発表者への質問が，資料のページ数と式・図の数に
見合うだけあるか（問数の目安）と，難易度（レベル1〜5）の配分，答えが「はい」で終わる質問と
答えを説明してもらう質問の割合，資料を見ただけでは答えが出ない「考えて答える質問」の数，
発表者への質問に「意図：」「言い換え：」の行がそろっているか（--require-intent）も調べる．
--quality を付けると，質問一つ一つの品質を点検する候補（重複，二つ以上聞いている，長すぎる，
漠然としている，考えて答える質問の答えに根拠がない）を一覧にする（終了コードには影響しない）．
--sentences は資料の文を番号付きで書き出し，手順の文と理由が書かれていない文に印を付ける．

使い方:
  python3 check_coverage.py 資料.pdf ノート.md
  python3 check_coverage.py 資料.pdf ノート.md --ignore 1.38 --ignore 図1.2
  python3 check_coverage.py --text 資料.txt ノート.md     （テキストを取り出し済みのとき）
  python3 check_coverage.py 資料.pdf ノート.md --qa 元データ.txt
  python3 check_coverage.py 資料.pdf ノート.md --qa 解説・質問.md --min-per-page 15 --min-per-equation 2 --min-per-figure 2 --min-easy-share 0.2 --min-open-share 0.4 --min-deep-per-page 5 --require-intent
  python3 check_coverage.py 資料.pdf ノート.md --qa 元データ.txt --quality
  python3 check_coverage.py 資料.pdf ノート.md --sentences

PDF のテキストは pdftotext（Poppler）で取り出す．
見出しにない番号があるか，--qa の問数やレベルの配分が目安に届かなければ，一覧を出して終了コード1で終わる．
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

# 問数の目安（逆質問の既定値．発表原稿や発表者への質問では --min-per-page などで変える）
DEFAULT_MIN_PER_PAGE = 35
DEFAULT_MIN_PER_EQUATION = 7
DEFAULT_MIN_PER_FIGURE = 8
# 難易度を5段階に分けたとき，各レベルが全問に占める割合の下限と，レベル1〜2の割合の下限（既定は調べない）
FIVE_LEVELS = 5
EASY_LEVELS = (1, 2)
DEFAULT_MIN_LEVEL_SHARE = 0.1
DEFAULT_MIN_EASY_SHARE = 0.0
# 答えを説明してもらう質問（答えが「はい」で始まらない質問）の割合の下限（既定は調べない）
DEFAULT_MIN_OPEN_SHARE = 0.0
YES_ANSWER = re.compile(r"^(はい|ええ|そうです)")
# 考えて答える質問の印（質問の頭に付ける）と，1ページあたりの数の下限（既定は調べない）
DEEP_TAG = re.compile(r"〔(組み合わせ|もし|比較|数値|つながり|理由|限界|前提)〕")
DEFAULT_MIN_DEEP_PER_PAGE = 0
# 発表者への質問で，聞き返されたときに言う「意図」と「言い換え」の行
INTENT_LINE = re.compile(r"^\s*-\s*意図[：:]")
REPHRASE_LINE = re.compile(r"^\s*-\s*言い換え[：:]")
# 品質の点検（--quality）の基準
MAX_QUESTION_LENGTH = 90
DUPLICATE_SIMILARITY = 0.65
STOCK_PHRASES = re.compile(r"とは何ですか|は何ですか|はいくらですか|はどうなりますか|どうなりますか|を一言で言ってください|という理解でよいですか|ですね|なぜですか|のはなぜですか")
QUESTION_ENDINGS = re.compile(r"(?:か|ください)[．？?]")
VAGUE_PHRASE = re.compile(r"について(?:説明|教えて|どう思)")
SPECIFIC_POINTER = re.compile(r"式\(|図\s?\d|p\.\s?\d|ページ|\d+\.\d+")
GROUNDS = re.compile(r"p\.\s?\d|ページ|式\(|図\s?\d|節|資料|原著")
NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)*")
# 解説・質問ファイルの想定回答の行（   - → 答え）
ARROW_ANSWER = re.compile(r"^\s*-\s*→\s*(.*)$")
# 質問のまとまりの始まり（元データの @行，組み立てた節の **A1．，番号付きの質問）
SOURCE_QUESTION = re.compile(r"^@(\d+)\|")
# 元データの難易度の段階数（%levels 5）と，ノートの小見出しのレベル（### 6-1. レベル1（…））
SOURCE_LEVELS = re.compile(r"^%levels\s+(\d+)$")
LEVEL_HEADING = re.compile(r"レベル([1-9])")
BUILT_QUESTION = re.compile(r"^\*\*[A-Z]+\d+．")
NUMBERED_QUESTION = re.compile(r"^\d+\.\s")
BLOCK_END = re.compile(r"^(#{1,6}\s|# |%)")
QUESTION_SECTION_WORDS = ("質問", "指摘")
# 文の区切り（全角・半角の句点）と，文として数えない短すぎる断片の長さ
SENTENCE_END = re.compile(r"(?<=[．。])")
MIN_SENTENCE_LENGTH = 8
CJK_GAP = re.compile(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])")
# --sentences の印．手順の文には「なぜ要るか・なぜこの順か・省くとどうなるか」，
# 理由が書かれていない文には「なぜか」を立てる（逆質問で突かれやすい）
STEP_WORDS = re.compile(r"(?<!量子化)ステップ(?!幅)|手順|まず|次に|その後|最後に|第[一二三四五1-5]に|した後|してから|に先立|の前に|の後に|後で")
NEED_WORDS = re.compile(r"必要|要する|要求|べき|しなければ|選ぶ|選択|下げる|上げる|増やす|減らす|戻す|用いる(?!と)|使用する(?!と)")
REASON_WORDS = re.compile(r"ため|から|ので|理由|なぜ|によって|により|結果")
STEP_MARK = "〔手順〕"
NO_REASON_MARK = "〔理由なし〕"
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
  """元データ（@行で始まる質問）を，質問ごとのテキストとレベルに分け，難易度の段階数と一緒に返す．

  分類の行（# ）や自由記述のブロック（%head など）が来たら，次の質問まで数えない．
  段階数は %levels の値で，書かれていなければ3（1.2.0 までの元データ）．
  """
  blocks = []
  scale = 3
  active = False
  for line in lines:
    question = SOURCE_QUESTION.match(line)
    levels = SOURCE_LEVELS.match(line)
    if levels:
      scale = int(levels.group(1))
    if question:
      blocks.append({"text": line, "level": int(question.group(1))})
      active = True
    elif BLOCK_END.match(line):
      active = False
    elif active and line.strip():
      blocks[-1]["text"] += "\n" + line
  return blocks, scale


def splitNoteBlocks(lines):
  """Markdown のノートを質問ごとのテキストとレベルに分け，難易度の段階数と一緒に返す．

  組み立てた節（**A1．）があればそれを，なければ見出し2（## ）に「質問」「指摘」を含む節の
  番号付きの項目（1. 2. …）を，1問として数える．小見出し（### 6-1 など）の下も同じ節とみなす．
  番号付きの項目のレベルは，その上の小見出しの「レベルN」から読む（### 6-1. レベル1（…））．
  小見出しにレベルがあれば5段階とみなし，なければ段階数は None（レベルを調べない）．
  """
  built = any(BUILT_QUESTION.match(line) for line in lines)
  if built:
    starter, inSection = BUILT_QUESTION, (lambda heading: True)
  else:
    starter = NUMBERED_QUESTION
    inSection = lambda heading: any(word in heading for word in QUESTION_SECTION_WORDS)
  blocks = []
  section = ""
  level = None
  scale = None
  current = None
  for line in lines:
    if HEADING_PATTERN.match(line):
      if line.startswith("## ") or line.startswith("# "):
        section = line
        level = None
      else:
        match = LEVEL_HEADING.search(line)
        level = int(match.group(1)) if match and not built and inSection(section) else None
        if level is not None:
          scale = FIVE_LEVELS
      current = None
      continue
    if starter.match(line) and inSection(section):
      blocks.append({"text": line, "level": level})
      current = len(blocks) - 1
    elif current is not None and line.strip():
      blocks[current]["text"] += "\n" + line
  return blocks, scale


def answerKind(block):
  """質問の答えが「はい」で始まるなら yes，それ以外なら open，答えがなければ None を返す．

  解説・質問ファイルは「- →」の行を，元データと組み立てたノートは質問の次の行を答えとみなす．
  """
  lines = block["text"].split("\n")
  arrows = [ARROW_ANSWER.match(line) for line in lines[1:]]
  answers = [match.group(1).strip() for match in arrows if match]
  if not answers:
    if NUMBERED_QUESTION.match(lines[0]):
      return None
    answers = [line.strip() for line in lines[1:] if line.strip()]
  if not answers:
    return None
  return "yes" if YES_ANSWER.match(answers[0]) else "open"


def reportAnswerKinds(args, blocks):
  """答えが「はい」で始まる質問と，答えを説明してもらう質問の数を表示し，割合が足りなければ1を返す．"""
  kinds = [answerKind(block) for block in blocks]
  yes = kinds.count("yes")
  opened = kinds.count("open")
  answered = yes + opened
  if not answered:
    return 0
  print(f"答えの形：「はい」で答える質問 {yes}問，説明してもらう質問 {opened}問（説明の割合 {opened / answered:.0%}）")
  if opened < args.min_open_share * answered:
    print(f"  説明してもらう質問が全問の{args.min_open_share:.0%}に届きません．「何ですか」「なぜですか」「いくらですか」の形の質問を足してください")
    return 1
  return 0


def reportDeepQuestions(args, blocks, pages):
  """考えて答える質問（質問の行に〔組み合わせ〕などの印）の数を表示し，目安に届かなければ1を返す．"""
  deep = sum(bool(DEEP_TAG.search(block["text"].split("\n")[0])) for block in blocks)
  target = pages * args.min_deep_per_page
  print(f"考えて答える質問（〔組み合わせ〕〔もし〕〔比較〕〔数値〕〔つながり〕〔理由〕〔限界〕〔前提〕）：{deep}問（1ページあたり {deep / pages:.1f}問）")
  if deep < target:
    print(f"  目安の{target}問（1ページ{args.min_deep_per_page}問）に届きません．資料を見ただけでは答えが出ない質問を足してください")
    return 1
  return 0


def reportIntents(blocks):
  """番号付きの質問（想定回答「→」のあるもの）に，「意図：」と「言い換え：」の行があるかを調べ，欠けた数を返す．"""
  asked = [
    block for block in blocks
    if NUMBERED_QUESTION.match(block["text"]) and any(ARROW_ANSWER.match(line) for line in block["text"].split("\n")[1:])
  ]
  if not asked:
    print("意図と言い換え：調べていません（解説・質問ファイルの番号付きの質問だけを調べます）")
    return 0
  missing = []
  for block in asked:
    lines = block["text"].split("\n")
    if not any(INTENT_LINE.match(line) for line in lines) or not any(REPHRASE_LINE.match(line) for line in lines):
      missing.append(block["text"].split(".", 1)[0])
  print(f"意図と言い換え：{len(asked)}問のうち，そろっていない質問 {len(missing)}問")
  if missing:
    shown = "，".join(missing[:15]) + ("，…" if len(missing) > 15 else "")
    print(f"  欠けている番号：{shown}．聞き返されたときのために「- 意図：」「- 言い換え：」の行を足してください")
    return 1
  return 0


def questionParts(block):
  """質問のまとまりから，番号，質問の文（印・【】・★を除いた本文），答えの文を取り出す．"""
  lines = block["text"].split("\n")
  first = lines[0]
  if first.startswith("@"):
    first = first.split("|", 3)[3]
    ident = ""
  else:
    match = re.match(r"^(?:\*\*)?([A-Z]*\d+)[.．]\s*", first)
    ident = match.group(1) if match else ""
    first = first[match.end():] if match else first
  question = re.sub(r"〔[^〕]*〕|【[^】]*】|★|\*\*$", "", first).strip()
  arrows = [ARROW_ANSWER.match(line) for line in lines[1:]]
  answers = [m.group(1) for m in arrows if m] or [line.strip() for line in lines[1:] if line.strip()]
  return ident, first, question, " ".join(answers)


def bigramSet(text):
  """似ているかを比べるための2文字の組の集合（決まり文句と記号を除く）．"""
  text = STOCK_PHRASES.sub("", text)
  text = re.sub(r"[\s，．、。？?「」（）()$\\{}_^|]", "", text)
  return {text[i:i + 2] for i in range(len(text) - 1)}


def reportQuality(blocks):
  """質問一つ一つの品質を点検する候補を一覧にする（終了コードには影響しない）．"""
  parts = [questionParts(block) for block in blocks]
  labels = [ident or f"{index + 1}問目" for index, (ident, _, _, _) in enumerate(parts)]
  candidates = {
    "二つ以上聞いている（一問一義にする）": [],
    f"長すぎる（{MAX_QUESTION_LENGTH}字より長い．短く一回で伝わる文にする）": [],
    "漠然としている（式・図・ページで指す所を決める）": [],
    "考えて答える質問の答えに根拠がない（資料のどこを組み合わせたかを書く）": [],
  }
  keys = list(candidates)
  for label, (ident, first, question, answer) in zip(labels, parts):
    if len(QUESTION_ENDINGS.findall(question)) >= 2:
      candidates[keys[0]].append(label)
    if len(question) > MAX_QUESTION_LENGTH:
      candidates[keys[1]].append(label)
    if VAGUE_PHRASE.search(question) and not SPECIFIC_POINTER.search(first):
      candidates[keys[2]].append(label)
    if DEEP_TAG.search(first) and not GROUNDS.search(answer + first):
      candidates[keys[3]].append(label)
  grams = [bigramSet(question) for _, _, question, _ in parts]
  numbers = [set(NUMBER_TOKEN.findall(question)) for _, _, question, _ in parts]
  duplicates = []
  for a in range(len(parts)):
    for b in range(a + 1, len(parts)):
      if numbers[a] != numbers[b] or not grams[a] or not grams[b]:
        continue
      similarity = len(grams[a] & grams[b]) / len(grams[a] | grams[b])
      if similarity >= DUPLICATE_SIMILARITY:
        duplicates.append(f"{labels[a]}と{labels[b]}")
  print("\n品質の点検の候補（一つずつ読み，直すか，そのままでよい理由を確かめる）：")
  print(f"  重複の候補（同じ答えになるなら1つにまとめ，空いた枠を触れていない所の質問にする）：{len(duplicates)}組")
  if duplicates:
    print("    " + "，".join(duplicates[:20]) + ("，…" if len(duplicates) > 20 else ""))
  for name, labelsFound in candidates.items():
    print(f"  {name}：{len(labelsFound)}問")
    if labelsFound:
      print("    " + "，".join(labelsFound[:20]) + ("，…" if len(labelsFound) > 20 else ""))


def loadQuestionBlocks(path):
  """元データ（.txt）かノート（.md）から，質問ごとのテキストとレベル，難易度の段階数を取り出す．"""
  lines = path.read_text(encoding="utf-8").splitlines()
  if any(SOURCE_QUESTION.match(line) for line in lines):
    return splitSourceBlocks(lines)
  return splitNoteBlocks(lines)


def countMentions(kind, numbers, blocks):
  """式・図の番号ごとに，その番号に触れている質問の数を数える．"""
  counts = {number: 0 for number in numbers}
  for block in blocks:
    found = findNumbers(block["text"], expand=True)[kind]
    for number in numbers:
      if isCovered(kind, number, found):
        counts[number] += 1
  return counts


def reportLevels(args, blocks, scale):
  """質問のレベルの配分を表示し，5段階なら目安に届かないレベルの数を返す．"""
  leveled = [block["level"] for block in blocks if block["level"] is not None]
  if scale is None or not leveled:
    print("レベル：調べていません（元データの @レベル か，ノートの小見出しの「レベルN」から読みます）")
    return 0
  counts = {level: leveled.count(level) for level in range(1, max(scale, max(leveled)) + 1)}
  unleveled = len(blocks) - len(leveled)
  parts = [f"レベル{level} {count}問" for level, count in counts.items()]
  if unleveled:
    parts.append(f"レベルなし {unleveled}問（表記の指摘など）")
  print("レベル：" + "，".join(parts))
  if scale < FIVE_LEVELS:
    return 0
  shortage = 0
  few = [level for level in range(1, FIVE_LEVELS + 1) if counts.get(level, 0) < args.min_level_share * len(leveled)]
  if few:
    print(f"  全問の{args.min_level_share:.0%}に届かないレベル：" + "，".join(f"レベル{level}" for level in few))
    shortage += len(few)
  easy = sum(counts.get(level, 0) for level in EASY_LEVELS)
  if easy < args.min_easy_share * len(leveled):
    print(f"  レベル1〜2が{easy}問で，全問の{args.min_easy_share:.0%}に届きません．聞きやすい易しい質問を足してください")
    shortage += 1
  return shortage


def reportQuestionCounts(args, sourceText, inSource, ignored):
  """--qa のファイルの問数が，ページ数と式・図の数に見合うかを表示し，不足の数を返す．"""
  blocks = []
  scales = []
  for path in args.qa:
    fileBlocks, scale = loadQuestionBlocks(path)
    blocks += fileBlocks
    if scale is not None:
      scales.append(scale)
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
  shortage += reportLevels(args, blocks, max(scales) if scales else None)
  shortage += reportAnswerKinds(args, blocks)
  shortage += reportDeepQuestions(args, blocks, pages)
  if args.require_intent:
    shortage += reportIntents(blocks)
  if args.quality:
    reportQuality(blocks)
  if shortage:
    print("\n問数が目安に届いていません．言い換えではなく，触れていない文・式・図・記号・数値と，足りないレベルの問い，欠けている意図と言い換えを足してください")
  else:
    print("\n問数は目安に届いています")
  return shortage


def sentenceMarks(sentence):
  """文に付ける印（手順の文，理由が書かれていない文）を返す．"""
  marks = ""
  if STEP_WORDS.search(sentence):
    marks += STEP_MARK
  if NEED_WORDS.search(sentence) and not REASON_WORDS.search(sentence):
    marks += NO_REASON_MARK
  return marks


def printSentences(sourceText):
  """資料の文をページごとに番号付きで書き出す（1文に1問以上を作るための作業表）．

  手順の文と，理由が書かれていない文に印を付け，最後に数を出す．
  """
  pages = [page for page in sourceText.split("\f") if page.strip()]
  total = steps = noReasons = 0
  for pageIndex, page in enumerate(pages, start=1):
    flat = CJK_GAP.sub("", " ".join(line.strip() for line in page.splitlines() if line.strip()))
    flat = MULTI_SPACE.sub(" ", flat)
    sentences = [s.strip() for s in SENTENCE_END.split(flat) if len(s.strip()) >= MIN_SENTENCE_LENGTH]
    for sentenceIndex, sentence in enumerate(sentences, start=1):
      marks = sentenceMarks(sentence)
      steps += STEP_MARK in marks
      noReasons += NO_REASON_MARK in marks
      print(f"p.{pageIndex}-{sentenceIndex:02d} {marks}{sentence}")
    total += len(sentences)
  print(f"\n全{total}文（{len(pages)}ページ）")
  print(f"{STEP_MARK}{steps}文：各ステップに「なぜ要るか」「なぜこの順か」「省くとどうなるか」「前後で何が変わるか」を立てる")
  print(f"{NO_REASON_MARK}{noReasons}文：「なぜ〜するのですか」を立て，答えはほかのページの記述から組み立てる")


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
  parser.add_argument("--min-level-share", type=float, default=DEFAULT_MIN_LEVEL_SHARE, help=f"5段階のとき，各レベルが全問に占める割合の下限（既定 {DEFAULT_MIN_LEVEL_SHARE}）")
  parser.add_argument("--min-easy-share", type=float, default=DEFAULT_MIN_EASY_SHARE, help=f"5段階のとき，レベル1〜2が全問に占める割合の下限（既定 {DEFAULT_MIN_EASY_SHARE}．発表者への質問は 0.4）")
  parser.add_argument("--min-open-share", type=float, default=DEFAULT_MIN_OPEN_SHARE, help=f"答えが「はい」で始まらない（説明してもらう）質問の割合の下限（既定 {DEFAULT_MIN_OPEN_SHARE}．発表者への質問は 0.4）")
  parser.add_argument("--min-deep-per-page", type=int, default=DEFAULT_MIN_DEEP_PER_PAGE, help=f"考えて答える質問（〔組み合わせ〕などの印付き）の1ページあたりの下限（既定 {DEFAULT_MIN_DEEP_PER_PAGE}．逆質問と発表者への質問は 5）")
  parser.add_argument("--require-intent", action="store_true", help="発表者への質問（番号付き）に「- 意図：」「- 言い換え：」の行がそろっているかを調べる")
  parser.add_argument("--quality", action="store_true", help="質問一つ一つの品質を点検する候補（重複，二つ以上聞いている，長すぎる，漠然，根拠のない答え）を一覧にする")
  parser.add_argument("--sentences", action="store_true", help="資料の文をページごとに番号付きで書き出して終わる")
  args = parser.parse_args()
  for name in ("pages", "min_per_page", "min_per_equation", "min_per_figure", "min_deep_per_page"):
    if getattr(args, name) < 0:
      parser.error(f"--{name.replace('_', '-')} は0以上にしてください")
  for name in ("min_level_share", "min_easy_share", "min_open_share"):
    if not 0 <= getattr(args, name) <= 1:
      parser.error(f"--{name.replace('_', '-')} は0以上1以下にしてください")
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
