plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "de.skyler.jarvis"
    compileSdk = 35

    defaultConfig {
        applicationId = "de.skyler.jarvis"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "0.3." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
    }

    signingConfigs {
        create("jarvis") {
            // fester Schlüssel, damit sich jede neue Version über die alte installieren lässt
            storeFile = file("jarvis.keystore")
            storePassword = "jarvis-app"
            keyAlias = "jarvis"
            keyPassword = "jarvis-app"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("jarvis")
        }
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("jarvis")
        }
    }

    // Zwei Apps aus demselben Code: „privat“ (Jarvis, de.skyler.jarvis) und „konto“ (Jarvis Konto, für alle von der Website).
    // Beide werden bei jedem Update gebaut, beide aktualisieren sich selbst über ihren eigenen Download.
    buildFeatures { buildConfig = true }
    flavorDimensions += "art"
    productFlavors {
        create("privat") {
            dimension = "art"
            manifestPlaceholders["appLabel"] = "Jarvis"
            buildConfigField("String", "RELEASE_TAG", "\"neueste\"")
            buildConfigField("String", "APK_NAME", "\"Jarvis.apk\"")
            // Eigener Sprach-Agent (ElevenLabs) – kommt aus einem geheimen GitHub-Wert, steht nicht im Code
            buildConfigField("String", "LIVE_AGENT", "\"" + (System.getenv("JARVIS_AGENT_ID") ?: "").trim() + "\"")
        }
        create("konto") {
            dimension = "art"
            applicationIdSuffix = ".konto"
            versionNameSuffix = "-konto"
            manifestPlaceholders["appLabel"] = "Jarvis Konto"
            buildConfigField("String", "RELEASE_TAG", "\"konto-neueste\"")
            buildConfigField("String", "APK_NAME", "\"Jarvis-Konto.apk\"")
            buildConfigField("String", "LIVE_AGENT", "\"\"")   // für alle: ohne fremden Agenten (kostenlose Stimme)
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Samsung Health über Health Connect (Kalorien, Schritte, Sport)
    implementation("androidx.health.connect:connect-client:1.1.0-alpha12")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    // Aktivierungswort offline auf dem Handy (Vosk); Modell wird beim ersten Start geladen
    implementation("com.alphacephei:vosk-android:0.3.47@aar")
    implementation("net.java.dev.jna:jna:5.13.0@aar")
    // Gleiche Stimmen wie am PC (Piper), offline auf dem Handy – sherpa-onnx (nur arm64) + Entpacken der Stimmen
    implementation(files("libs/sherpa-onnx-1.13.8-arm64.aar"))
    implementation("org.apache.commons:commons-compress:1.21")
}
