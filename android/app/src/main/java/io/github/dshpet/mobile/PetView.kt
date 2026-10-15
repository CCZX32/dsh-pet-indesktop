package io.github.dshpet.mobile

import android.content.Context
import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.view.MotionEvent
import android.view.VelocityTracker
import android.view.View
import android.view.ViewConfiguration
import kotlin.math.hypot

@SuppressLint("ViewConstructor") // Constructed by the service, never inflated from XML.
class PetView(context: Context, private val engine: PetEngine,
              private val changed: () -> Unit, private val released: () -> Unit,
              private val clicked: () -> Unit, private val menu: () -> Unit) : View(context) {
    var renderScale = 1.0
    var lastGesture = "none"
        private set
    private var bitmap: Bitmap? = null
    private var crop = SourceBox(0.0, 0.0, 640.0, 360.0)
    private var mirrored = false
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val sourceRect = Rect()
    private val destinationRect = RectF()
    private var tracker: VelocityTracker? = null
    private var downX = 0f
    private var downY = 0f
    private var originX = 0.0
    private var originY = 0.0
    private var moved = false
    private var menuOpened = false
    private var activePointer = -1
    private var releaseVelocityX = 0f
    private var releaseVelocityY = 0f
    private var lastMoveTime = 0L
    private val longPress = Runnable {
        if (!moved && activePointer >= 0) {
            menuOpened = true
            engine.cancelDrag()
            menu()
        }
    }

    init {
        contentDescription = context.getString(R.string.app_name)
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
        isClickable = true
        isLongClickable = true
    }

    fun present(frame: Bitmap?, region: SourceBox, facingRight: Boolean) {
        val different = (frame != null && frame !== bitmap) || crop != region || mirrored != facingRight
        if (frame != null) bitmap = frame
        crop = region
        mirrored = facingRight
        if (different) invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val image = bitmap ?: return
        canvas.save()
        if (mirrored) canvas.scale(-1f, 1f, width / 2f, height / 2f)
        sourceRect.set(crop.left.toInt(), crop.top.toInt(), crop.right.toInt(), crop.bottom.toInt())
        destinationRect.set(0f, 0f, width.toFloat(), height.toFloat())
        canvas.drawBitmap(image, sourceRect, destinationRect, paint)
        canvas.restore()
        PetRuntime.draws.incrementAndGet()
    }

    override fun performClick(): Boolean {
        super.performClick()
        engine.click()
        clicked()
        changed()
        return true
    }

    override fun performLongClick(): Boolean {
        menu()
        return true
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                activePointer = event.getPointerId(0)
                tracker?.recycle()
                tracker = VelocityTracker.obtain()
                trackScreenMovement(event)
                downX = event.rawX; downY = event.rawY
                originX = engine.x; originY = engine.y
                moved = false; menuOpened = false
                releaseVelocityX = 0f; releaseVelocityY = 0f; lastMoveTime = event.eventTime
                engine.beginDrag()
                lastGesture = "down"
                postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                changed()
            }
            MotionEvent.ACTION_MOVE -> {
                if (activePointer < 0 || menuOpened) return true
                trackScreenMovement(event)
                tracker?.computeCurrentVelocity(1000)
                releaseVelocityX = tracker?.getXVelocity(activePointer) ?: 0f
                releaseVelocityY = tracker?.getYVelocity(activePointer) ?: 0f
                lastMoveTime = event.eventTime
                val dx = event.rawX - downX
                val dy = event.rawY - downY
                if (hypot(dx, dy) > ViewConfiguration.get(context).scaledTouchSlop) {
                    moved = true
                    removeCallbacks(longPress)
                }
                if (moved) {
                    engine.dragTo(originX + dx / renderScale, originY + dy / renderScale)
                    changed()
                }
            }
            MotionEvent.ACTION_UP -> {
                if (activePointer < 0) return true
                removeCallbacks(longPress)
                if (!menuOpened) {
                    if (moved) {
                        // ACTION_UP can clear VelocityTracker; use the last MOVE,
                        // but discard stale velocity after the finger has rested.
                        val age = event.eventTime - lastMoveTime
                        val fresh = age in 0L..150L
                        val vx = if (fresh) releaseVelocityX / renderScale else 0.0
                        val vy = if (fresh) releaseVelocityY / renderScale else 0.0
                        lastGesture = "release vx=$vx vy=$vy age_ms=$age"
                        engine.release(vx, vy)
                        released()
                    } else performClick()
                }
                finishGesture()
                changed()
            }
            MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN -> {
                lastGesture = "cancel action=${event.actionMasked}"
                engine.cancelDrag()
                finishGesture()
                released()
                changed()
            }
        }
        return true
    }

    private fun trackScreenMovement(event: MotionEvent) {
        // The overlay moves with the finger, so local coordinates hide its speed.
        val screenEvent = MotionEvent.obtain(event)
        screenEvent.offsetLocation(event.rawX - event.x, event.rawY - event.y)
        tracker?.addMovement(screenEvent)
        screenEvent.recycle()
    }

    private fun finishGesture() {
        removeCallbacks(longPress)
        tracker?.recycle(); tracker = null
        activePointer = -1
    }

    override fun onDetachedFromWindow() {
        finishGesture()
        bitmap = null
        super.onDetachedFromWindow()
    }
}
