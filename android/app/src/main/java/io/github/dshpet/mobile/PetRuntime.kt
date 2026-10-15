package io.github.dshpet.mobile

import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.MutableStateFlow

data class RuntimeState(val running: Boolean = false, val paused: Boolean = false, val error: String? = null)

object PetRuntime {
    val state = MutableStateFlow(RuntimeState())
    val draws = AtomicLong()
    val windowCount = AtomicInteger()
}
