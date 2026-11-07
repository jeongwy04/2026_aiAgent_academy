package kr.firstlisten.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class SyncEngineTest {
    private val alice = SyncAccount("alice", "https://server.example", "token-a", "login-a")
    private class Accounts(var value: SyncAccount?) : AccountProvider {
        var expired: SyncAccount? = null
        override fun currentAccount() = value
        override fun requireLogin(account: SyncAccount) { if (value == account) { expired = account; value = null } }
    }
    private class Outbox : ListenOutbox {
        val rows = linkedMapOf<String, ListenSnapshot>()
        val uploaded = mutableMapOf<String, Long>()
        val errors = mutableMapOf<String, String>()
        override suspend fun pending(ownerKey: String, limit: Int) = rows.values.filter {
            it.ownerKey == ownerKey && it.listenedMs >= 30_000 && it.version > uploaded.getOrDefault(it.eventId, 0) && it.eventId !in errors
        }.take(limit)
        override suspend fun acknowledge(ownerKey: String, eventId: String, version: Long, trackId: String) {
            check(rows.getValue(eventId).ownerKey == ownerKey)
            uploaded[eventId] = maxOf(uploaded.getOrDefault(eventId, 0), version)
        }
        override suspend fun reject(ownerKey: String, eventId: String, reason: String) { errors[eventId] = reason }
    }
    private val accounts = Accounts(alice)
    private val outbox = Outbox()
    private fun event(id: String = "e1", owner: String = "alice", ms: Long = 31_000, version: Long = 1) =
        ListenSnapshot(owner, id, TrackMetadata("입춘", "한로로"), "2026-11-07T00:00:00Z", ms, version)
    private fun acknowledgements(batch: List<ListenSnapshot>) = batch.map { SyncAck(it.eventId, "accepted", "track-id", it.listenedMs) }

    @Test fun `version updated during upload remains pending after old snapshot acknowledgement`() = runBlocking {
        outbox.rows["e1"] = event()
        var calls = 0
        val engine = SyncEngine(accounts, outbox) { _, batch ->
            if (++calls > 1) throw IOException("offline")
            outbox.rows["e1"] = event(ms = 45_000, version = 2)
            acknowledgements(batch)
        }
        assertEquals(SyncOutcome.RETRY, engine.run("alice"))
        assertEquals(1L, outbox.uploaded["e1"])
        assertEquals(45_000L, outbox.pending("alice", 100).single().listenedMs)
    }

    @Test fun `only current account eligible records are batched at a maximum of one hundred`() = runBlocking {
        repeat(201) { outbox.rows["a$it"] = event("a$it") }
        outbox.rows["bob"] = event("bob", owner = "bob")
        outbox.rows["short"] = event("short", ms = 29_999)
        val sizes = mutableListOf<Int>()
        val outcome = SyncEngine(accounts, outbox) { account, batch ->
            assertEquals(alice, account)
            assertTrue(batch.all { it.ownerKey == "alice" })
            sizes += batch.size
            acknowledgements(batch)
        }.run("alice")
        assertEquals(SyncOutcome.SUCCESS, outcome)
        assertEquals(listOf(100, 100, 1), sizes)
        assertFalse("bob" in outbox.uploaded)
    }

    @Test fun `failed batch is split so one invalid event cannot block valid records`() = runBlocking {
        listOf("good1", "bad", "good2").forEach { outbox.rows[it] = event(it) }
        val outcome = SyncEngine(accounts, outbox) { _, batch ->
            if (batch.any { it.eventId == "bad" }) throw HttpFailure(409, "event reused")
            acknowledgements(batch)
        }.run("alice")
        assertEquals(SyncOutcome.SUCCESS, outcome)
        assertEquals(setOf("good1", "good2"), outbox.uploaded.keys)
        assertEquals(setOf("bad"), outbox.errors.keys)
    }

    @Test fun `network errors and temporary HTTP failures preserve records for retry`() = runBlocking {
        outbox.rows["e1"] = event()
        for (error in listOf(IOException("offline"), HttpFailure(503, "unavailable"), HttpFailure(429, "limited"))) {
            assertEquals(SyncOutcome.RETRY, SyncEngine(accounts, outbox) { _, _ -> throw error }.run("alice"))
            assertTrue(outbox.uploaded.isEmpty())
        }
    }

    @Test fun `unauthorized response pauses uploads and retains pending records`() = runBlocking {
        outbox.rows["e1"] = event()
        assertEquals(SyncOutcome.NEEDS_LOGIN, SyncEngine(accounts, outbox) { _, _ -> throw HttpFailure(401, "expired") }.run("alice"))
        assertEquals(alice, accounts.expired)
        assertTrue(outbox.uploaded.isEmpty())
    }

    @Test fun `old account worker never uses new account credentials`() = runBlocking {
        accounts.value = alice.copy(ownerKey = "bob", token = "token-b")
        assertEquals(SyncOutcome.ACCOUNT_CHANGED, SyncEngine(accounts, outbox) { _, _ -> error("must not send") }.run("alice"))
    }

    @Test fun `switching account while response is in flight only acknowledges original owner`() = runBlocking {
        outbox.rows["e1"] = event()
        outbox.rows["bob"] = event("bob", "bob")
        val outcome = SyncEngine(accounts, outbox) { _, batch ->
            accounts.value = alice.copy(ownerKey = "bob", token = "token-b")
            acknowledgements(batch)
        }.run("alice")
        assertEquals(SyncOutcome.ACCOUNT_CHANGED, outcome)
        assertEquals(setOf("e1"), outbox.uploaded.keys)
    }

    @Test fun `incomplete or invalid success response never discards pending records`() = runBlocking {
        outbox.rows["e1"] = event()
        val invalid = listOf(emptyList(), listOf(SyncAck("other", "accepted", "track", 31_000)),
            listOf(SyncAck("e1", "accepted", "track", 0)), listOf(SyncAck("e1", "ignored_below_threshold", null, null)))
        for (response in invalid) {
            assertEquals(SyncOutcome.RETRY, SyncEngine(accounts, outbox) { _, _ -> response }.run("alice"))
            assertTrue(outbox.uploaded.isEmpty())
        }
    }
}
