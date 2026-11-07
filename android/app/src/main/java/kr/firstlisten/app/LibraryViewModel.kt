package kr.firstlisten.app

import android.app.Application
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
import kr.firstlisten.app.network.FirstListenApi
import kr.firstlisten.app.network.TrackOut
import kr.firstlisten.app.network.TrackStats
import kr.firstlisten.app.network.accounts
import kr.firstlisten.app.network.requestMessage
import kr.firstlisten.core.AccountProvider
import kr.firstlisten.core.HttpFailure
import kr.firstlisten.core.SyncAccount
import java.util.concurrent.atomic.AtomicLong

data class LibraryUiState(
    val ownerKey: String? = null,
    val query: String = "",
    val tracks: List<TrackOut> = emptyList(),
    val total: Int = 0,
    val nextOffset: Int = 0,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val hasMore: Boolean = false,
    val error: String? = null,
    val selectedTrack: TrackOut? = null,
    val stats: TrackStats? = null,
    val detailLoading: Boolean = false,
    val detailError: String? = null,
)

class LibraryViewModel internal constructor(
    application: Application,
    private val api: FirstListenApi,
    private val accounts: AccountProvider,
    accountChanges: Flow<SyncAccount?>,
    scope: CoroutineScope? = null,
) : AndroidViewModel(application) {
    constructor(application: Application) : this(application, application.appGraph.api,
        application.appGraph.sessions, application.appGraph.sessions.accounts())

    private val tasks = scope ?: viewModelScope
    private val mutable = MutableStateFlow(LibraryUiState())
    val state = mutable.asStateFlow()
    @Volatile private var account: SyncAccount? = null
    private var searchJob: Job? = null
    private var pageJob: Job? = null
    private var detailJob: Job? = null
    private val searchVersion = AtomicLong()
    private val detailVersion = AtomicLong()

    init {
        tasks.launch {
            accountChanges.collect { next ->
                if (next != account) {
                    searchJob?.cancel()
                    pageJob?.cancel()
                    detailJob?.cancel()
                    searchVersion.incrementAndGet()
                    detailVersion.incrementAndGet()
                    account = next
                    mutable.value = LibraryUiState(ownerKey = next?.ownerKey)
                    if (next != null) loadFirst(debounce = false)
                }
            }
        }
    }

    fun setQuery(query: String) {
        val value = query.take(300)
        if (value == mutable.value.query) return
        closeDetail()
        mutable.update { it.copy(query = value, tracks = emptyList(), total = 0, nextOffset = 0, hasMore = false) }
        loadFirst(debounce = true)
    }

    fun refresh() {
        loadFirst(debounce = false)
        mutable.value.selectedTrack?.let(::selectTrack)
    }

    private fun loadFirst(debounce: Boolean) {
        val owner = activeAccount() ?: return
        val query = mutable.value.query
        val version = searchVersion.incrementAndGet()
        searchJob?.cancel()
        pageJob?.cancel()
        mutable.update { it.copy(loading = true, loadingMore = false, error = null) }
        searchJob = tasks.launch {
            try {
                if (debounce) delay(300)
                val page = api.tracks(owner, query)
                if (isCurrent(owner) && version == searchVersion.get()) {
                    val nextOffset = page.offset + page.items.size
                    mutable.update { it.copy(tracks = page.items.distinctBy(TrackOut::id), total = page.total,
                        nextOffset = nextOffset, loading = false,
                        hasMore = page.items.isNotEmpty() && nextOffset < page.total && nextOffset <= 100_000) }
                }
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (isCurrent(owner) && version == searchVersion.get() && !expire(owner, error)) {
                    mutable.update { it.copy(loading = false, error = requestMessage(error)) }
                }
            }
        }
    }

    fun loadMore() {
        val before = mutable.value
        if (before.loading || before.loadingMore || !before.hasMore) return
        val owner = activeAccount() ?: return
        val version = searchVersion.get()
        mutable.update { it.copy(loadingMore = true, error = null) }
        pageJob = tasks.launch {
            try {
                val page = api.tracks(owner, before.query, offset = before.nextOffset)
                if (isCurrent(owner) && version == searchVersion.get()) {
                    val nextOffset = page.offset + page.items.size
                    mutable.update { it.copy(tracks = (it.tracks + page.items).distinctBy(TrackOut::id),
                        total = page.total, nextOffset = nextOffset, loadingMore = false,
                        hasMore = page.items.isNotEmpty() && nextOffset < page.total && nextOffset <= 100_000) }
                }
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (isCurrent(owner) && version == searchVersion.get() && !expire(owner, error)) {
                    mutable.update { it.copy(loadingMore = false, error = requestMessage(error)) }
                }
            }
        }
    }

    fun selectTrack(track: TrackOut) {
        val owner = activeAccount() ?: return
        val version = detailVersion.incrementAndGet()
        detailJob?.cancel()
        mutable.update { it.copy(selectedTrack = track, stats = null, detailLoading = true, detailError = null) }
        detailJob = tasks.launch {
            try {
                val stats = api.stats(owner, track.id)
                if (isCurrent(owner) && version == detailVersion.get()) {
                    mutable.update { it.copy(selectedTrack = stats.track, stats = stats, detailLoading = false) }
                }
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (isCurrent(owner) && version == detailVersion.get() && !expire(owner, error)) {
                    mutable.update { it.copy(detailLoading = false, detailError = requestMessage(error)) }
                }
            }
        }
    }

    fun closeDetail() {
        detailVersion.incrementAndGet()
        detailJob?.cancel()
        mutable.update { it.copy(selectedTrack = null, stats = null, detailLoading = false, detailError = null) }
    }

    private fun activeAccount(): SyncAccount? {
        val current = accounts.currentAccount()
        if (current == null || current != account) {
            mutable.value = LibraryUiState()
            return null
        }
        return current
    }

    private fun isCurrent(owner: SyncAccount) = owner == account && owner == accounts.currentAccount()

    private fun expire(owner: SyncAccount, error: Exception): Boolean {
        if (error !is HttpFailure || error.code != 401) return false
        accounts.requireLogin(owner)
        mutable.value = LibraryUiState()
        return true
    }
}
