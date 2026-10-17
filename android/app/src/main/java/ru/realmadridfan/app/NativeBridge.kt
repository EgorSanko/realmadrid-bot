package ru.realmadridfan.app

import android.webkit.JavascriptInterface

/**
 * Мост JS → Android: `window.MadridistaNative` на страницах сайта. Только безобидные действия,
 * каждое открывает системный экран, где человек сам подтверждает: меню «Поделиться» и
 * «Новое событие» в календаре. Работает, только пока в WebView открыт наш сайт (см. MainActivity.onOwnSite).
 * Методы вызываются из потока JavaBridge — всё, что трогает UI, переносится в главный поток.
 */
class NativeBridge(private val activity: MainActivity) {

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    /** Системное меню «Поделиться» (navigator.share в WebView не работает). */
    @JavascriptInterface
    fun share(text: String?, url: String?) {
        val body = listOfNotNull(text?.takeIf { it.isNotBlank() }, url?.takeIf { it.isNotBlank() })
            .joinToString("\n")
            .take(2000)
        if (body.isEmpty()) return
        activity.runOnUiThread { activity.shareText(body) }
    }

    /** Матч — в календарь устройства: открывается экран нового события, сохраняет человек сам. */
    @JavascriptInterface
    fun addToCalendar(title: String?, startMs: Double, endMs: Double, location: String?, description: String?) {
        val t = title?.trim()?.take(200).orEmpty()
        if (t.isEmpty() || startMs <= 0 || endMs < startMs) return
        activity.runOnUiThread {
            activity.addToCalendar(t, startMs.toLong(), endMs.toLong(), location?.take(200), description?.take(1000))
        }
    }
}
