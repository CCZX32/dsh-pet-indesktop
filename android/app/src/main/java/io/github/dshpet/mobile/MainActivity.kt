package io.github.dshpet.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {
    private lateinit var preferences: PetPreferences
    private var overlayAllowed by mutableStateOf(false)
    private var options by mutableStateOf(PetOptions())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        preferences = PetPreferences(this)
        options = preferences.options()
        setContent { PetSettings() }
    }

    override fun onResume() {
        super.onResume()
        overlayAllowed = Settings.canDrawOverlays(this)
        if (::preferences.isInitialized) options = preferences.options()
    }

    @OptIn(ExperimentalLayoutApi::class)
    @Composable private fun PetSettings() {
        val runtime by PetRuntime.state.collectAsState()
        val sizeLabel = stringResource(R.string.pet_size)
        var resetConfirmation by remember { mutableStateOf(false) }
        val permissionRequest = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            PetOverlayService.command(this, PetOverlayService.START)
        }
        val scheme = if (isSystemInDarkTheme()) darkColorScheme(
            primary = Color(0xFF76D5BD), onPrimary = Color(0xFF00382F),
            background = Color(0xFF191C1C), surface = Color(0xFF191C1C),
            secondaryContainer = Color(0xFF374944), onSecondaryContainer = Color(0xFFDDE5E1),
            surfaceVariant = Color(0xFF3F4844), outlineVariant = Color(0xFF56615B),
            tertiary = Color(0xFFFFB4A2)) else lightColorScheme(
            primary = Color(0xFF006B5C), background = Color(0xFFF8FAF9), surface = Color(0xFFF8FAF9),
            secondaryContainer = Color(0xFFE1E9E5), onSecondaryContainer = Color(0xFF293A34),
            surfaceVariant = Color(0xFFE7ECE9), outlineVariant = Color(0xFFCFD8D2),
            tertiary = Color(0xFFAD4C38))
        MaterialTheme(colorScheme = scheme) {
            Surface(modifier = Modifier.fillMaxSize()) {
                Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp, vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Image(painterResource(R.drawable.pet_icon), null, Modifier.size(96.dp))
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineSmall)
                            Text(stringResource(if (!runtime.running) R.string.not_running else
                                if (runtime.paused) R.string.paused else R.string.running),
                                color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    runtime.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    if (!overlayAllowed) {
                        Text(stringResource(R.string.permission_required))
                        Button(onClick = {
                            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
                        }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.grant_overlay)) }
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        maxItemsInEachRow = if (LocalDensity.current.fontScale > 1.3f) 1 else 2) {
                        Button(onClick = {
                            if (runtime.running) PetOverlayService.command(this@MainActivity,
                                if (runtime.paused) PetOverlayService.RESUME else PetOverlayService.PAUSE)
                            else if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(
                                    this@MainActivity, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                                permissionRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
                            else PetOverlayService.command(this@MainActivity, PetOverlayService.START)
                        }, enabled = overlayAllowed, modifier = Modifier.weight(1f)) {
                            Icon(if (runtime.running && !runtime.paused) Icons.Default.Pause else Icons.Default.PlayArrow, null)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(if (!runtime.running) R.string.start else
                                if (runtime.paused) R.string.resume else R.string.pause))
                        }
                        OutlinedButton(onClick = { PetOverlayService.command(this@MainActivity, PetOverlayService.STOP) },
                            enabled = runtime.running, modifier = Modifier.weight(1f)) {
                            Icon(Icons.Default.Stop, null)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.stop))
                        }
                    }
                    HorizontalDivider()
                    Text(stringResource(R.string.appearance), style = MaterialTheme.typography.titleMedium)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(stringResource(R.string.pet_size), modifier = Modifier.weight(1f))
                        Text("${(options.size * 100).toInt()}%")
                    }
                    Slider(value = options.size, onValueChange = { options = options.copy(size = it) },
                        onValueChangeFinished = { preferences.save(options) }, valueRange = .6f..1.6f,
                        modifier = Modifier.fillMaxWidth().semantics { contentDescription = sizeLabel })
                    HorizontalDivider()
                    Text(stringResource(R.string.interaction), style = MaterialTheme.typography.titleMedium)
                    SettingSwitch(R.string.wander, options.wander) {
                        options = options.copy(wander = it); preferences.save(options)
                    }
                    SettingSwitch(R.string.speech, options.speech) {
                        options = options.copy(speech = it); preferences.save(options)
                    }
                    HorizontalDivider()
                    TextButton(onClick = { resetConfirmation = true }) {
                        Icon(Icons.Default.Refresh, null)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.reset))
                    }
                    Text(stringResource(R.string.version), color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall)
                }
                if (resetConfirmation) AlertDialog(onDismissRequest = { resetConfirmation = false },
                    title = { Text(stringResource(R.string.reset)) },
                    text = { Text(stringResource(R.string.reset_message)) },
                    confirmButton = { TextButton(onClick = {
                        preferences.reset(); options = preferences.options()
                        if (runtime.running) PetOverlayService.command(this@MainActivity, PetOverlayService.RESET)
                        resetConfirmation = false
                    }) { Text(stringResource(R.string.reset)) } },
                    dismissButton = { TextButton(onClick = { resetConfirmation = false }) {
                        Text(stringResource(R.string.cancel))
                    } })
            }
        }
    }

    @Composable private fun SettingSwitch(label: Int, checked: Boolean, changed: (Boolean) -> Unit) {
        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).toggleable(checked, role = Role.Switch,
            onValueChange = changed), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(label), Modifier.weight(1f).padding(end = 16.dp))
            Switch(checked, onCheckedChange = null)
        }
    }
}
