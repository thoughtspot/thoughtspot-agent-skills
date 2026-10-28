#!/usr/bin/env bash
# Maintainer pre-review check: run the customer-reference gate over a pull request,
# WITH your private customer-name list, before reviewing it.
#
# Run main's copy, NEVER a PR checkout's (a PR can change its own copy of this file):
#
#     ( set -e; git fetch origin main; f="$(mktemp)"; trap 'rm -f "$f"' EXIT
#       git show refs/remotes/origin/main:scripts/check-pr.sh >| "$f"; bash "$f" <pr-number> )
#
# Every run ends with a `check-pr: PR #N ...` verdict line. No verdict line: it did not run.
#
# Options:  --links-only   proceed without a name list (CI already checks links, so this
#                          adds little; without it, a missing or empty list is an error).
#
# Why this is local and not CI: a list of customer names is itself confidential. A
# repository secret is readable by everyone with push access, GitHub masks each line of
# a secret in logs, and any public pass/fail verdict on contributor-supplied text is an
# oracle for whether a guessed name is on the list. CI therefore checks links only.
#
# What it scans, each as its own section:
#   1. every non-merge commit in the PR: added lines and commit messages (--range);
#   2. what each merge commit's conflict resolution changed (`git show --remerge-diff`);
#      an octopus merge (3+ parents) is refused, because git cannot remerge one;
#   3. the PR title, head branch name, description, conversation comments, review bodies
#      and inline review comments;
#   4. every path any commit or merge resolution touched, both sides of a rename;
#   5. every raw commit object (author, committer, encoding and mergetag headers);
#   6. added content again: per non-merge commit, and the PR's net diff.
# Sections 2-6 use this script's own scanner: entities and percent-escapes decoded and
# invisible format characters removed, then the raw, NFC and NFKC forms each matched line
# by line AND with lines joined, so a name hard-wrapped, split by an invisible line
# separator, or decomposed is still caught. Not caught: a wrap completed against a line
# that is already on the base branch (that line is context, not added content).
# Section 1 is the checker's own per-line scan, which also reports links.
#
# NOT scanned (BL-400): binary files, UTF-16 text included (listed for a manual look; the
# run exits 3); base64 or compressed content; Git LFS object content; attachments;
# comments on individual commits; the edit history of PR text; other spellings of a name
# (accent-folded "Mueller" for "Müller", markup inside a name). Non-Latin names cannot be
# listed: such a list is refused.
#
# It never executes PR code. Commits are fetched as git objects and read as data, with
# git and Python run hermetically: no global or system git config (textconv drivers,
# diff prefixes, signature checks), no .gitattributes from the working tree, no
# PYTHONPATH. The checker is taken from origin/main.
#
# Exit status: 0 clean, 1 findings, 2 usage or setup error, 3 clean but binary files
# need a manual look.
set -euo pipefail
# C locale for the shell tools: macOS tr/sort abort on invalid UTF-8 in PR data.
export LC_ALL=C

usage() { echo "usage: check-pr.sh [--links-only] <pr-number>  (run main's copy; see its header)" >&2; exit 2; }

links_only=0
if [[ "${1:-}" == "--links-only" ]]; then links_only=1; shift; fi
pr="${1:-}"
[[ $# -eq 1 && "$pr" =~ ^[1-9][0-9]*$ ]] || usage
command -v gh >/dev/null || { echo "check-pr: needs the GitHub CLI (gh)" >&2; exit 2; }
# GIT_ATTR_SOURCE, GIT_CONFIG_GLOBAL and GIT_CONFIG_COUNT are silently ignored by older git.
IFS=. read -r gmaj gmin _ <<<"$(git version | awk '{ print $3 }')"
if ! (( gmaj > 2 || (gmaj == 2 && gmin >= 42) )); then
    echo "check-pr: needs git 2.42 or later" >&2; exit 2
fi

# One meaning for a relative list path, wherever the steps below run from.
if [[ -n "${TS_CUSTOMER_DENYLIST:-}" && "$TS_CUSTOMER_DENYLIST" != /* && "$TS_CUSTOMER_DENYLIST" != "~"* ]]; then
    export TS_CUSTOMER_DENYLIST="$PWD/$TS_CUSTOMER_DENYLIST"
fi

root="$(git rev-parse --show-toplevel)" || exit 2
cd "$root"

# Hermetic environment for every command that reads PR content.
EMPTY_TREE=4b825dc642cb6eb9a060e54bf8d69288fbee4904
hermetic() {
    env -u PYTHONPATH -u PYTHONHOME -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_ATTR_SOURCE="$EMPTY_TREE" \
        GIT_CONFIG_COUNT=5 \
        GIT_CONFIG_KEY_0=core.quotePath GIT_CONFIG_VALUE_0=false \
        GIT_CONFIG_KEY_1=diff.noprefix GIT_CONFIG_VALUE_1=false \
        GIT_CONFIG_KEY_2=diff.mnemonicPrefix GIT_CONFIG_VALUE_2=false \
        GIT_CONFIG_KEY_3=core.attributesFile GIT_CONFIG_VALUE_3=/dev/null \
        GIT_CONFIG_KEY_4=color.ui GIT_CONFIG_VALUE_4=never \
        "$@"
}
py() { hermetic python3 -E -s "$@"; }
# Terminal-safe output: PR text could otherwise carry escape sequences to the terminal.
# Drop control characters except tab and newline, including UTF-8-encoded C1 controls
# (U+0080-009F: CSI, OSC); every other byte passes through.
show() { perl -pe 's/[\x00-\x08\x0b-\x1f\x7f]//g; s/\xc2[\x80-\x9f]//g'; }

repo="$(gh repo view "$(git remote get-url origin)" --json nameWithOwner --jq .nameWithOwner)" \
    || { echo "check-pr: cannot resolve the origin repository with gh" >&2; exit 2; }
meta="$(gh pr view "$pr" --repo "$repo" --json baseRefName,headRefOid --jq '.baseRefName + " " + .headRefOid')" \
    || { echo "check-pr: cannot read PR #$pr in $repo" >&2; exit 2; }
read -r base head_oid <<<"$meta"
git check-ref-format --branch "$base" >/dev/null \
    || { echo "check-pr: unexpected base branch name" >&2; exit 2; }

ns="refs/check-pr/$pr-$$"
tmp="$(mktemp -d)"
cleanup() {
    local st=$?
    set +e
    case "$st" in 0|1|2|3) ;; *) st=2 ;; esac   # an aborted step is a setup error
    rm -rf "$tmp"
    git for-each-ref --format='%(refname)' "$ns/" | while read -r ref; do
        git update-ref -d "$ref" || true
    done
    exit "$st"
}
trap cleanup EXIT

git fetch --no-tags --quiet origin \
    "+refs/pull/$pr/head:$ns/head" \
    "+refs/heads/$base:$ns/base" \
    "+refs/heads/main:$ns/checker" \
    || { echo "check-pr: fetch failed" >&2; exit 2; }
head="$(git rev-parse "$ns/head^{commit}")"
if [[ "$head" != "$head_oid" ]]; then
    echo "check-pr: PR #$pr moved while fetching (GitHub says $head_oid). Run it again." >&2
    exit 2
fi
mb="$(git merge-base "$ns/base" "$head")" || exit 2

# The trusted checker: origin/main's copy, extracted outside the repo.
git archive "$ns/checker" tools/validate/check_customer_references.py tools/validate/_git.py \
    | tar -x -C "$tmp" || exit 2
vdir="$tmp/tools/validate"
checker="$vdir/check_customer_references.py"

# The scanner for sections 2-6: main's checker, called directly (not through
# --message-file, whose commit-message scissors handling would let one line hide the
# rest), over whole text, normalised, per line and with lines joined.
#   mode all: every finding; nowarn: FAIL only; diff: list hits in a patch's added lines
#   (split on newline only); paths: NUL-separated records.
cat > "$tmp/scan.py" <<'EOF'
import sys, unicodedata
vdir, title, path, mode, expected = sys.argv[1:6]
sys.path.insert(0, vdir)
import check_customer_references as c
d = c.load_denylist()
if (len(d) if d else 0) != int(expected):
    print("ERROR the private list changed during the run; this is not a finding. Run check-pr again.")
    sys.exit(1)

def forms(rec):
    # Decode entities and percent-escapes first, drop invisible format characters, THEN
    # normalise. Scan raw, NFC and NFKC forms: each one alone misses something (NFKC
    # turns a trademark sign into "TM"; raw misses decomposed accents).
    base = "\n".join("".join(ch for ch in c.decode_line(l) if unicodedata.category(ch) != "Cf")
                     for l in rec.splitlines())
    return dict.fromkeys([base, unicodedata.normalize("NFC", base),
                          unicodedata.normalize("NFKC", base)])

raw = open(path, "rb").read().decode("utf-8", "replace")
if mode == "diff":
    raw = "\n".join(l[1:] for l in raw.split("\n") if l.startswith("+"))
records = [r for r in raw.split("\0") if r] if mode == "paths" else [raw]
hits = []
for rec in records:
    seen = {}
    for text in forms(rec):
        found = c.scan_text(text, "", d, grandfathered=set())
        if d is not None:
            per_line = {h.match for h in found if h.rule == "customer-name"}
            for n in d.entries_in(" ".join(text.splitlines())):
                if f"<denylist entry #{n}>" not in per_line:
                    found.append(c.Hit(0, "customer-name",
                                       f"<denylist entry #{n}> (split across lines)", c._DENY_ADVICE))
        for h in found:
            seen.setdefault((h.line, h.rule, h.match), h)
    hits += seen.values()
if mode == "nowarn":
    hits = [h for h in hits if h.level == "FAIL"]
elif mode == "diff":
    hits = [h for h in hits if h.rule == "customer-name"]
for h in hits:
    c._emit(f"{title}, line {h.line}", h, d)
if not hits:
    print("No customer references.")
sys.exit(1 if any(h.level == "FAIL" for h in hits) else 0)
EOF

# The name check is the only thing this adds over CI: refuse to report "clean" without it,
# and refuse a list with entries the checker would silently ignore or misread.
listinfo="$(cd "$tmp" && py - "$vdir" <<'EOF'
import sys, unicodedata
sys.path.insert(0, sys.argv[1])
import check_customer_references as c
d = c.load_denylist()
kept = {n for _, n in (d.substrings + d.words)} if d else set()
bad = []
p = c.denylist_path()
if p.is_file():
    for n, line in enumerate(p.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        # Not kept, or not in the normal composed form the scanned text is folded to.
        if n not in kept or unicodedata.normalize("NFKC", name) != name:
            bad.append(n)
print(len(d) if d else 0, ",".join(map(str, bad)) or "-")
EOF
)" || { echo "check-pr: could not read the private list" >&2; exit 2; }
read -r entries dropped <<<"$(printf '%s\n' "$listinfo" | tail -n 1)"
[[ "$entries" =~ ^[0-9]+$ && -n "$dropped" ]] \
    || { echo "check-pr: could not read the private list" >&2; exit 2; }
if [[ "$entries" == "0" && $links_only -eq 0 ]]; then
    echo "check-pr: no usable names in the private list (missing, empty, or every entry under" >&2
    echo "          3 letters once normalised). Fix it, or pass --links-only. See .claude/rules/security.md." >&2
    exit 2
fi
if [[ "$dropped" != "-" ]]; then
    echo "check-pr: private list entries $dropped would be ignored or misread: a duplicate, under" >&2
    echo "          3 ASCII letters/digits once normalised (e.g. a non-Latin name), or not in" >&2
    echo "          composed Unicode (NFC/NFKC; common when copied from a macOS file name)." >&2
    echo "          Retype or remove them." >&2
    exit 2
fi

count="$(git rev-list --count "$mb..$head")" || exit 2
merges="$(git rev-list --merges "$mb..$head")" || exit 2
octopus="$(git rev-list --min-parents=3 "$mb..$head")" || exit 2
if [[ -n "$octopus" ]]; then
    echo "check-pr: PR #$pr has an octopus merge (${octopus:0:12}), which git cannot remerge," >&2
    echo "          so its changes cannot be scanned. Ask for it to be rebuilt." >&2
    exit 2
fi
echo "PR #$pr ($repo): $count commit(s) on $base, head ${head:0:12}; names in effect: $entries"
echo

rc=0
# Each section: collect its text into a file (a failed command is a setup error, never an
# empty section), then scan it in THIS shell so a finding can set rc.
section() {  # $1 = title, $2 = scan.py mode, rest = command producing the text
    local title="$1" mode="$2"; shift 2
    local f="$tmp/section.txt"
    "$@" > "$f" || { echo "check-pr: could not read: $title" >&2; exit 2; }
    echo "== $title"
    if [[ -s "$f" ]]; then
        py "$tmp/scan.py" "$vdir" "$title" "$f" "$mode" "$entries" 2>&1 | show || rc=1
    else
        echo "(nothing)"
    fi
    echo
}
remerge()    { hermetic git show --remerge-diff --no-color --no-ext-diff --no-textconv --format= "$1"; }
paths()      { hermetic git log -z --format= --name-only --no-renames --diff-merges=remerge "$mb..$head"; }
rawcommits() { git rev-list "$mb..$head" | git cat-file --batch; }
# Per commit, then the PR's net diff: a name wrapped across lines added by two different
# commits is only adjacent in the net diff.
content()    { hermetic git log -p --no-merges --no-color --no-ext-diff --no-textconv --format= "$mb..$head" \
                   && hermetic git diff --no-color --no-ext-diff --no-textconv "$mb" "$head"; }

echo "== Commits: added lines and commit messages"
py "$checker" --root "$root" --range "$mb..$head" 2>&1 | show || rc=1
echo

for m in $merges; do
    section "Merge ${m:0:12}: conflict resolution" all remerge "$m"
done
section "PR title and head branch name" all \
    gh pr view "$pr" --repo "$repo" --json title,headRefName --jq '.title, .headRefName'
section "PR description" all gh pr view "$pr" --repo "$repo" --json body --jq '.body'
section "Conversation comments" all \
    gh pr view "$pr" --repo "$repo" --json comments --jq '.comments[].body'
section "Review bodies" all gh pr view "$pr" --repo "$repo" --json reviews --jq '.reviews[].body'
section "Inline review comments" all \
    gh api "repos/$repo/pulls/$pr/comments" --paginate --jq '.[].body'
section "Every path touched" paths paths
section "Raw commit objects (authors, committers, headers)" nowarn rawcommits
section "Added content, lines joined (names only)" diff content

binaries="$(hermetic git log --format= --numstat --no-renames --diff-merges=remerge "$mb..$head" \
    | awk -F'\t' '$1 == "-" { print $3 }' | sort -u)" || exit 2

if [[ $rc -ne 0 ]]; then
    echo "check-pr: PR #$pr has customer references. Do not merge. See .claude/rules/security.md."
    exit 1
fi
if [[ -n "$binaries" ]]; then
    echo "check-pr: PR #$pr is clean as far as text goes, but these binary files were NOT scanned."
    echo "          Open each and check it by hand before merging:"
    printf '%s\n' "$binaries" | show | sed 's/^/            /'
    exit 3
fi
if [[ "$entries" == "0" ]]; then
    echo "check-pr: PR #$pr is clean of LINKS. Names were not checked (--links-only)."
else
    echo "check-pr: PR #$pr is clean."
fi
exit 0
