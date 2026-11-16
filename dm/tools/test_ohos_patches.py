#!/usr/bin/env python3
# Guard for the OHOS port's syncability with upstream main.
#   python tools/test_ohos_patches.py [--upstream-dir DIR]
# Checks: (1) every patch in dm/ohos/patches applies cleanly to upstream main; (2) applying it reproduces the working port-edited
# file exactly (LF-normalized); (3) the additive OHOS dirs are present. Upstream main is extracted from the nested repo's own
# upstream/main ref (kept current by sync_upstream.py; no network, and never a shallow fetch, which would truncate the fork's
# history; --upstream-dir overrides with an already-extracted dm/. Upstream drift (a shared file that differs from main with no
# patch: an unsynced main or an accidental edit) is reported, not a failure. Exits non-zero if a patch is stale or broken.
import argparse, os, shutil, subprocess, sys, tarfile, tempfile
OURS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))          # dm/
PATCHES = os.path.join(OURS, "ohos", "patches")
ap = argparse.ArgumentParser()
ap.add_argument("--upstream-dir", help="an already-extracted upstream dm/ (skips the fetch)")
a = ap.parse_args()
def norm(p):
    with open(p, "rb") as fh: return fh.read().replace(b"\r\n", b"\n")
def walk(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f); out[os.path.relpath(p, root).replace(os.sep, "/")] = p
    return out
up_root = None
if a.upstream_dir:
    up = os.path.abspath(a.upstream_dir)
else:
    # The nested repo is a real fork: upstream main lives in its upstream/main ref. Extract from it -
    # never `git fetch --depth=1` here; a shallow fetch would truncate the fork's full upstream history.
    repo = subprocess.run(["git", "-C", OURS, "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    if subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", "upstream/main"], capture_output=True).returncode:
        sys.exit("test_ohos_patches.py: no upstream/main ref in the nested repo - run dm/tools/sync_upstream.py first, or pass --upstream-dir")
    up_root = tempfile.mkdtemp(prefix="ohos_guard_")
    # Python's tarfile, not bsdtar, and the temp dir is always cleaned up: leaked extractions (one full
    # upstream tree per run) once filled C:, and bsdtar on a full disk reports every create as a
    # misleading "No such file or directory" under its \\?\-prefixed temp path.
    try:
        with tempfile.TemporaryFile() as tar:
            subprocess.run(["git", "-C", repo, "archive", "upstream/main", "dm/"], stdout=tar, check=True); tar.seek(0)
            with tarfile.open(fileobj=tar, mode="r") as tf: tf.extractall(up_root, filter="fully_trusted")
    except BaseException:
        shutil.rmtree(up_root, ignore_errors=True); raise
    up = os.path.join(up_root, "dm")
u, o = walk(up), walk(OURS)
fails = []


def find_patch():
    """The GNU patch this guard needs, not whatever PATH calls 'patch'.

    On GitHub's windows-latest runner, PATH reaches Strawberry Perl's C:\\Strawberry\\c\\bin\\patch.exe before any
    GNU one, and that is a Perl script: it reads -p1 -f -s as its own arguments and dies with "File: .\\src\\patch",
    which the guard then reported as "does not apply to upstream" for every patch. A guard that fails because it
    found the wrong tool is worse than one that says it could not find the right one.

    Git for Windows ships GNU patch at <git>\\usr\\bin\\patch.exe, and the runner has git on PATH. The path is derived
    from git itself rather than hard-coded: this machine's git is on E:, and C:\\Program Files\\Git does not exist.
    """
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            # <git>\\cmd\\git.exe -> <git>\\usr\\bin\\patch.exe
            root = os.path.dirname(os.path.dirname(os.path.abspath(git)))
            cand = os.path.join(root, "usr", "bin", "patch.exe")
            if os.path.isfile(cand):
                return cand
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramW6432", r"C:\Program Files")):
            cand = os.path.join(base, "Git", "usr", "bin", "patch.exe")
            if os.path.isfile(cand):
                return cand
    return shutil.which("patch")


PATCH = find_patch()
if not PATCH:
    sys.exit("test_ohos_patches.py: no patch found - install Git for Windows (it ships GNU patch), or put one on PATH")

patches = sorted(os.path.relpath(os.path.join(dp, f), PATCHES).replace(os.sep, "/")
                 for dp, dn, fn in os.walk(PATCHES) for f in fn if f.endswith(".patch"))
tmp = tempfile.mkdtemp(prefix="ohos_guard_apply_")
for p in patches:
    rel = p[:-len(".patch")]
    if rel not in u: fails.append(f"{p}: target not in upstream"); continue
    dst = os.path.join(tmp, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(u[rel], dst)
    r = subprocess.run([PATCH, "-p1", "-f", "-s"], stdin=open(os.path.join(PATCHES, p), "rb"), cwd=tmp, capture_output=True)
    if r.returncode: fails.append(f"{p}: does not apply to upstream ({r.stderr.decode(errors='replace').strip()[:80]})"); continue
    if rel not in o: fails.append(f"{p}: patched file missing from working tree"); continue
    if norm(dst) != norm(o[rel]): fails.append(f"{p}: stale - applying to upstream does not reproduce the working file (re-run export_ohos_patches.py)")
for d in ("ohos", "compat", "gfx/vk"):
    if not os.path.isdir(os.path.join(OURS, d)): fails.append(f"additive dir missing: {d}")
drift = [rel for rel in sorted(o) if rel in u and not rel.startswith("ohos/patches/")
         and norm(o[rel]) != norm(u[rel]) and not os.path.exists(os.path.join(PATCHES, rel + ".patch"))
         and b"\0" not in norm(o[rel])]
print(f"guard: {len(patches)} patches checked, {len(fails)} failures, {len(drift)} upstream-drift files pending sync")
for f in fails: print("  FAIL", f)
for d in drift: print("  drift", d)
shutil.rmtree(tmp, ignore_errors=True)
if up_root: shutil.rmtree(up_root, ignore_errors=True)
sys.exit(1 if fails else 0)