# R8 для оболочки «Мадридиста».
# Мост JS → Android (window.MadridistaNative): методы с @JavascriptInterface вызываются из JavaScript
# по имени — R8 не должен их переименовывать или выкидывать.
-keepclassmembers class ru.realmadridfan.app.NativeBridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
