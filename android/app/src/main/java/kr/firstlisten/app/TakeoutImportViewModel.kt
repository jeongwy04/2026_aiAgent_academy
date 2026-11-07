package kr.firstlisten.app

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kr.firstlisten.app.data.stageTakeoutJson
import kr.firstlisten.app.network.FirstListenApi
import kr.firstlisten.app.network.ImportSummary
import kr.firstlisten.app.network.accounts
import kr.firstlisten.core.AccountProvider
import kr.firstlisten.core.HttpFailure
import kr.firstlisten.core.SyncAccount
import java.io.File
import java.io.IOException

data class TakeoutImportState(
    val ownerKey: String? = null,
    val busy: Boolean = false,
    val result: ImportSummary? = null,
    val error: String? = null,
)

class TakeoutImportViewModel internal constructor(
    application: Application,
    private val api: FirstListenApi,
    private val accounts: AccountProvider,
    accountChanges: Flow<SyncAccount?>,
    private val prepareFile: suspend (Uri) -> File,
    scope: CoroutineScope? = null,
) : AndroidViewModel(application) {
    constructor(application: Application) : this(application, application.appGraph.api,
        application.appGraph.sessions, application.appGraph.sessions.accounts(),
        { stageTakeoutJson(application, it) })

    private val tasks = scope ?: viewModelScope
    private val mutable = MutableStateFlow(TakeoutImportState())
    val state = mutable.asStateFlow()
    @Volatile private var account: SyncAccount? = null
    private var selection: SyncAccount? = null
    private var upload: Job? = null

    init {
        tasks.launch {
            accountChanges.collect { next ->
                if (next != account) {
                    upload?.cancel()
                    selection = null
                    account = next
                    mutable.value = TakeoutImportState(ownerKey = next?.ownerKey)
                }
            }
        }
    }

    fun beginSelection(): Boolean {
        val owner = accounts.currentAccount() ?: run {
            account?.let(::expireIfNeeded)
            return false
        }
        if (owner != account || mutable.value.busy) return false
        selection = owner
        return true
    }

    fun importSelected(uri: Uri?) {
        val owner = selection ?: return
        selection = null
        if (uri == null || mutable.value.busy) return
        if (!isCurrent(owner)) {
            expireIfNeeded(owner)
            return
        }
        mutable.value = TakeoutImportState(ownerKey = owner.ownerKey, busy = true)
        upload = tasks.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val file = prepareFile(uri)
                    try {
                        ensureActive()
                        check(isCurrent(owner)) { "다시 로그인한 뒤 파일을 선택해 주세요." }
                        api.importTakeout(owner, file)
                    } finally { file.delete() }
                }
                if (isCurrent(owner)) mutable.value = TakeoutImportState(ownerKey = owner.ownerKey, result = result)
                else expireIfNeeded(owner)
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (isCurrent(owner)) {
                    mutable.value = TakeoutImportState(ownerKey = owner.ownerKey, error = importMessage(error))
                    if (error is HttpFailure && error.code == 401) accounts.requireLogin(owner)
                } else expireIfNeeded(owner)
            }
        }
    }

    private fun isCurrent(owner: SyncAccount) = owner == account && owner == accounts.currentAccount()

    private fun expireIfNeeded(owner: SyncAccount) {
        // The local expiry clock can elapse without a session Flow emission.
        if (owner == account && accounts.currentAccount() == null) accounts.requireLogin(owner)
    }
}

internal fun importMessage(error: Exception): String = when (error) {
    is HttpFailure -> when (error.code) {
        401 -> "로그인이 만료되었습니다. 다시 로그인한 뒤 파일을 선택해 주세요."
        409 -> "다른 가져오기가 진행 중이거나 기록이 충돌했습니다. 잠시 후 다시 시도해 주세요."
        413 -> "서버의 파일 크기 제한을 초과했습니다. 더 작은 JSON 파일을 선택해 주세요."
        422 -> "파일을 처리할 수 없습니다. 압축을 푼 Google Takeout 활동 기록 JSON인지 확인해 주세요."
        429 -> error.retryAfterSec?.let { "요청이 많습니다. ${it}초 후 다시 파일을 선택해 주세요." }
            ?: "요청이 많습니다. 잠시 후 다시 파일을 선택해 주세요."
        else -> "가져오기를 완료하지 못했습니다. 잠시 후 같은 파일로 다시 시도해 주세요."
    }
    is IOException -> "파일을 읽거나 서버 응답을 확인하지 못했습니다. 파일과 연결 상태를 확인하고 같은 파일로 다시 시도해 주세요. 이미 저장된 기록은 중복으로 추가되지 않습니다."
    is SecurityException -> "파일 읽기 권한이 없습니다. 파일을 다시 선택해 주세요."
    else -> error.message ?: "가져오기를 완료하지 못했습니다. 파일을 다시 선택해 주세요."
}
