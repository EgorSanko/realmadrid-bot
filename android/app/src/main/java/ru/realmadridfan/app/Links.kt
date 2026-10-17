package ru.realmadridfan.app

import android.net.Uri

/**
 * Куда вести ссылку: внутри приложения (наш сайт), в Telegram или во внешний браузер.
 * Без Android-зависимостей, кроме Uri, — логика простая и проверяется на эмуляторе.
 */
object Links {
    /** Наш сайт: домен и www. Плюс хост START_URL (отладочная сборка с локальным сервером). */
    private val OWN_HOSTS = setOf("realmadridfan.ru", "www.realmadridfan.ru")
    private val TELEGRAM_HOSTS = setOf("t.me", "www.t.me", "telegram.me", "www.telegram.me", "telegram.dog")

    enum class Target { INSIDE, TELEGRAM, INTENT, EXTERNAL }

    fun isOwn(uri: Uri, startUri: Uri): Boolean {
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme != "https" && scheme != "http") return false
        val host = uri.host?.lowercase() ?: return false
        if (host in OWN_HOSTS) return scheme == "https"
        // отладка: тот же хост и порт, что у START_URL (например, 10.0.2.2:8080)
        return host == startUri.host?.lowercase() && uri.port == startUri.port && scheme == startUri.scheme
    }

    fun targetOf(uri: Uri, startUri: Uri): Target {
        val scheme = uri.scheme?.lowercase() ?: return Target.INSIDE
        return when {
            scheme == "about" || scheme == "data" || scheme == "blob" || scheme == "javascript" -> Target.INSIDE
            scheme == "tg" -> Target.TELEGRAM
            scheme == "intent" -> Target.INTENT
            (scheme == "https" || scheme == "http") && uri.host?.lowercase() in TELEGRAM_HOSTS -> Target.TELEGRAM
            isOwn(uri, startUri) -> Target.INSIDE
            else -> Target.EXTERNAL
        }
    }

    /**
     * https://t.me/<бот>?start=login_xxx → tg://resolve?domain=<бот>&start=login_xxx — так ссылку откроет
     * любой установленный клиент Telegram, а не браузер. Ссылки, которые не переводятся (приглашения
     * в чаты и т. п.), — null: их откроем как https (Telegram перехватит их сам или откроется браузер).
     */
    fun toTelegramDeepLink(uri: Uri): Uri? {
        if (uri.scheme?.lowercase() == "tg") return uri
        val segs = uri.pathSegments.filter { it.isNotEmpty() }
        if (segs.isEmpty()) return null
        val domain = segs[0]
        if (domain.startsWith("+") || domain == "joinchat" || domain == "addstickers" || domain == "share") return null
        if (!Regex("^[A-Za-z0-9_]{4,64}$").matches(domain)) return null
        val b = Uri.Builder().scheme("tg").authority("resolve").appendQueryParameter("domain", domain)
        if (segs.size >= 2 && segs[1].all { it.isDigit() }) b.appendQueryParameter("post", segs[1])
        for (name in uri.queryParameterNames) {
            if (name == "domain") continue
            uri.getQueryParameter(name)?.let { b.appendQueryParameter(name, it) }
        }
        return b.build()
    }
}
