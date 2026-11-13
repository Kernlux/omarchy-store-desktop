#!/usr/bin/bash
# Build release/omarchy-store-desktop-<VERSION>.tar.gz and its .sha256, then pin that sum in pkg/PKGBUILD.
# Run from a clean checkout. No network. Refuses to release a build whose --self-test or tests fail, or a dirty git tree.
# Reproducible: the archive's mtime is SOURCE_DATE_EPOCH, defaulting to the newest mtime among the shipped sources
# (or the last commit time inside git), and the epoch used is printed so anyone can rebuild the same bytes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

V="$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' omarchy-store-desktop.py)"
[[ -n "$V" ]] || { echo "could not read VERSION"; exit 1; }
rm -f "release/omarchy-store-desktop-$V.tar.gz" "release/omarchy-store-desktop-$V.tar.gz.sha256"   # a stale archive must never be re-pinned
/usr/bin/python3 -I omarchy-store-desktop.py --self-test >/dev/null 2>&1 || { echo "self-test failed; not releasing"; exit 1; }
command -v pytest >/dev/null 2>&1 || { echo "python-pytest is required to release (tests/ hold the no-hook and packaging assertions)"; exit 1; }
python3 -m pytest -q tests/ >/dev/null || { echo "tests failed; not releasing"; exit 1; }
grep -q "^pkgver=$V\$" pkg/PKGBUILD || { echo "pkg/PKGBUILD pkgver is not $V"; exit 1; }
[[ -f "SECURITY-REVIEW-$V.md" ]] && grep -q '^## ' "SECURITY-REVIEW-$V.md" && ! grep -qi '(draft' "SECURITY-REVIEW-$V.md" || { echo "SECURITY-REVIEW-$V.md is missing or still a draft"; exit 1; }
# The numbers the documents quote must be the real ones.
n_checks="$(/usr/bin/python3 -I omarchy-store-desktop.py --self-test 2>/dev/null | tail -1 | cut -d' ' -f1)"
for doc in README.md SECURITY.md "SECURITY-REVIEW-$V.md"; do grep -q "$n_checks checks" "$doc" || { echo "$doc does not say '$n_checks checks'"; exit 1; }; done
line="$(python3 -m pytest -q tests/ 2>/dev/null | tail -1)"; passed="$(grep -o '[0-9]* passed' <<<"$line" | cut -d' ' -f1)"; skipped="$(grep -o '[0-9]* skipped' <<<"$line" | cut -d' ' -f1)"
n_tests=$(( ${passed:-0} + ${skipped:-0} ))     # the release-consistency test skips while the archive is being rebuilt
for doc in README.md SECURITY.md "SECURITY-REVIEW-$V.md"; do grep -q "$n_tests tests" "$doc" || { echo "$doc does not say '$n_tests tests' (or tests fail)"; exit 1; }; done
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --quiet && git diff --cached --quiet || { echo "git tree is not clean; commit first"; exit 1; }
  : "${SOURCE_DATE_EPOCH:=$(git log -1 --format=%ct)}"
fi
# (pkg/PKGBUILD is an OUTPUT of this script — its mtime must not feed the epoch, or two runs on one tree would differ)
: "${SOURCE_DATE_EPOCH:=$(stat -c %Y omarchy-store-desktop.py install.sh LICENSE README.md SECURITY.md "SECURITY-REVIEW-$V.md" data/* tests/test_security.py | sort -n | tail -1)}"
export SOURCE_DATE_EPOCH
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || echo "WARNING: not a git tree — no clean-tree check; release from a committed checkout when you can" >&2

stage="$(mktemp -d)"; trap 'rm -rf "$stage"' EXIT
d="$stage/omarchy-store-desktop-$V"
mkdir -p "$d/data" "$d/pkg" "$d/tests"
cp omarchy-store-desktop.py install.sh LICENSE README.md SECURITY.md "SECURITY-REVIEW-$V.md" "$d/"
cp tests/test_security.py "$d/tests/"
printf 'version=%s\nsource_date_epoch=%s\n' "$V" "$SOURCE_DATE_EPOCH" > "$d/RELEASE-INFO"   # the one generated file: how to rebuild these bytes
cp data/com.omarchystore.Store.desktop data/com.omarchystore.Store.png data/omarchy-store-desktop "$d/data/"
cp data/lockup.png "$d/data/"; mkdir -p "$d/data/icons"; cp data/icons/48.png data/icons/64.png data/icons/128.png data/icons/256.png "$d/data/icons/"
# The PKGBUILD copy inside the archive cannot contain the archive's own hash; mark it and say where the real one is.
sed "s|^sha256sums=.*|sha256sums=('SKIP')  # this copy travels inside the archive it would hash; pkg/PKGBUILD in the repo and on the AUR pin the real sum|" pkg/PKGBUILD > "$d/pkg/PKGBUILD"
find "$d" -type f -exec chmod 0644 {} +
chmod 0755 "$d/install.sh" "$d/data/omarchy-store-desktop"
find "$d" -type d -exec chmod 0755 {} +

mkdir -p release
out="release/omarchy-store-desktop-$V.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$SOURCE_DATE_EPOCH" --format=gnu \
    -C "$stage" -cf - "omarchy-store-desktop-$V" | gzip -n -9 > "$out"
sum="$(sha256sum "$out" | cut -d' ' -f1)"
printf '%s  %s\n' "$sum" "$(basename "$out")" > "$out.sha256"   # bare file name so `sha256sum -c` works from the download dir
sed -i "s|^sha256sums=.*|sha256sums=('$sum')|" pkg/PKGBUILD
sed -i "s|^\tsha256sums = .*|\tsha256sums = $sum|; s|^\tpkgver = .*|\tpkgver = $V|" pkg/.SRCINFO   # keep the AUR metadata in step
echo "built $out (SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH)"; cat "$out.sha256"
