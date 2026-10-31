#!/usr/bin/env python3
"""Darwin cannot do __attribute__((alias("x"))). Rewrite every such declaration into a forwarding function.
Usage: patch_mobileglues.py <MobileGlues-cpp dir>   (idempotent, prints what it changed)"""
import os, re, sys

root = sys.argv[1]
alias_re = re.compile(r'__attribute__\s*\(\(\s*alias\s*\(\s*"(\w+)"\s*\)\s*\)\)\s*;')
SKIP = {"GLAPI", "GLAPIENTRY", "extern", "static", "inline", "APIENTRY"}

def split_params(p):
    out, depth, cur = [], 0, ""
    for ch in p:
        if ch in "([<":
            depth += 1
        elif ch in ")]>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out

def convert(decl, target):
    decl = " ".join(decl.split())
    i = decl.index("(")
    j = decl.rindex(")")
    head, params = decl[:i].strip(), decl[i + 1:j].strip()
    toks = head.replace("*", " * ").split()
    name = toks[-1]
    rettoks = [t for t in toks[:-1] if t not in SKIP]
    is_void = rettoks == ["void"]
    args = []
    if params and params != "void":
        for prm in split_params(params):
            prm = re.sub(r"\[[^\]]*\]\s*$", "", prm.strip())
            m = re.search(r"([A-Za-z_]\w*)\s*$", prm)
            args.append(m.group(1))
    call = "%s(%s)" % (target, ", ".join(args))
    return "%s { %s%s; }" % (decl, "" if is_void else "return ", call), name

changed = 0
for dp, _, files in os.walk(root):
    for fn in files:
        if not fn.endswith((".c", ".cc", ".cpp", ".h", ".hpp")):
            continue
        path = os.path.join(dp, fn)
        s = open(path, encoding="utf-8", errors="replace").read()
        if "alias(" not in s:
            continue
        out, pos, n = [], 0, 0
        for m in alias_re.finditer(s):
            before = s[pos:m.start()]
            b = max(before.rfind(";"), before.rfind("}"), before.rfind("{")) + 1
            keep, chunk = before[:b], before[b:]
            lines = chunk.split("\n")
            while lines and (not lines[0].strip() or lines[0].lstrip().startswith(("#", "//"))):
                keep += lines.pop(0) + "\n"
            new, name = convert("\n".join(lines), m.group(1))
            out.append(keep + new)
            pos = m.end()
            n += 1
            print("  %s: %s -> forwards to %s" % (os.path.relpath(path, root), name, m.group(1)))
        if n:
            out.append(s[pos:])
            open(path, "w", encoding="utf-8").write("".join(out))
            changed += n
print("patch_mobileglues: converted %d alias declaration(s)" % changed)
