package kr.firstlisten.app

import android.app.Application
import android.content.ComponentName
import android.service.notification.NotificationListenerService
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kr.firstlisten.app.capture.MusicNotificationListenerService
import kr.firstlisten.app.data.ListenEventEntity
import kr.firstlisten.app.data.SessionStore

@OptIn(ExperimentalCoroutinesApi::class)
class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val graph = application.appGraph
    val session = graph.sessions.state
    val capture = graph.captureStatus
    val sync = graph.syncStatus
    val busy = MutableStateFlow(false)
    val message = MutableStateFlow<String?>(null)
    val permission = MutableStateFlow(false)
    val recent = session.flatMapLatest { s -> s.ownerKey?.let { graph.database.events().recent(it) }
        ?: flowOf(emptyList<ListenEventEntity>()) }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
    val pending = session.flatMapLatest { s -> s.ownerKey?.let { graph.database.events().pendingCount(it) }
        ?: flowOf(0) }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)
    val rejected = session.flatMapLatest { s -> s.ownerKey?.let { graph.database.events().rejectedCount(it) }
        ?: flowOf(0) }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    fun refreshPermission() {
        val context = getApplication<Application>()
        permission.value = NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)
        if (permission.value && session.value.captureEnabled && !capture.value.connected) {
            NotificationListenerService.requestRebind(ComponentName(context, MusicNotificationListenerService::class.java))
        }
    }

    fun authenticate(email: String, password: String, register: Boolean) = action {
        val baseUrl = graph.api.normalizeBaseUrl(SessionStore.DEFAULT_BASE_URL)
        require(email.isNotBlank() && password.isNotEmpty()) { "이메일과 비밀번호를 입력해 주세요." }
        require(!register || password.length in 10..128) { "비밀번호는 10자 이상 128자 이하로 입력해 주세요." }  // server: MemberCreate
        if (register) graph.api.register(baseUrl, email.trim(), password)
        val token = graph.api.login(baseUrl, email.trim(), password)
        val member = graph.api.me(baseUrl, token.access_token)
        withContext(Dispatchers.IO) { graph.sessions.signIn(baseUrl, member.id, member.email, token.access_token, token.expires_at) }
        message.value = "로그인했습니다. 알림 접근을 허용하고 자동 기록을 켜 주세요."
    }

    fun setCapture(enabled: Boolean) = action {
        refreshPermission()
        require(!enabled || permission.value) { "먼저 알림 접근 설정에서 FirstListen을 허용해 주세요." }
        withContext(Dispatchers.IO) { graph.sessions.setCapture(enabled) }
        message.value = if (enabled) "YouTube Music을 재생하면 자동으로 기록합니다." else "자동 기록을 껐습니다."
    }

    fun syncNow(retryRejected: Boolean = false) = action {
        val ownerKey = session.value.ownerKey ?: error("로그인이 필요합니다.")
        require(graph.sessions.currentAccount() != null) { "다시 로그인하면 저장된 기록을 전송할 수 있습니다." }
        if (retryRejected) graph.database.events().retryRejected(ownerKey)
        graph.scheduler.request(ownerKey)
        message.value = "동기화를 예약했습니다. 네트워크에 연결되면 전송합니다."
    }

    fun logout() = action {
        val account = graph.sessions.currentAccount()
        val ownerKey = session.value.ownerKey
        withContext(Dispatchers.IO) { graph.sessions.signOut() }
        ownerKey?.let(graph.scheduler::cancel)
        message.value = "로그아웃했습니다. 기기에 저장된 기록은 해당 계정으로 다시 로그인하면 볼 수 있습니다."
        if (account != null) {
            try { graph.api.logout(account) }
            catch (error: Exception) {
                if (error is CancellationException) throw error
                message.value = "기기에서 로그아웃했습니다. 연결 실패로 서버 토큰은 만료 시까지 남을 수 있습니다."
            }
        }
    }

    private fun action(block: suspend () -> Unit) {
        if (busy.value) return
        viewModelScope.launch {
            busy.value = true
            message.value = null
            try { block() }
            catch (error: Exception) {
                if (error is CancellationException) throw error
                message.value = error.message ?: "작업을 완료하지 못했습니다."
            } finally { busy.value = false }
        }
    }
}
