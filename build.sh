#!/bin/sh
# Build the .deb from the package/ tree into build/.
# Usage: ./build.sh
set -e
cd "$(dirname "$0")"

name="$(sed -n 's/^Package: //p' package/DEBIAN/control)"
version="$(sed -n 's/^Version: //p' package/DEBIAN/control)"
out="build/${name}_${version}_all.deb"

# Git does not keep every permission bit; set them explicitly
chmod 755 package/DEBIAN/postinst package/DEBIAN/prerm package/DEBIAN/postrm \
          package/usr/bin/nautilus-new-document
chmod 644 package/DEBIAN/control \
          package/usr/share/doc/nautilus-new-named-document/copyright \
          package/usr/share/nautilus-python/extensions/new_named_document.py

mkdir -p build
dpkg-deb --root-owner-group --build package "$out"
echo "Built $out"
