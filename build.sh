#!/bin/bash
# Packages FTCTools for release as build/FTCTools-<version>.zip: the add-in
# folder, for Windows and macOS. The version comes from FTCTools.manifest.
# Needs jq and 7-Zip; set SEVENZIP if 7-Zip isn't in the default place.
set -euo pipefail
cd "$(dirname "$0")"

SEVENZIP=${SEVENZIP:-"/c/Program Files/7-Zip/7z.exe"}

version=$(jq -r .version FTCTools.manifest)
stage=build/stage/FTCTools
echo "FTCTools $version"

rm -rf build
mkdir -p "$stage"
cp FTCTools.py FTCTools.manifest LICENSE "$stage"/
cp -r commands "$stage"/
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +

# The zip holds the FTCTools folder itself, so it unzips ready to load.
(cd build/stage && "$SEVENZIP" a -tzip -bso0 -bsp0 "../FTCTools-$version.zip" FTCTools)

ls -l build/FTCTools-"$version".zip
