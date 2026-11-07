package kr.firstlisten.app.capture

import android.content.ComponentName
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSession
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.service.notification.NotificationListenerService
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kr.firstlisten.app.CaptureStatus
import kr.firstlisten.app.appGraph
import kr.firstlisten.core.ListenSnapshot
import kr.firstlisten.core.ListeningTracker
import kr.firstlisten.core.PlaybackSample
import java.time.Instant

class MusicNotificationListenerService : NotificationListenerService() {
    private sealed interface Command {
        data object Connect : Command
        data object Disconnect : Command
        data object Refresh : Command
        data object Destroy : Command
        data class SessionEnded(val token: MediaSession.Token) : Command
        data class Configure(val owner: String?) : Command
        data class Sample(val owner: String, val token: MediaSession.Token, val sample: PlaybackSample,
            val elapsedMs: Long, val wallClock: Instant) : Command
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val commands = Channel<Command>(Channel.UNLIMITED)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val graph get() = appGraph
    private val manager by lazy { getSystemService(MediaSessionManager::class.java) }
    private var connected = false
    private var owner: String? = null
    private var registered = false
    private var controller: MediaController? = null
    private var callback: MediaController.Callback? = null
    private var tracker: ListeningTracker? = null
    private var ticker: Job? = null
    private var configuration: Job? = null
    private val requestedMs = mutableMapOf<String, Long>()
    private val endedSessions = mutableSetOf<MediaSession.Token>()
    private val sessionsChanged = MediaSessionManager.OnActiveSessionsChangedListener { commands.trySend(Command.Refresh) }

    override fun onCreate() {
        super.onCreate()
        scope.launch {
            graph.ready.await()
            for (command in commands) {
                try {
                    when (command) {
                        Command.Connect -> {
                            connected = true
                            graph.captureStatus.value = CaptureStatus(connected = true, message = "자동 기록을 켜면 수집을 시작합니다.")
                            refresh()
                        }
                        Command.Disconnect -> {
                            connected = false
                            detach()
                            removeListener()
                            graph.captureStatus.value = CaptureStatus(message = "수집 연결이 끊겼습니다. 알림 접근 권한을 확인해 주세요.")
                        }
                        Command.Refresh -> refresh()
                        is Command.SessionEnded -> {
                            endedSessions += command.token
                            if (controller?.sessionToken == command.token) detach()
                            refresh()
                        }
                        is Command.Configure -> {
                            if (owner != command.owner) {
                                detach()
                                owner = command.owner
                            }
                            refresh()
                        }
                        is Command.Sample -> if (owner == command.owner && controller?.sessionToken == command.token) {
                            val changes = tracker?.observe(command.sample, command.elapsedMs, command.wallClock).orEmpty()
                            persist(changes)
                            graph.captureStatus.value = CaptureStatus(connected = true,
                                message = if (command.sample.track == null) "곡명·가수 정보를 기다리는 중" else "재생 상태: ${command.sample.status}",
                                track = command.sample.track?.let { "${it.title} · ${it.artist}" },
                                listenedMs = changes.lastOrNull()?.listenedMs ?: graph.captureStatus.value.listenedMs)
                        }
                        Command.Destroy -> {
                            detach()
                            removeListener()
                            graph.captureStatus.value = CaptureStatus(message = "수집 서비스가 종료되었습니다.")
                            scope.cancel()
                            break
                        }
                    }
                } catch (error: Exception) {
                    if (error is CancellationException) throw error
                    // Do not keep counting through a storage/permission failure.
                    ticker?.cancel()
                    tracker = null
                    controller?.let { active -> callback?.let { active.unregisterCallback(it) } }
                    controller = null
                    callback = null
                    graph.captureStatus.value = CaptureStatus(connected = connected, message = "수집 중단: ${error.message ?: "권한과 저장 공간을 확인해 주세요."}")
                }
            }
        }
        configuration = scope.launch {
            graph.sessions.state.map { if (it.captureEnabled) it.ownerKey else null }.distinctUntilChanged()
                .collect { commands.send(Command.Configure(it)) }
        }
    }

    override fun onListenerConnected() { commands.trySend(Command.Connect) }
    override fun onListenerDisconnected() {
        commands.trySend(Command.Disconnect)
        requestRebind(ComponentName(this, MusicNotificationListenerService::class.java))
    }

    override fun onDestroy() {
        configuration?.cancel()
        ticker?.cancel()
        commands.trySend(Command.Destroy)
        super.onDestroy()
    }

    private suspend fun refresh() {
        if (!connected || owner == null) {
            detach()
            removeListener()
            if (connected) graph.captureStatus.value = CaptureStatus(connected = true, message = "자동 기록 꺼짐")
            return
        }
        if (!registered) {
            manager.addOnActiveSessionsChangedListener(sessionsChanged,
                ComponentName(this, MusicNotificationListenerService::class.java), mainHandler)
            registered = true
        }
        val sessions = manager.getActiveSessions(ComponentName(this, MusicNotificationListenerService::class.java))
            .filter { it.packageName == MediaSessionObserver.YOUTUBE_MUSIC_PACKAGE && it.sessionToken !in endedSessions }
        val selected = sessions.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING }
            ?: sessions.firstOrNull { it.sessionToken == controller?.sessionToken } ?: sessions.firstOrNull()
        if (selected == null) {
            detach()
            graph.captureStatus.value = CaptureStatus(connected = true, message = "YouTube Music 재생을 기다리는 중")
            return
        }
        if (selected.sessionToken == controller?.sessionToken) return
        detach()
        controller = selected
        tracker = ListeningTracker(owner!!)
        val attachedOwner = owner!!
        callback = object : MediaController.Callback() {
            override fun onMetadataChanged(metadata: MediaMetadata?) { submit(selected, attachedOwner) }
            override fun onPlaybackStateChanged(state: PlaybackState?) { submit(selected, attachedOwner) }
            override fun onSessionDestroyed() { commands.trySend(Command.SessionEnded(selected.sessionToken)) }
        }
        selected.registerCallback(callback!!, mainHandler)
        submit(selected, attachedOwner)
        ticker = scope.launch {
            while (true) {
                delay(5_000)
                submit(selected, attachedOwner)
            }
        }
    }

    private fun submit(active: MediaController, attachedOwner: String) {
        val configured = graph.sessions.state.value
        if (!configured.captureEnabled || configured.ownerKey != attachedOwner) return
        val now = SystemClock.elapsedRealtime()
        commands.trySend(Command.Sample(attachedOwner, active.sessionToken,
            MediaSessionObserver.sample(active, now), now, Instant.now()))
    }

    private suspend fun detach() {
        ticker?.cancel()
        ticker = null
        controller?.let { active -> callback?.let { active.unregisterCallback(it) } }
        controller = null
        callback = null
        persist(tracker?.disconnect().orEmpty())
        tracker = null
        requestedMs.clear()
    }

    private suspend fun persist(changes: List<ListenSnapshot>) {
        for (snapshot in changes) {
            graph.database.events().record(snapshot)
            if (snapshot.listenedMs >= ListeningTracker.MIN_LISTENED_MS &&
                (snapshot.closed || snapshot.listenedMs - requestedMs.getOrDefault(snapshot.eventId, 0) >= 30_000)) {
                graph.scheduler.request(snapshot.ownerKey)
                requestedMs[snapshot.eventId] = snapshot.listenedMs
            }
        }
    }

    private fun removeListener() {
        if (registered) {
            manager.removeOnActiveSessionsChangedListener(sessionsChanged)
            registered = false
        }
    }
}
