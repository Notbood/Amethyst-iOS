#!/usr/bin/env python3
"""Make MobileGlues (written for Linux/Android) compile on Darwin. Idempotent, prints what it changed.
  1) __attribute__((alias("x"))) is unsupported on Darwin -> rewritten into forwarding functions
  2) syscall(__NR_gettid) does not exist on Darwin -> pthread_threadid_np helper
Usage: patch_mobileglues.py <MobileGlues-cpp dir>"""
import os, re, sys

root = sys.argv[1]
tid_re = re.compile(r"syscall\s*\(\s*(?:__NR_gettid|SYS_gettid)\s*\)")
inc_re = re.compile(r"^[ \t]*#[ \t]*include[^\n]*$", re.M)
TID_HELPER = """
#ifdef __APPLE__
#ifndef MG_DARWIN_TID_DEFINED
#define MG_DARWIN_TID_DEFINED
#include <pthread.h>
#include <stdint.h>
static inline long mg_darwin_tid() { uint64_t t = 0; pthread_threadid_np(NULL, &t); return (long)t; }
#endif
#endif
"""
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
        rel = os.path.relpath(path, root)
        s = open(path, encoding="utf-8", errors="replace").read()
        orig = s

        # --- pass 1: alias attributes ---
        if "alias(" in s:
            out, pos = [], 0
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
                changed += 1
                print("  %s: %s -> forwards to %s" % (rel, name, m.group(1)))
            out.append(s[pos:])
            s = "".join(out)

        # --- pass 2: gettid ---
        m = tid_re.search(s)
        if m:
            incs = [i for i in inc_re.finditer(s) if i.end() <= m.start()]
            at = incs[-1].end() if incs else 0
            s = s[:at] + "\n" + TID_HELPER + s[at:]
            s, n = tid_re.subn("mg_darwin_tid()", s)
            changed += n
            print("  %s: %d x syscall(gettid) -> mg_darwin_tid()" % (rel, n))

        if s != orig:
            open(path, "w", encoding="utf-8").write(s)
print("patch_mobileglues: %d change(s)" % changed)
