package kr.firstlisten.core

import java.io.IOException

data class SyncAccount(val ownerKey: String, val baseUrl: String, val token: String, val sessionId: String)
data class SyncAck(val eventId: String, val status: String, val trackId: String?, val listenedMs: Long?)
class HttpFailure(val code: Int, message: String, val retryAfterSec: Long? = null) : IOException(message)

interface AccountProvider {
    fun currentAccount(): SyncAccount?
    fun requireLogin(account: SyncAccount)
}

interface ListenOutbox {
    suspend fun pending(ownerKey: String, limit: Int): List<ListenSnapshot>
    suspend fun acknowledge(ownerKey: String, eventId: String, version: Long, trackId: String)
    suspend fun reject(ownerKey: String, eventId: String, reason: String)
}

fun interface SyncTransport {
    suspend fun send(account: SyncAccount, events: List<ListenSnapshot>): List<SyncAck>
}

enum class SyncOutcome { SUCCESS, RETRY, NEEDS_LOGIN, ACCOUNT_CHANGED }

/** All acknowledgements refer to the sent snapshot, never to a newer local version. */
class SyncEngine(
    private val accounts: AccountProvider,
    private val outbox: ListenOutbox,
    private val transport: SyncTransport,
) {
    suspend fun run(ownerKey: String): SyncOutcome {
        val account = accounts.currentAccount() ?: return SyncOutcome.NEEDS_LOGIN
        if (account.ownerKey != ownerKey) return SyncOutcome.ACCOUNT_CHANGED
        repeat(10) {
            if (accounts.currentAccount() != account) return SyncOutcome.ACCOUNT_CHANGED
            val batch = outbox.pending(ownerKey, 100)
            if (batch.isEmpty()) return SyncOutcome.SUCCESS
            val result = sendBatch(account, batch)
            if (result != SyncOutcome.SUCCESS) return result
        }
        return if (outbox.pending(ownerKey, 1).isEmpty()) SyncOutcome.SUCCESS else SyncOutcome.RETRY
    }

    private suspend fun sendBatch(account: SyncAccount, batch: List<ListenSnapshot>): SyncOutcome {
        if (accounts.currentAccount() != account) return SyncOutcome.ACCOUNT_CHANGED
        try {
            val results = transport.send(account, batch)
            val byId = results.associateBy { it.eventId }
            if (results.size != batch.size || byId.size != batch.size || batch.any {
                val ack = byId[it.eventId]
                ack == null || ack.status != "accepted" || ack.trackId == null ||
                    ack.listenedMs == null || ack.listenedMs < it.listenedMs
            }) return SyncOutcome.RETRY
            batch.forEach { outbox.acknowledge(account.ownerKey, it.eventId, it.version, byId.getValue(it.eventId).trackId!!) }
            return SyncOutcome.SUCCESS
        } catch (error: HttpFailure) {
            when (error.code) {
                401 -> {
                    accounts.requireLogin(account)
                    return SyncOutcome.NEEDS_LOGIN
                }
                409, 422 -> {
                    // A rejected batch is atomic on the server. Split it to preserve valid neighbours.
                    if (batch.size == 1) {
                        outbox.reject(account.ownerKey, batch.single().eventId, "${error.code}: ${error.message}")
                        return SyncOutcome.SUCCESS
                    }
                    val middle = batch.size / 2
                    val left = sendBatch(account, batch.take(middle))
                    return if (left == SyncOutcome.SUCCESS) sendBatch(account, batch.drop(middle)) else left
                }
                else -> return SyncOutcome.RETRY
            }
        } catch (_: IOException) {
            return SyncOutcome.RETRY
        }
    }
}
