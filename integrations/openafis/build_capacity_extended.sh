#!/usr/bin/env bash
# Stage 19B — patch the pinned OpenAFIS tree and build the capacity-extended bridge.
# The diff is two lines in lib/Template.cpp; see docs/adr/0136.
set -e
SRC=/mnt/c/Users/sirak/.cache/fpbench/third_party/openafis/repo
WORK=$HOME/stage19b-openafis
rm -rf "$WORK"; mkdir -p "$WORK"
cp -r "$SRC" "$WORK/upstream"
rm -rf "$WORK/upstream/.git"
cp -r "$WORK/upstream" "$WORK/pristine"

python3 - "$WORK/upstream/lib/Template.cpp" <<'PY'
import sys, pathlib
# Bytes, not text: the checkout carries CRLF and a text-mode round trip would
# rewrite every line ending, burying the one real change in a whole-file diff.
p = pathlib.Path(sys.argv[1])
data = p.read_bytes()
eol = b"\r\n" if b"\r\n" in data else b"\n"
old = eol.join([
    b'        if (minutiae.size() > MaximumMinutiae) {',
    b'            Log::error("minutiea count > MaximumMinutiae");',
    b'            return false;',
    b'        }',
    b'',
])
new = eol.join([
    b'#ifndef FPBENCH_STAGE19B_ALLOW_ABOVE_MAXIMUM_MINUTIAE',
    b'        if (minutiae.size() > MaximumMinutiae) {',
    b'            Log::error("minutiea count > MaximumMinutiae");',
    b'            return false;',
    b'        }',
    b'#endif',
    b'',
])
assert data.count(old) == 1, f"expected one occurrence, found {data.count(old)}"
p.write_bytes(data.replace(old, new))
print(f"patched with {'CRLF' if eol == b'\r\n' else 'LF'} endings preserved")
PY

cd "$WORK"
diff -u pristine/lib/Template.cpp upstream/lib/Template.cpp > stage19b.patch || true
echo "=== the complete algorithmic diff ==="
cat stage19b.patch
echo "=== every file differing ==="
diff -rq pristine upstream || true
echo "=== hashes ==="
echo "pristine Template.cpp : $(sha256sum pristine/lib/Template.cpp | cut -d' ' -f1)"
echo "patched  Template.cpp : $(sha256sum upstream/lib/Template.cpp | cut -d' ' -f1)"
echo "patch                 : $(sha256sum stage19b.patch | cut -d' ' -f1)"
WORK=$HOME/stage19b-openafis
mkdir -p "$WORK/bridge/src"
# The bridge source is Stage 18A's, unchanged: its bytes are pinned by 18A's
# published marker, so 19B builds the same file against a different tree.
cp /mnt/c/fingerprint-benchmark/integrations/openafis/Makefile "$WORK/bridge/"
cp /mnt/c/fingerprint-benchmark/integrations/openafis/src/*.cpp "$WORK/bridge/src/"
cd "$WORK/bridge"
make FPBENCH_OPENAFIS_SOURCE="$WORK/upstream" \
     CXXFLAGS="-std=c++17 -O3 -march=native -mtune=native -fstrict-aliasing -Wall -Wextra -Wno-deprecated -DFPBENCH_STAGE19B_ALLOW_ABOVE_MAXIMUM_MINUTIAE" \
     2>&1 | tail -5
echo "=== identity ==="
./build/fpbench_openafis_bridge identity
echo "=== hashes ==="
echo "bridge source  : $(sha256sum src/fpbench_openafis_bridge.cpp | cut -d' ' -f1)"
echo "bridge binary  : $(sha256sum build/fpbench_openafis_bridge | cut -d' ' -f1)"
echo "g++            : $(g++ --version | head -1)"
