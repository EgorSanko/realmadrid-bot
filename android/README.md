# «Мадридиста» для Android (RuStore)

WebView-оболочка сайта https://realmadridfan.ru/ — пакет `ru.realmadridfan.app`. Сайт узнаёт приложение по
User-Agent `MadridistaApp/<версия> (Android; RuStore)` (frontend/src/lib/shell.ts): прячет трансляцию и виджет
входа Telegram, показывает «У меня есть код доступа» в профиле.

## Сборка

Нужны JDK 17+ (подходит `C:\Program Files\Android\Android Studio\jbr`) и Android SDK (`local.properties`:
`sdk.dir=C\:\\Users\\egor3\\AppData\\Local\\Android\\Sdk`).

```bash
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"
cd android
./gradlew assembleRelease bundleRelease     # app/build/outputs/apk/release/app-release.apk, bundle/release/app-release.aab
./gradlew assembleDebug -PstartUrl=http://10.0.2.2:8080/   # отладка на эмуляторе с локальным сервером
./gradlew assembleCheck -PstartUrl=http://10.0.2.2:8080/   # как release (R8), но на локальный сервер
```

Подпись релиза: файл `android/keystore.properties` (в git не попадает) или переменные окружения
`RMV2_STORE_FILE`, `RMV2_STORE_PASSWORD`, `RMV2_KEY_ALIAS`, `RMV2_KEY_PASSWORD`:

```
storeFile=C:/Users/egor3/.keystores/realmadridfan-release.jks
storePassword=…
keyAlias=madridista
keyPassword=…
```

Ключ и пароли — `C:\Users\egor3\.keystores\realmadridfan-release.txt`. Потеря ключа = нельзя обновить
приложение в RuStore, держите копию.

Новая версия: поднять `versionCode` (обязательно) и `versionName` в `app/build.gradle.kts`.

## Что умеет оболочка

- ссылки realmadridfan.ru — внутри; t.me / tg: — в Telegram (нет — в браузере); прочие — во внешнем браузере;
  iframe YouTube на странице видео играет внутри, во весь экран — с поворотом;
- «Назад»: полный экран → история SPA → выход;
- «Нет соединения» / «Сервер не отвечает» — только для главного документа, кнопка «Повторить»;
- мост `window.MadridistaNative`: `share(text, url)`, `addToCalendar(title, startMs, endMs, place, text)`;
- иконки: `tools/brand/make-android-icons.js`; запасная без эмблемы — `rustore/fallback-icon/`.
