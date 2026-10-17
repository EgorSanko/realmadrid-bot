import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

/*
 * Подпись релиза. Ключ и пароли в репозиторий не попадают. Откуда берутся (первое найденное):
 *  1. файл android/keystore.properties (в .gitignore) или путь из переменной RMV2_KEYSTORE_PROPS;
 *     ключи: storeFile, storePassword, keyAlias, keyPassword;
 *  2. переменные окружения RMV2_STORE_FILE, RMV2_STORE_PASSWORD, RMV2_KEY_ALIAS, RMV2_KEY_PASSWORD.
 * Не нашлось — release собирается неподписанным (Gradle об этом предупредит).
 */
val signing: Map<String, String>? = run {
    val path = System.getenv("RMV2_KEYSTORE_PROPS") ?: rootProject.file("keystore.properties").path
    val f = file(path)
    if (f.isFile) {
        val p = Properties().apply { f.inputStream().use { load(it) } }
        listOf("storeFile", "storePassword", "keyAlias", "keyPassword").associateWith { p.getProperty(it) ?: "" }
    } else {
        val env = mapOf(
            "storeFile" to System.getenv("RMV2_STORE_FILE"),
            "storePassword" to System.getenv("RMV2_STORE_PASSWORD"),
            "keyAlias" to System.getenv("RMV2_KEY_ALIAS"),
            "keyPassword" to System.getenv("RMV2_KEY_PASSWORD"),
        )
        if (env.values.all { !it.isNullOrBlank() }) env.mapValues { it.value!! } else null
    }
}

// Адрес сайта. Для проверки на эмуляторе с локальным сервером: ./gradlew assembleDebug -PstartUrl=http://10.0.2.2:8080/
val siteUrl: String = (project.findProperty("startUrl") as String?) ?: "https://realmadridfan.ru/"

android {
    namespace = "ru.realmadridfan.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "ru.realmadridfan.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        buildConfigField("String", "START_URL", "\"https://realmadridfan.ru/\"")
        // отладка WebView через chrome://inspect — только в debug и check, в релизе выключена
        buildConfigField("boolean", "WEB_DEBUG", "false")
    }

    signingConfigs {
        if (signing != null) {
            create("release") {
                storeFile = file(signing.getValue("storeFile"))
                storePassword = signing.getValue("storePassword")
                keyAlias = signing.getValue("keyAlias")
                keyPassword = signing.getValue("keyPassword")
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "START_URL", "\"$siteUrl\"")
            buildConfigField("boolean", "WEB_DEBUG", "true")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (signing != null) signingConfig = signingConfigs.getByName("release")
        }
        // как release (R8, сжатие ресурсов), но на локальный сервер и с отладочной подписью — проверить,
        // что минификация не сломала WebView и мост MadridistaNative: ./gradlew assembleCheck -PstartUrl=…
        create("check") {
            initWith(getByName("release"))
            applicationIdSuffix = ".check"
            versionNameSuffix = "-check"
            signingConfig = signingConfigs.getByName("debug")
            buildConfigField("String", "START_URL", "\"$siteUrl\"")
            buildConfigField("boolean", "WEB_DEBUG", "true")
            matchingFallbacks += listOf("release")
        }
    }

    sourceSets {
        // локальный http-сервер разрешён только отладочным сборкам (debug и check)
        getByName("check").res.srcDir("src/debug/res")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // без телеметрии сборки в APK/AAB (блок «dependencies info», который читает только Google Play)
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    packaging {
        resources.excludes += setOf("META-INF/*.version", "META-INF/**/LICENSE*", "kotlin/**", "DebugProbesKt.bin")
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-splashscreen:1.0.1")
}
