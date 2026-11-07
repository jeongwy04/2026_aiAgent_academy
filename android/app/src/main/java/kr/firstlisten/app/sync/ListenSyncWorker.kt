package kr.firstlisten.app.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.sync.withLock
import kr.firstlisten.app.appGraph
import kr.firstlisten.app.data.RoomOutbox
import kr.firstlisten.core.SyncEngine
import kr.firstlisten.core.SyncOutcome
import java.util.concurrent.TimeUnit

class SyncScheduler(context: Context) {
    private val manager = WorkManager.getInstance(context)
    private val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun request(ownerKey: String) {
        val request = OneTimeWorkRequestBuilder<ListenSyncWorker>()
            .setInputData(workDataOf(OWNER_KEY to ownerKey))
            .setConstraints(constraints).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag(tag(ownerKey)).build()
        // Keep one queued upload while offline. Periodic work also recovers finish/enqueue races.
        manager.enqueueUniqueWork("listen-now-$ownerKey", ExistingWorkPolicy.KEEP, request)
    }

    fun periodic(ownerKey: String) {
        val request = PeriodicWorkRequestBuilder<ListenSyncWorker>(15, TimeUnit.MINUTES)
            .setInputData(workDataOf(OWNER_KEY to ownerKey)).setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).addTag(tag(ownerKey)).build()
        manager.enqueueUniquePeriodicWork("listen-periodic-$ownerKey", ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun cancel(ownerKey: String) { manager.cancelAllWorkByTag(tag(ownerKey)) }
    private fun tag(ownerKey: String) = "listen-owner-$ownerKey"
    companion object { const val OWNER_KEY = "owner_key" }
}

class ListenSyncWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val graph = applicationContext.appGraph
        val ownerKey = inputData.getString(SyncScheduler.OWNER_KEY) ?: return Result.failure()
        graph.ready.await()
        return graph.syncMutex.withLock {
            graph.syncStatus.value = "청취 기록 전송 중"
            when (SyncEngine(graph.sessions, RoomOutbox(graph.database.events()), graph.api).run(ownerKey)) {
                SyncOutcome.SUCCESS -> {
                    graph.syncStatus.value = "전송 완료 · 보류 기록은 별도 확인"
                    Result.success()
                }
                SyncOutcome.RETRY -> {
                    graph.syncStatus.value = "전송 실패 · 연결 후 자동 재시도"
                    Result.retry()
                }
                SyncOutcome.NEEDS_LOGIN -> {
                    graph.syncStatus.value = "다시 로그인하면 전송을 재개합니다."
                    Result.success()
                }
                SyncOutcome.ACCOUNT_CHANGED -> Result.success()
            }
        }
    }
}
