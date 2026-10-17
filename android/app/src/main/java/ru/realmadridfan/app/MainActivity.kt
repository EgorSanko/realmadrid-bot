package ru.realmadridfan.app

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.CalendarContract
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * «Мадридиста» — оболочка сайта https://realmadridfan.ru/ для RuStore.
 *
 *  - один экран: WebView без адресной строки; к User-Agent дописано « MadridistaApp/<версия> (Android; RuStore)»,
 *    по нему сайт прячет трансляцию и виджет входа Telegram (frontend/src/lib/shell.ts);
 *  - ссылки нашего домена — внутри, t.me / tg: — в Telegram (нет его — в браузере), остальное — во внешнем браузере;
 *    iframe YouTube на странице видео играет внутри, во весь экран — с поворотом;
 *  - «Назад»: закрыть полноэкранное видео → история WebView (в ней и pushState SPA) → выход;
 *  - нет сети / сервер ответил 5xx на главный документ — свой экран с «Повторить» (ошибки картинок и API
 *    его не вызывают);
 *  - системный splash держится до первой отрисовки страницы (не дольше SPLASH_MAX_MS), дальше — заставка сайта.
 */
class MainActivity : ComponentActivity() {

    companion object {
        private const val SPLASH_MAX_MS = 6000L
        private const val UA_SUFFIX_PREFIX = " MadridistaApp/"
        private const val STATE_WEB = "web"
        private const val SPA_CAN_BACK =
            "(function(){try{var s=history.state;return !!(s&&typeof s.idx==='number'&&s.idx>0)}catch(e){return false}})()"
    }

    private lateinit var web: WebView
    private lateinit var content: FrameLayout
    private lateinit var fullscreen: FrameLayout
    private lateinit var offline: View
    private lateinit var offlineTitle: TextView
    private lateinit var offlineText: TextView
    private lateinit var retry: Button
    private lateinit var retryProgress: ProgressBar

    private val startUri: Uri = Uri.parse(BuildConfig.START_URL)
    private val main = Handler(Looper.getMainLooper())

    @Volatile private var splashDone = false
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null

    /** Адрес главного документа, который сейчас грузится, и была ли у него ошибка. */
    private var loadingUrl: String? = null
    private var mainFailed = false
    private var failedUrl: String? = null

    /** Открыт ли в WebView наш сайт — мост MadridistaNative отвечает только тогда. Пишется в главном потоке. */
    @Volatile var onOwnSite = false
        private set

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        val bg = getColor(R.color.bg)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(bg),
            navigationBarStyle = SystemBarStyle.dark(bg),
        )
        setContentView(R.layout.activity_main)
        splash.setKeepOnScreenCondition { !splashDone }
        main.postDelayed({ splashDone = true }, SPLASH_MAX_MS)

        content = findViewById(R.id.content)
        fullscreen = findViewById(R.id.fullscreen)
        web = findViewById(R.id.web)
        offline = findViewById(R.id.offline)
        offlineTitle = findViewById(R.id.offline_title)
        offlineText = findViewById(R.id.offline_text)
        retry = findViewById(R.id.retry)
        retryProgress = findViewById(R.id.retry_progress)

        // контент не уходит под статус-бар, навбар/жестовую панель, вырез и клавиатуру;
        // полоски по краям — того же цвета #06070B, что и фон сайта
        ViewCompat.setOnApplyWindowInsetsListener(content) { v, insets ->
            val i = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or
                    WindowInsetsCompat.Type.ime(),
            )
            v.setPadding(i.left, i.top, i.right, i.bottom)
            WindowInsetsCompat.CONSUMED
        }

        setupWebView()
        retry.setOnClickListener { retryLoad() }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    customView != null -> exitFullscreen()
                    // SPA: react-router кладёт в history.state номер шага (idx). Записи pushState, сделанные без
                    // жеста пользователя (переход после входа, редирект), Chromium помечает «пропускаемыми», и
                    // WebView.canGoBack() их не видит — поэтому сначала спрашиваем саму страницу.
                    onOwnSite && offline.visibility != View.VISIBLE -> web.evaluateJavascript(SPA_CAN_BACK) { r ->
                        if (r == "true") web.evaluateJavascript("history.back()", null) else nativeBack()
                    }
                    else -> nativeBack()
                }
            }

            private fun nativeBack() {
                if (web.canGoBack()) {
                    hideError()
                    web.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                    isEnabled = true
                }
            }
        })

        val restored = savedInstanceState?.getBundle(STATE_WEB)?.let { web.restoreState(it) }
        if (restored == null || web.url == null) web.loadUrl(BuildConfig.START_URL)
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    private fun setupWebView() {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.WEB_DEBUG)
        web.setBackgroundColor(getColor(R.color.bg))
        web.overScrollMode = View.OVER_SCROLL_NEVER
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = true
            setSupportMultipleWindows(false)       // target=_blank и window.open — через shouldOverrideUrlLoading
            javaScriptCanOpenWindowsAutomatically = false
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            textZoom = 100                           // вёрстка сайта рассчитана на свой размер шрифта
            userAgentString = userAgentString + UA_SUFFIX_PREFIX + BuildConfig.VERSION_NAME + " (Android; RuStore)"
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)                    // rm_session живёт между запусками
            setAcceptThirdPartyCookies(web, true)    // встроенный плеер YouTube
        }
        web.addJavascriptInterface(NativeBridge(this), "MadridistaNative")
        web.setDownloadListener { url, _, _, _, _ -> openExternal(Uri.parse(url)) }
        web.webViewClient = Client()
        web.webChromeClient = Chrome()
    }

    // ---------- навигация и ошибки ----------

    private inner class Client : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            // iframe (плеер YouTube на странице видео) — грузится внутри как есть
            if (!request.isForMainFrame) return false
            return route(request.url)
        }

        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            loadingUrl = url
            // onReceivedHttpError (5xx) приходит раньше onPageStarted — ошибку этого же адреса не сбрасываем
            if (url != failedUrl) mainFailed = false
            onOwnSite = Links.isOwn(Uri.parse(url), startUri)
        }

        override fun onPageCommitVisible(view: WebView, url: String) {
            if (!mainFailed) {
                splashDone = true
                hideError()
            }
        }

        override fun onPageFinished(view: WebView, url: String) {
            splashDone = true
            if (!mainFailed) hideError()
            onOwnSite = Links.isOwn(Uri.parse(url), startUri)
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            // ошибки картинок, API и iframe — не повод показывать «нет соединения»
            if (!request.isForMainFrame) return
            if (error.errorCode == ERROR_UNSUPPORTED_SCHEME) return
            showError(request.url.toString(), server = false)
        }

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
            // 404 сайта — его собственная страница «не найдено»; 5xx главного документа — наш экран
            if (request.isForMainFrame && response.statusCode >= 500 && Links.isOwn(request.url, startUri)) {
                showError(request.url.toString(), server = true)
            }
        }

        @SuppressLint("WebViewClientOnReceivedSslError")
        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            handler.cancel()
            if (error.url == loadingUrl) showError(error.url, server = false)
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            // процесс отрисовки упал (нехватка памяти) — пересоздаём экран, а не роняем приложение
            recreate()
            return true
        }
    }

    /** true — ссылку обработали сами (не грузить в WebView). */
    private fun route(uri: Uri): Boolean = when (Links.targetOf(uri, startUri)) {
        Links.Target.INSIDE -> false
        Links.Target.TELEGRAM -> {
            openTelegram(uri)
            true
        }
        Links.Target.INTENT -> {
            openIntentUri(uri)
            true
        }
        Links.Target.EXTERNAL -> {
            openExternal(uri)
            true
        }
    }

    private fun showError(url: String?, server: Boolean) {
        mainFailed = true
        failedUrl = url
        splashDone = true
        offlineTitle.setText(if (server) R.string.server_title else R.string.offline_title)
        offlineText.setText(if (server) R.string.server_text else R.string.offline_text)
        retry.isEnabled = true
        retryProgress.visibility = View.INVISIBLE
        offline.visibility = View.VISIBLE
    }

    private fun hideError() {
        offline.visibility = View.GONE
        retryProgress.visibility = View.INVISIBLE
        retry.isEnabled = true
    }

    private fun retryLoad() {
        retry.isEnabled = false
        retryProgress.visibility = View.VISIBLE
        val url = failedUrl?.takeIf { Links.isOwn(Uri.parse(it), startUri) } ?: BuildConfig.START_URL
        failedUrl = null
        mainFailed = false
        web.loadUrl(url)
    }

    // ---------- внешние приложения ----------

    private fun openTelegram(uri: Uri) {
        Links.toTelegramDeepLink(uri)?.let { tg ->
            if (tryStart(Intent(Intent.ACTION_VIEW, tg))) return
        }
        // Telegram не установлен (или ссылка не переводится в tg://) — как обычная https-ссылка
        val https = if (uri.scheme == "tg") Uri.parse("https://t.me/") else uri
        openExternal(https)
    }

    private fun openIntentUri(uri: Uri) {
        val s = uri.toString()
        val intent = try {
            Intent.parseUri(s, Intent.URI_INTENT_SCHEME)
        } catch (e: Exception) {
            null
        }
        if (intent != null) {
            intent.addCategory(Intent.CATEGORY_BROWSABLE)
            intent.component = null
            intent.selector = null
            if (tryStart(intent)) return
            intent.getStringExtra("browser_fallback_url")?.let { fb ->
                val f = Uri.parse(fb)
                if (f.scheme == "https" || f.scheme == "http") {
                    if (!route(f)) web.loadUrl(fb)
                    return
                }
            }
        }
        toast(R.string.no_app_for_link)
    }

    private fun openExternal(uri: Uri) {
        val i = Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)
        if (!tryStart(i)) toast(R.string.no_app_for_link)
    }

    private fun tryStart(intent: Intent): Boolean = try {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        true
    } catch (e: ActivityNotFoundException) {
        false
    } catch (e: SecurityException) {
        false
    }

    fun shareText(body: String) {
        if (!onOwnSite) return
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, body)
        tryStart(Intent.createChooser(send, getString(R.string.share_title)))
    }

    fun addToCalendar(title: String, startMs: Long, endMs: Long, location: String?, description: String?) {
        if (!onOwnSite) return
        val i = Intent(Intent.ACTION_INSERT)
            .setData(CalendarContract.Events.CONTENT_URI)
            .putExtra(CalendarContract.Events.TITLE, title)
            .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, startMs)
            .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, endMs)
        location?.takeIf { it.isNotBlank() }?.let { i.putExtra(CalendarContract.Events.EVENT_LOCATION, it) }
        description?.takeIf { it.isNotBlank() }?.let { i.putExtra(CalendarContract.Events.DESCRIPTION, it) }
        if (!tryStart(i)) toast(R.string.calendar_none)
    }

    private fun toast(res: Int) = Toast.makeText(this, res, Toast.LENGTH_SHORT).show()

    // ---------- полноэкранное видео ----------

    private inner class Chrome : WebChromeClient() {
        override fun onShowCustomView(view: View, callback: CustomViewCallback) {
            if (customView != null) {
                callback.onCustomViewHidden()
                return
            }
            customView = view
            customCallback = callback
            fullscreen.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            fullscreen.visibility = View.VISIBLE
            content.visibility = View.INVISIBLE
            WindowCompat.getInsetsController(window, window.decorView).apply {
                systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                hide(WindowInsetsCompat.Type.systemBars())
            }
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        }

        override fun onHideCustomView() {
            val cb = customCallback
            customView?.let { fullscreen.removeView(it) }
            customView = null
            customCallback = null
            fullscreen.visibility = View.GONE
            content.visibility = View.VISIBLE
            WindowCompat.getInsetsController(window, window.decorView).show(WindowInsetsCompat.Type.systemBars())
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            cb?.onCustomViewHidden()
        }

        override fun onPermissionRequest(request: PermissionRequest) = request.deny()

        override fun onGeolocationPermissionsShowPrompt(origin: String, callback: GeolocationPermissions.Callback) =
            callback.invoke(origin, false, false)

        // вместо серой «кнопки play» у <video> до загрузки — прозрачная картинка
        override fun getDefaultVideoPoster(): Bitmap =
            Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.TRANSPARENT) }
    }

    private fun exitFullscreen() {
        (web.webChromeClient as? Chrome)?.onHideCustomView()
    }

    // ---------- жизненный цикл ----------

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
        web.onPause()
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        val b = Bundle()
        web.saveState(b)
        outState.putBundle(STATE_WEB, b)
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        if (customView != null) exitFullscreen()
        (web.parent as? ViewGroup)?.removeView(web)
        web.destroy()
        super.onDestroy()
    }
}
