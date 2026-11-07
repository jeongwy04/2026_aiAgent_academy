package kr.firstlisten.app.data

import android.app.Application
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import kr.firstlisten.core.ListenSnapshot
import kr.firstlisten.core.TrackMetadata
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class ListenDatabaseTest {
    private val context = ApplicationProvider.getApplicationContext<Application>()
    private var database = Room.databaseBuilder(context, ListenDatabase::class.java, "outbox-test.db").build()
    private fun event(owner: String = "alice", ms: Long = 31_000, version: Long = 1) =
        ListenSnapshot(owner, "event-1", TrackMetadata("입춘", "한로로"), "2026-11-07T00:00:00Z", ms, version)

    @After fun cleanup() { database.close(); context.deleteDatabase("outbox-test.db") }

    @Test fun `checkpoint and acknowledgment interleaving preserves newer version`() = runBlocking {
        val dao = database.events()
        dao.record(event())
        dao.record(event(ms = 45_000, version = 2))
        dao.acknowledge("alice", "event-1", 1, "track-1")
        assertEquals(45_000L, dao.pending("alice", 100).single().listenedMs)
        dao.record(event(ms = 50_000, version = 3))
        assertEquals(1L, dao.find("alice", "event-1")!!.uploadedVersion)
        dao.acknowledge("alice", "event-1", 3, "track-1")
        assertTrue(dao.pending("alice", 100).isEmpty())
    }

    @Test fun `outbox survives reopening and isolates accounts including shared event IDs`() = runBlocking {
        database.events().record(event())
        database.events().record(event("bob", 60_000))
        database.close()
        database = Room.databaseBuilder(context, ListenDatabase::class.java, "outbox-test.db").build()
        database.events().acknowledge("alice", "event-1", 1, "track-a")
        assertTrue(database.events().pending("alice", 100).isEmpty())
        assertEquals(60_000L, database.events().pending("bob", 100).single().listenedMs)
    }

    @Test fun `threshold quarantine and interrupted sessions are preserved`() = runBlocking {
        val dao = database.events()
        dao.record(event(ms = 29_999))
        assertTrue(dao.pending("alice", 100).isEmpty())
        dao.record(event(ms = 30_000, version = 2))
        dao.reject("alice", "event-1", "422 invalid")
        dao.record(event(ms = 35_000, version = 3))
        assertTrue(dao.pending("alice", 100).isEmpty())
        dao.closeInterruptedEvents()
        assertTrue(dao.find("alice", "event-1")!!.closed)
        dao.retryRejected("alice")
        assertEquals(35_000L, dao.pending("alice", 100).single().listenedMs)
    }
}
