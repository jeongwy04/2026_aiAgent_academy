package kr.firstlisten.app

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kr.firstlisten.app.network.ChatReply
import kr.firstlisten.app.network.FirstListenApi
import kr.firstlisten.app.network.TrackOut
import kr.firstlisten.app.network.accounts
import kr.firstlisten.app.network.requestMessage
import kr.firstlisten.core.AccountProvider
import kr.firstlisten.core.HttpFailure
import kr.firstlisten.core.SyncAccount
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

data class ChatMessage(
    val id: String,
    val question: String,
    val reply: ChatReply? = null,
    val pending: Boolean = false,
    val error: String? = null,
)

data class ChatUiState(
    val ownerKey: String? = null,
    val question: String = "",
    val selectedTrack: TrackOut? = null,
    val messages: List<ChatMessage> = emptyList(),
    val sending: Boolean = false,
    val retryAfterSec: Long = 0,
    val error: String? = null,
)

class ChatViewModel internal constructor(
    application: Application,
    private val api: FirstListenApi,
    private val accounts: AccountProvider,
    accountChanges: Flow<SyncAccount?>,
    scope: CoroutineScope? = null,
    private val nowMillis: () -> Long = SystemClock::elapsedRealtime,
) : AndroidViewModel(application) {
    constructor(application: Application) : this(application, application.appGraph.api,
        application.appGraph.sessions, application.appGraph.sessions.accounts())

    private val tasks = scope ?: viewModelScope
    private val mutable = MutableStateFlow(ChatUiState())
    val state = mutable.asStateFlow()
    @Volatile private var account: SyncAccount? = null
    private var requestJob: Job? = null
    private var cooldownJob: Job? = null
    private val requestVersion = AtomicLong()

    init {
        tasks.launch {
            accountChanges.collect { next ->
                if (next != account) {
                    requestVersion.incrementAndGet()
                    requestJob?.cancel()
                    cooldownJob?.cancel()
                    account = next
                    mutable.value = ChatUiState(ownerKey = next?.ownerKey)
                }
            }
        }
    }

    fun setQuestion(question: String) { mutable.update { it.copy(question = question.take(500), error = null) } }

    fun selectTrack(track: TrackOut?) {
        if (accounts.currentAccount() != account || account == null) return
        if (mutable.value.selectedTrack == track) return
        requestVersion.incrementAndGet()
        requestJob?.cancel()
        mutable.update { it.copy(selectedTrack = track, sending = false, error = null,
            messages = it.messages.map { message -> if (message.pending) message.copy(pending = false, error = "질문할 곡이 바뀌어 요청을 취소했습니다.") else message }) }
    }

    fun send() { ask(mutable.value.question) }

    fun ask(question: String) {
        val before = mutable.value
        if (before.sending || before.retryAfterSec > 0) return
        val owner = accounts.currentAccount()
        if (owner == null || owner != account) {
            mutable.value = ChatUiState(error = "기록 탭에서 먼저 로그인해 주세요.")
            return
        }
        val text = question.trim().take(500)
        if (text.isEmpty()) {
            mutable.update { it.copy(error = "질문을 입력해 주세요.") }
            return
        }
        val context = before.selectedTrack
        val messageId = UUID.randomUUID().toString()
        val version = requestVersion.incrementAndGet()
        mutable.update { it.copy(question = "", sending = true, error = null,
            messages = it.messages + ChatMessage(messageId, text, pending = true)) }
        requestJob = tasks.launch {
            try {
                val reply = api.chat(owner, text, context?.id)
                if (isCurrent(owner, version)) {
                    mutable.update { it.copy(sending = false, selectedTrack = reply.track ?: it.selectedTrack,
                        messages = it.messages.map { message -> if (message.id == messageId) message.copy(reply = reply, pending = false) else message }) }
                }
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (!isCurrent(owner, version)) return@launch
                if (error is HttpFailure && error.code == 401) {
                    accounts.requireLogin(owner)
                    mutable.value = ChatUiState(error = requestMessage(error))
                } else {
                    val limited = error is HttpFailure && error.code == 429
                    val wait = if (limited) (error as HttpFailure).retryAfterSec?.coerceIn(0, 86_400) ?: 60 else 0
                    val message = if (limited) "질문 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요." else requestMessage(error)
                    mutable.update { it.copy(sending = false,
                        messages = it.messages.map { entry -> if (entry.id == messageId) entry.copy(pending = false, error = message) else entry }) }
                    if (limited) startCooldown(owner, wait)
                }
            }
        }
    }

    fun retry(messageId: String) {
        mutable.value.messages.firstOrNull { it.id == messageId }?.let { ask(it.question) }
    }

    fun chooseCandidate(messageId: String, track: TrackOut) {
        if (mutable.value.sending || mutable.value.retryAfterSec > 0) return
        val message = mutable.value.messages.firstOrNull { it.id == messageId } ?: return
        if (message.reply?.candidates?.none { it.id == track.id } != false) return
        selectTrack(track)
        ask(message.question)
    }

    private fun startCooldown(owner: SyncAccount, seconds: Long) {
        cooldownJob?.cancel()
        val deadline = nowMillis() + seconds * 1_000
        mutable.update { it.copy(retryAfterSec = seconds) }
        cooldownJob = tasks.launch {
            while (owner == account && owner == accounts.currentAccount()) {
                val remaining = ((deadline - nowMillis()).coerceAtLeast(0) + 999) / 1_000
                mutable.update { it.copy(retryAfterSec = remaining) }
                if (remaining == 0L) break
                delay(1_000)
            }
        }
    }

    private fun isCurrent(owner: SyncAccount, version: Long) =
        owner == account && owner == accounts.currentAccount() && version == requestVersion.get()
}
