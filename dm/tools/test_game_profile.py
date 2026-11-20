#!/usr/bin/env python3
# Guard for P4.1: a runtime host must be equivalent to a builtin one. game.py profile writes the constants of header_one as
# rows, and game.py header --runtime builds a table from them; this checks, for every profile in dm/games, that the rows and
# the builtin macros agree field by field. A difference means a runtime host would start with values the builtin one never had.
#
#   python dm/tools/test_game_profile.py [--game <title ID>...]
#
# Exits non-zero on any difference (or when a profile's rows cannot be parsed).
import argparse, re, sys
from pathlib import Path

DM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DM / 'games'))
import game  # noqa: E402  (dm/games/game.py)

ap = argparse.ArgumentParser()
ap.add_argument('--game', action='append', help='title IDs to check (default: every profile)')
a = ap.parse_args()


def builtin_macros(g):
    """header_one's constants by macro name: the values a builtin host compiles in."""
    return {m[1]: m[2] for m in (re.match(r'#define (DM_GAME_\w+) (.*)$', ln) for ln in game.header_one(g).splitlines()) if m}


def parse_rows(text):
    """profile()' output → [{row: [values]}] with 'program' first in each block."""
    out, cur = [], None
    for ln in text.splitlines():
        if not ln or ln.startswith('#'):
            continue
        parts = ln.split('\t')
        if parts[0] == 'program':
            cur = {'program': [parts[1]]}
            out.append(cur)
        elif cur is not None:
            cur[parts[0]] = parts[1:]
    return out


def unq(v):
    """a C string literal's contents; non-literals unchanged (a number keeps its text)."""
    return game._unq(v) if v.startswith('"') else v


def same(field, macro_val, rows, path):
    """Whether the builtin macro and the profile row express the same thing for one field."""
    if field in dict((f, m) for f, m, _ in game.RT_FIELDS):
        typ = dict((f, t) for f, _, t in game.RT_FIELDS)[field]
        got = rows.get(field)
        if got is None:
            return f'{field}: no row (builtin has {macro_val})'
        if typ == 'str':
            want, have = unq(macro_val), got[0] if got else ''
            return True if want == have else f'{field}: builtin {want!r}, profile {have!r}'
        want = int(macro_val.replace('ull', ''), 0)
        try:
            have = int(got[0], 0)
        except (ValueError, IndexError):
            return f'{field}: profile {got!r} is not a number'
        return True if want == have else f'{field}: builtin {want}, profile {have}'
    if field == 'modules':
        want = [game._unq(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"', macro_val)]
        have = rows.get('modules', [])
        return True if want == have else f'modules: builtin {want}, profile {have}'
    if field in ('builds', 'versions'):
        want = [game._unq(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"', macro_val)]
        have = rows.get(field, [])
        # The macro's rows are pairs; a profile with no build rows writes one NULL row (header_one's "NULL, NULL").
        w = [(want[i], want[i + 1]) for i in range(0, len(want) - 1, 2)]
        h = [(have[i], have[i + 1]) for i in range(0, len(have) - 1, 2)]
        return True if w == h else f'{field}: builtin {w}, profile {h}'
    return f'{field}: not comparable'


fails = 0
checked = 0
for prof in sorted((DM / 'games').glob('*/game.tsv')):
    tid = prof.parent.name
    if not re.fullmatch(r'[0-9A-Fa-f]{16}', tid) or (a.game and tid not in a.game):
        continue
    g = game.load(tid)
    progs = game._progs(g)
    rows_by_prog = parse_rows(game.profile(progs, game._src(g)))
    if len(rows_by_prog) != len(progs):
        print(f'{tid}: {len(progs)} program(s) but {len(rows_by_prog)} profile block(s)')
        fails += 1
        continue
    for (num, pg), rows in zip(progs, rows_by_prog):
        macros = builtin_macros(pg)
        diffs = []
        for field, macro, _ in game.RT_FIELDS:
            if macro not in macros:
                continue   # the builtin header leaves it out entirely; the runtime row defaults to 0
            r = same(field, macros[macro], rows, tid)
            if r is not True:
                diffs.append(r)
        for field, macro in game.RT_LISTS:
            if macro not in macros:
                continue
            r = same(field, macros[macro], rows, tid)
            if r is not True:
                diffs.append(r)
        checked += 1
        if diffs:
            fails += 1
            print(f'{tid} program {num}: {len(diffs)} difference(s)')
            for d in diffs:
                print(f'  {d}')
print(f'guard: {checked} program(s) checked, {fails} with differences')
sys.exit(1 if fails else 0)
