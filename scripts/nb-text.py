#!/usr/bin/env python3
# dump the visible text of a Mathematica notebook (.nb) without a kernel.
# usage: python3 scripts/nb-text.py <file.nb>
# prints one line per leaf cell: ==[Style]== flattened text. box structure
# (fractions, sums, superscripts) is lossy but good enough to see what each
# cell says and in what order — use it to read lesson/exercise text and to
# verify hand-edited notebooks before sending them anywhere.

import re
import signal
import sys

signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # play nice with head/grep -m


# top-level Cell[...] spans, recursing into CellGroupData wrappers so only
# leaf cells come back. bracket matching skips quoted strings (escapes and
# all), which also carries it safely past embedded raster CompressedData.
def cells(s, start=0):
    i = start
    while True:
        j = s.find("Cell[", i)
        if j < 0:
            return
        depth = 0
        k = j + 4
        while k < len(s):
            c = s[k]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
            elif c == '"':
                k += 1
                while k < len(s) and s[k] != '"':
                    if s[k] == "\\":
                        k += 1
                    k += 1
            k += 1
        if s[j:j + 19] == "Cell[CellGroupData[":
            i = j + 5  # descend into the group
        else:
            yield s[j:k + 1]
            i = k + 1


STYLES = ("Title|Subtitle|Chapter|Section|Subsection|Subsubsection|"
          "Text|Input|Output|Program|Item|ItemNumbered")


# concatenate every quoted string in the cell body. style names and UUID
# fragments leak through, so output is for eyeballs, not round-tripping.
def flatten(body):
    body = re.sub(r'ExpressionUUID->"[^"]*"', "", body)
    body = re.sub(r"Cell(ChangeTimes|Label|Tags)->[^,\]]*", "", body)
    toks = re.findall(r'"((?:[^"\\]|\\.)*)"', body, re.S)  # re.S: \-newline in \<...\> strings
    out = "".join(toks)
    out = (out.replace("\\n", "\n").replace('\\"', '"')
              .replace("\\<", "").replace("\\>", "").replace("\\\n", "")
              .replace("\\[IndentingNewLine]", "\n")
              .replace("\\[LineSeparator]", "\n"))
    return re.sub(r"\\\[([A-Za-z]+)\]", r"<\1>", out).strip()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__ or "usage: nb-text.py <file.nb>")
    src = open(sys.argv[1]).read().replace("\r\n", "\n")
    m = re.search(r"\(\* End of Notebook Content \*\)", src)
    if m:
        src = src[:m.start()]  # drop the stale outline cache at the end
    for c in cells(src):
        body = re.match(r"Cell\[(.*)\]$", c, re.S).group(1)
        sm = re.search(r',\s*"(%s)"' % STYLES, body)
        style = sm.group(1) if sm else "?"
        txt = flatten(body)
        if len(txt) > 900:
            txt = txt[:900] + "…"
        print(f"==[{style}]== {txt}")


if __name__ == "__main__":
    main()
