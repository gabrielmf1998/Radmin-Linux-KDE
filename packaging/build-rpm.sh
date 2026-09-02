#!/usr/bin/env bash
# Constroi o RPM do radmin-linux (so o codigo; a imagem da VM e a parte).
set -euo pipefail
SELF="$(cd "$(dirname "$0")/.." && pwd)"
TOP="${1:-$HOME/rpmbuild}"
mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
# rpmbuild com o codigo no BUILD (sem tarball, build local)
cp "$SELF/packaging/radmin-linux.spec" "$TOP/SPECS/"
rpmbuild --define "_topdir $TOP" \
         --define "srcdir $SELF" \
         -bb "$TOP/SPECS/radmin-linux.spec"
echo "RPM em: $TOP/RPMS/noarch/"
ls -la "$TOP/RPMS/noarch/"*.rpm 2>/dev/null
