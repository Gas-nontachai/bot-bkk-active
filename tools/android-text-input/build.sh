#!/bin/sh
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD="$SOURCE/.build"
SDK=${ANDROID_SDK_ROOT:-"$HOME/Library/Android/sdk"}
JAVA_HOME=${JAVA_HOME:-"/Applications/Android Studio.app/Contents/jbr/Contents/Home"}
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
TOOLS="$SDK/build-tools/36.0.0"
ANDROID="$SDK/platforms/android-36/android.jar"
mkdir -p "$BUILD/classes" "$BUILD/dex"
javac -source 8 -target 8 -Xlint:-options -classpath "$ANDROID" -d "$BUILD/classes" "$SOURCE/TextInput.java"
"$TOOLS/d8" --lib "$ANDROID" --output "$BUILD/dex" "$BUILD/classes/local/bkkactive/textinput/TextInput.class"
"$TOOLS/aapt" package -f -M "$SOURCE/AndroidManifest.xml" -I "$ANDROID" -F "$BUILD/text-input-unsigned.apk"
(cd "$BUILD/dex" && "$TOOLS/aapt" add "$BUILD/text-input-unsigned.apk" classes.dex)
if [ ! -f "$BUILD/debug.keystore" ]; then
    keytool -genkeypair -keystore "$BUILD/debug.keystore" -storepass android -keypass android -alias androiddebugkey -dname "CN=BKK Active local helper" -keyalg RSA -validity 3650
fi
"$TOOLS/apksigner" sign --ks "$BUILD/debug.keystore" --ks-pass pass:android --out "$BUILD/text-input.apk" "$BUILD/text-input-unsigned.apk"
