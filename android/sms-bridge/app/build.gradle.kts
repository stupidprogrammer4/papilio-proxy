plugins { id("com.android.application") }
android {
    namespace = "net.papilio.smsbridge"
    compileSdk = 37
    defaultConfig { applicationId = "net.papilio.smsbridge"; minSdk = 26; targetSdk = 37; versionCode = 3; versionName = "0.3.0" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
