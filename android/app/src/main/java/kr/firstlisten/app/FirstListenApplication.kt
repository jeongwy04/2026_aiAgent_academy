package kr.firstlisten.app

import android.app.Application
import android.content.Context
import androidx.room.Room
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kr.firstlisten.app.data.ListenDatabase
import kr.firstlisten.app.data.SessionStore
import kr.firstlisten.app.network.FirstListenApi
import kr.firstlisten.app.sync.SyncScheduler

data class CaptureStatus(
    val connected: Boolean = false,
    val message: String = "알림 접근 권한을 허용해 주세요.",
    val track: String? = null,
    val listenedMs: Long = 0,
)

class AppGraph(context: Context) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val sessions = SessionStore(context)
    val database = Room.databaseBuilder(context, ListenDatabase::class.java, "firstlisten.db").build()
    val api = FirstListenApi(allowHttp = BuildConfig.DEBUG)
    val captureStatus = MutableStateFlow(CaptureStatus())
    val syncStatus = MutableStateFlow("전송 대기")
    val syncMutex = Mutex()
    val ready = scope.async { database.events().closeInterruptedEvents() }
    val scheduler = SyncScheduler(context)

    init {
        scope.launch {
            ready.await()
            var scheduledOwner: String? = null
            sessions.state.collectLatest {
                val account = sessions.currentAccount()
                if (scheduledOwner != account?.ownerKey) scheduledOwner?.let(scheduler::cancel)
                scheduledOwner = account?.ownerKey
                account?.let {
                    scheduler.periodic(it.ownerKey)
                    scheduler.request(it.ownerKey)
                }
            }
        }
    }
}

class FirstListenApplication : Application() {
    val graph: AppGraph by lazy { AppGraph(this) }
    override fun onCreate() {
        super.onCreate()
        graph
    }
}

val Context.appGraph: AppGraph get() = (applicationContext as FirstListenApplication).graph
