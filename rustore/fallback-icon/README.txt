Запасная иконка без эмблемы клуба (золотая «М» в тонком кольце на тёмно-синем) — на случай, если модерация
RuStore не пропустит иконку с эмблемой Real Madrid (чужой товарный знак).

Как подменить:
1. Скопировать папки mipmap-* отсюда поверх android/app/src/main/res/mipmap-* (те же имена файлов).
2. В android/app/build.gradle.kts поднять versionCode (и versionName), собрать заново release.
3. В карточке RuStore заменить иконку на icon-512.png из этой папки (иконка в магазине и на устройстве
   должна совпадать).
4. Значок системного splash (drawable-*/splash_icon.png) и картинку экрана «Нет соединения» при этом тоже
   стоит заменить — их рисует tools/brand/make-android-icons.js (там же видно, как сделан этот вариант).

Пересобрать картинки: NODE_PATH=C:/Users/egor3/node_modules node tools/brand/make-android-icons.js
