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

/**
 * "이 노래", "그 곡은", "저 노래"처럼 곡을 가리키는 말로 시작하는 질문 (서버 chat_service.DEICTIC과 같은 기준).
 * 대화 중인 곡(selectedTrack)은 이런 질문에만 track_id로 보낸다. 서버는 track_id가 있으면 질문 속 곡명을
 * 무시하므로, "봄날 언제부터?" 같은 다른 곡 질문에 직전 곡을 붙이면 엉뚱한 곡의 답이 나온다.
 */
private val DEICTIC = Regex("""^\s*(이|그|저)\s*(노래|곡)""")

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

    fun ask(question: String, trackOverride: TrackOut? = null) {
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
        // 직접 고른 후보가 있으면 그 곡, 아니면 '이/그 노래'로 시작하는 질문에만 대화 중인 곡을 붙인다.
        val target = trackOverride ?: before.selectedTrack?.takeIf { DEICTIC.containsMatchIn(text) }
        val messageId = UUID.randomUUID().toString()
        val version = requestVersion.incrementAndGet()
        mutable.update { it.copy(question = "", sending = true, error = null,
            messages = it.messages + ChatMessage(messageId, text, pending = true)) }
        requestJob = tasks.launch {
            try {
                val reply = api.chat(owner, text, target?.id)
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
        ask(message.question, track)  // 원래 질문은 곡명을 담고 있어 '이 노래' 규칙에 걸리지 않으므로 직접 넘긴다
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
