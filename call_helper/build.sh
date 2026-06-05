#!/bin/bash
set -e

ANDROID_HOME="$HOME/android-sdk"
BUILD_TOOLS="$ANDROID_HOME/android-14"
PLATFORM="$ANDROID_HOME/platforms/android-34/android.jar"

cd "$(dirname "$0")"

rm -rf build/classes build/dex build/*.apk
mkdir -p build/classes build/dex

# Compile
javac --release 8 -cp "$PLATFORM" -d build/classes src/com/coldcaller/CallHelper.java

# Convert to DEX
java -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 --release \
  --lib "$PLATFORM" --output build/dex build/classes/com/coldcaller/CallHelper.class

# Package APK
mkdir -p res/values
cat > res/values/strings.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">CallHelper</string>
</resources>
EOF

"$BUILD_TOOLS/aapt" package -f -M AndroidManifest.xml -S res -I "$PLATFORM" \
  -F build/CallHelper-unsigned.apk build/dex/

# Sign
if [ ! -f build/callhelper.keystore ]; then
  keytool -genkeypair -keystore build/callhelper.keystore -alias callhelper \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=CallHelper" \
    -storepass password -keypass password 2>/dev/null
fi

"$BUILD_TOOLS/apksigner" sign --ks build/callhelper.keystore --ks-pass pass:password \
  --ks-key-alias callhelper --out build/CallHelper.apk build/CallHelper-unsigned.apk

echo "Build complete: build/CallHelper.apk"
