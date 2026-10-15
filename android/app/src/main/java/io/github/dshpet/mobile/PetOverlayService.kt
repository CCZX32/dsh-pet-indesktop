package io.github.dshpet.mobile

import android.app.AppOpsManager
import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.util.DisplayMetrics
import android.view.Choreographer
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import java.io.FileDescriptor
import java.io.PrintWriter
import kotlin.math.max
import kotlin.math.roundToInt

class PetOverlayService : Service(), Choreographer.FrameCallback {
    companion object {
        const val START = "pet.START"
        const val PAUSE = "pet.PAUSE"
        const val RESUME = "pet.RESUME"
        const val STOP = "pet.STOP"
        const val RESET = "pet.RESET"
        private const val CHANNEL = "pet-running"
        fun command(context: Context, action: String) {
            try {
                val intent = Intent(context, PetOverlayService::class.java).setAction(action)
                if (action == STOP) context.stopService(intent)
                else if (action == START) ContextCompat.startForegroundService(context, intent)
                else context.startService(intent)
            } catch (e: RuntimeException) {
                android.util.Log.e("PetOverlay", "Service command failed", e)
                PetRuntime.state.value = PetRuntime.state.value.copy(error = context.getString(R.string.start_failed))
            }
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private lateinit var windows: WindowManager
    private lateinit var preferences: PetPreferences
    private lateinit var catalog: AssetCatalog
    private lateinit var engine: PetEngine
    private var options = PetOptions()
    private var pet: PetView? = null
    private var params: WindowManager.LayoutParams? = null
    private var bubble: View? = null
    private var actions: View? = null
    private var loader: FrameLoader? = null
    private var scale = 1.0
    private var safe = Rect()
    private var started = false
    private var registered = false
    private var userPaused = false
    private var frameScheduled = false
    private var lastFrame = 0L
    private var nextSpeech = 0L
    private var decodedBeforeClose = 0L
    private val dismissBubble = Runnable { removeAuxiliary(bubble); bubble = null }
    private val preferenceListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == null || key in setOf("size", "wander", "speech")) handler.post { reloadOptions() }
    }
    private val permissionListener = AppOpsManager.OnOpChangedListener { op, pkg ->
        if (op == AppOpsManager.OPSTR_SYSTEM_ALERT_WINDOW && pkg == packageName) handler.post {
            if (started && !Settings.canDrawOverlays(this)) fail(R.string.permission_required)
        }
    }
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { updateVisibility() }
    }

    override fun onCreate() {
        super.onCreate()
        windows = getSystemService(WindowManager::class.java)
        preferences = PetPreferences(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            START -> startPet()
            STOP -> stopSelf()
            PAUSE -> if (started) { userPaused = true; updateVisibility(); updateNotification() }
            RESUME -> if (started) { userPaused = false; updateVisibility(); updateNotification() }
            RESET -> if (started) {
                engine.restorePosition(.7, 1.0)
                reloadOptions()
            }
            else -> if (!started) stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun startPet() {
        if (started) return
        if (!Settings.canDrawOverlays(this)) { fail(R.string.permission_required); return }
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL,
                getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW))
            val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
            ServiceCompat.startForeground(this, 1, notification(), type)
            catalog = AssetCatalog.load(assets)
            engine = PetEngine(catalog.clips)
            started = true
            val saved = preferences.position()
            reloadOptions()
            engine.restorePosition(saved.first, saved.second)
            preferences.subscribe(preferenceListener)
            ContextCompat.registerReceiver(this, screenReceiver, IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_OFF)
                addAction(Intent.ACTION_SCREEN_ON)
                addAction(Intent.ACTION_USER_PRESENT)
            }, ContextCompat.RECEIVER_NOT_EXPORTED)
            registered = true
            getSystemService(AppOpsManager::class.java).startWatchingMode(
                AppOpsManager.OPSTR_SYSTEM_ALERT_WINDOW, packageName, permissionListener)
            PetRuntime.state.value = RuntimeState(running = true)
            nextSpeech = SystemClock.elapsedRealtime() + 30_000
            updateVisibility()
        } catch (e: Exception) {
            android.util.Log.e("PetOverlay", "Pet startup failed", e)
            fail(if (e is SecurityException) R.string.permission_required else R.string.assets_failed)
        }
    }

    private fun interactive() = getSystemService(PowerManager::class.java).isInteractive &&
        !getSystemService(KeyguardManager::class.java).isKeyguardLocked

    private fun updateVisibility() {
        if (!started) return
        if (!Settings.canDrawOverlays(this)) { fail(R.string.permission_required); return }
        val visible = interactive()
        engine.paused = userPaused || !visible
        PetRuntime.state.value = RuntimeState(running = true, paused = userPaused)
        Choreographer.getInstance().removeFrameCallback(this)
        frameScheduled = false; lastFrame = 0L
        if (!visible) {
            engine.cancelDrag()
            removeWindows()
            return
        }
        if (pet == null) attachPet()
        if (pet == null) return
        render()
        if (!userPaused) scheduleFrame()
    }

    private fun layout(width: Int, height: Int) = WindowManager.LayoutParams(
        width, height, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT).apply {
        gravity = Gravity.TOP or Gravity.START
        if (Build.VERSION.SDK_INT >= 30) setFitInsetsTypes(0)
    }

    private fun attachPet() {
        try {
            pet = PetView(this, engine, ::render, ::rememberPosition, ::showSpeech, ::showActions).also {
                it.renderScale = scale
            }
            params = layout(1, 1)
            windows.addView(pet, params)
            PetRuntime.windowCount.set(1)
            loader = FrameLoader(assets, { if (pet != null) render() }, {
                android.util.Log.e("PetOverlay", "Frame decode failed", it)
                fail(R.string.assets_failed)
            })
        } catch (e: RuntimeException) {
            android.util.Log.e("PetOverlay", "Cannot attach overlay", e)
            pet = null; params = null
            fail(R.string.permission_required)
        }
    }

    private fun reloadOptions() {
        if (!started) return
        options = preferences.options()
        engine.wander = options.wander
        scale = 112.0 * resources.displayMetrics.density * options.size / catalog.body.height
        safe = safeBounds()
        engine.resize(max(0.0, safe.width() / scale - catalog.body.width),
            max(0.0, safe.height() / scale - catalog.body.height))
        pet?.renderScale = scale
        if (!options.speech) { handler.removeCallbacks(dismissBubble); dismissBubble.run() }
        removeAuxiliary(actions); actions = null
        render()
    }

    @Suppress("DEPRECATION")
    private fun safeBounds(): Rect {
        if (Build.VERSION.SDK_INT >= 30) {
            val metrics = windows.currentWindowMetrics
            val insets = metrics.windowInsets.getInsetsIgnoringVisibility(
                WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            return Rect(metrics.bounds).apply {
                left += insets.left; top += insets.top; right -= insets.right; bottom -= insets.bottom
            }
        }
        val metrics = DisplayMetrics()
        windows.defaultDisplay.getRealMetrics(metrics)
        fun inset(name: String): Int {
            val id = resources.getIdentifier(name, "dimen", "android")
            return if (id == 0) 0 else resources.getDimensionPixelSize(id)
        }
        return Rect(0, inset("status_bar_height"), metrics.widthPixels,
            metrics.heightPixels - inset("navigation_bar_height"))
    }

    private fun scheduleFrame() {
        if (!frameScheduled && started && pet != null && !engine.paused) {
            frameScheduled = true
            Choreographer.getInstance().postFrameCallback(this)
        }
    }

    override fun doFrame(frameTimeNanos: Long) {
        frameScheduled = false
        if (!started || engine.paused || pet == null) return
        if (lastFrame == 0L) lastFrame = frameTimeNanos
        val elapsed = (frameTimeNanos - lastFrame) / 1e9
        if (elapsed >= 1.0 / 30) {
            lastFrame = frameTimeNanos
            engine.advance(elapsed)
            render()
            if (SystemClock.elapsedRealtime() >= nextSpeech) {
                showSpeech()
                nextSpeech = SystemClock.elapsedRealtime() + kotlin.random.Random.nextLong(20_000, 60_001)
            }
        }
        scheduleFrame()
    }

    private fun render() {
        val view = pet ?: return
        val p = params ?: return
        val clip = engine.clip
        val crop = clip.crop
        val x = (safe.left + (engine.x + crop.left - catalog.body.left) * scale).roundToInt()
        val y = (safe.top + (engine.y + crop.top - catalog.body.top) * scale).roundToInt()
        val width = max(1, (crop.width * scale).roundToInt())
        val height = max(1, (crop.height * scale).roundToInt())
        if (p.x != x || p.y != y || p.width != width || p.height != height) {
            p.x = x; p.y = y; p.width = width; p.height = height
            try { windows.updateViewLayout(view, p) }
            catch (e: RuntimeException) { fail(R.string.permission_required); return }
        }
        view.present(loader?.request(clip, engine.frameIndex), crop, engine.facingRight)
        positionBubble()
    }

    private fun rememberPosition() {
        preferences.savePosition(engine.normalizedX, engine.normalizedY)
        removeAuxiliary(actions); actions = null
    }

    private fun showSpeech() {
        if (!options.speech || catalog.phrases.isEmpty() || pet == null || userPaused) return
        handler.removeCallbacks(dismissBubble)
        dismissBubble.run()
        val text = TextView(this).apply {
            this.text = catalog.phrases.random()
            setTextColor(Color.rgb(29, 42, 47)); textSize = 14f
            maxWidth = (220 * resources.displayMetrics.density).roundToInt()
            val pad = (12 * resources.displayMetrics.density).roundToInt()
            setPadding(pad, pad / 2, pad, pad / 2)
            background = GradientDrawable().apply {
                setColor(Color.WHITE); cornerRadius = 8 * resources.displayMetrics.density
                setStroke(1, Color.rgb(213, 224, 226))
            }
        }
        val p = layout(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT)
        // Android 12+ only permits pass-through overlays below its opacity limit.
        p.flags = p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        p.alpha = .8f
        try {
            windows.addView(text, p); bubble = text
            text.post { positionBubble() }
            handler.postDelayed(dismissBubble, 3200)
        } catch (e: RuntimeException) { fail(R.string.permission_required) }
    }

    private fun positionBubble() {
        val view = bubble ?: return
        val p = view.layoutParams as WindowManager.LayoutParams
        p.x = (safe.left + engine.x * scale).roundToInt().coerceIn(safe.left, max(safe.left, safe.right - view.width))
        val above = (safe.top + engine.y * scale - view.height - 8 * resources.displayMetrics.density).roundToInt()
        p.y = if (above >= safe.top) above else
            (safe.top + (engine.y + catalog.body.height) * scale).roundToInt().coerceAtMost(safe.bottom - view.height)
        try { windows.updateViewLayout(view, p) } catch (_: RuntimeException) { removeAuxiliary(view); bubble = null }
    }

    private fun showActions() {
        removeAuxiliary(actions)
        val panel = object : LinearLayout(this) {
            override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
                if (event.keyCode == android.view.KeyEvent.KEYCODE_BACK) {
                    if (event.action == android.view.KeyEvent.ACTION_UP) {
                        removeAuxiliary(actions); actions = null
                    }
                    return true
                }
                return super.dispatchKeyEvent(event)
            }
        }.apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            elevation = 6 * resources.displayMetrics.density
        }
        fun action(label: Int, run: () -> Unit) {
            panel.addView(Button(this).apply {
                setText(label)
                setOnClickListener { removeAuxiliary(actions); actions = null; run() }
            })
        }
        action(R.string.settings) {
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        }
        action(if (userPaused) R.string.resume else R.string.pause) {
            command(this, if (userPaused) RESUME else PAUSE)
        }
        action(R.string.stop) { stopSelf() }
        val p = layout((160 * resources.displayMetrics.density).roundToInt(), WindowManager.LayoutParams.WRAP_CONTENT)
        // A user-opened menu needs focus for Back and accessibility navigation.
        p.flags = p.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
        p.flags = p.flags or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH
        panel.setOnTouchListener { _, event ->
            if (event.action == android.view.MotionEvent.ACTION_OUTSIDE) {
                removeAuxiliary(actions); actions = null
            }
            false
        }
        p.x = (safe.left + engine.x * scale).roundToInt().coerceIn(safe.left, max(safe.left, safe.right - p.width))
        p.y = (safe.top + engine.y * scale).roundToInt().coerceIn(safe.top,
            max(safe.top, safe.bottom - (170 * resources.displayMetrics.density).roundToInt()))
        try { windows.addView(panel, p); actions = panel }
        catch (e: RuntimeException) { fail(R.string.permission_required) }
    }

    private fun notification(): Notification {
        fun pending(action: String) = PendingIntent.getService(this, action.hashCode(),
            Intent(this, PetOverlayService::class.java).setAction(action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(if (userPaused) R.string.paused else R.string.running))
            .setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
            .setContentIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
            .addAction(if (userPaused) android.R.drawable.ic_media_play else android.R.drawable.ic_media_pause,
                getString(if (userPaused) R.string.resume else R.string.pause), pending(if (userPaused) RESUME else PAUSE))
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, getString(R.string.stop), pending(STOP))
            .build()
    }

    private fun updateNotification() = getSystemService(NotificationManager::class.java).notify(1, notification())
    private fun fail(message: Int) {
        PetRuntime.state.value = RuntimeState(error = getString(message))
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        stopSelf()
    }

    private fun removeAuxiliary(view: View?) {
        if (view != null) try { windows.removeViewImmediate(view) } catch (_: RuntimeException) { }
    }

    private fun removeWindows() {
        handler.removeCallbacks(dismissBubble)
        removeAuxiliary(bubble); bubble = null
        removeAuxiliary(actions); actions = null
        removeAuxiliary(pet); pet = null; params = null
        PetRuntime.windowCount.set(0)
        loader?.let { decodedBeforeClose += it.decoded.get(); it.close() }
        loader = null
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (started) { reloadOptions(); rememberPosition() }
    }

    override fun onDestroy() {
        if (started) rememberPosition()
        started = false
        Choreographer.getInstance().removeFrameCallback(this)
        handler.removeCallbacksAndMessages(null)
        preferences.unsubscribe(preferenceListener)
        if (registered) {
            unregisterReceiver(screenReceiver)
            getSystemService(AppOpsManager::class.java).stopWatchingMode(permissionListener)
        }
        removeWindows()
        PetRuntime.state.value = RuntimeState(error = PetRuntime.state.value.error)
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun dump(fd: FileDescriptor, writer: PrintWriter, args: Array<out String>) {
        writer.println("running=$started paused=$userPaused interactive=${interactive()}")
        writer.println("windows=${PetRuntime.windowCount.get()} draws=${PetRuntime.draws.get()} decoded=${decodedBeforeClose + (loader?.decoded?.get() ?: 0)}")
        if (started) writer.println("mode=${engine.mode} x=${engine.x} y=${engine.y} clip=${engine.clip.id}")
        writer.println("gesture=${pet?.lastGesture}")
    }
    override fun onBind(intent: Intent?): IBinder? = null
}
