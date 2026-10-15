package io.github.dshpet.mobile

import android.content.res.AssetManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/** One decoder, latest-request coalescing, and at most three cached frames. */
class FrameLoader(private val assets: AssetManager, private val ready: () -> Unit,
                  private val failed: (Exception) -> Unit) : AutoCloseable {
    private data class Request(val clip: ClipSpec, val index: Int) {
        val key get() = "${clip.id}:$index"
        val path get() = "pet/${clip.path}/f_${(index + 1).toString().padStart(4, '0')}.webp"
    }
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "pet-frame-decoder")
    }
    private val handler = Handler(Looper.getMainLooper())
    private val lock = Any()
    private val frames = LinkedHashMap<String, Bitmap>(4, .75f, true)
    private var wanted: Request? = null
    private var busy = false
    private var closed = false
    private var failures = 0
    val decoded = AtomicLong()

    fun request(clip: ClipSpec, index: Int): Bitmap? = synchronized(lock) {
        if (closed) return null
        val request = Request(clip, index.coerceIn(0, clip.frames - 1))
        wanted = request
        val current = frames[request.key]
        if (!busy && (current == null || frames[Request(clip, (index + 1) % clip.frames).key] == null)) {
            busy = true
            executor.execute { decodeLatest() }
        }
        current
    }

    private fun decodeLatest() {
        while (true) {
            val request = synchronized(lock) {
                if (closed || wanted == null) { busy = false; return }
                wanted!!
            }
            try {
                for (item in listOf(request, Request(request.clip, (request.index + 1) % request.clip.frames))) {
                    if (synchronized(lock) { closed }) return
                    if (synchronized(lock) { frames.containsKey(item.key) }) continue
                    val bitmap = assets.open(item.path).use { BitmapFactory.decodeStream(it) }
                        ?: error("Unreadable animation frame: ${item.path}")
                    decoded.incrementAndGet()
                    synchronized(lock) {
                        if (closed) return
                        frames[item.key] = bitmap
                        while (frames.size > 3) frames.remove(frames.keys.first())
                    }
                }
                failures = 0
                handler.post { if (!synchronized(lock) { closed }) ready() }
            } catch (e: Exception) {
                failures++
                if (failures >= 3) handler.post { if (!synchronized(lock) { closed }) failed(e) }
            }
            synchronized(lock) {
                if (closed || wanted?.key == request.key) { busy = false; return }
            }
        }
    }

    override fun close() {
        synchronized(lock) { closed = true; wanted = null; frames.clear() }
        handler.removeCallbacksAndMessages(null)
        executor.shutdownNow()
    }
}
