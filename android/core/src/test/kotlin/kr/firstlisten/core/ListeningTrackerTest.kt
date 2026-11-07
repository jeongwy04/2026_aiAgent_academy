package kr.firstlisten.core

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class ListeningTrackerTest {
    private val song = TrackMetadata("입춘", "한로로", externalId = "abcdefghijk")
    private val start = Instant.parse("2026-11-07T00:00:00Z")
    private val tracker = ListeningTracker("alice")
    private var latest: ListenSnapshot? = null

    private fun observe(ms: Long, sample: PlaybackSample = PlaybackSample(song, PlaybackStatus.PLAYING)): List<ListenSnapshot> =
        tracker.observe(sample, ms, start.plusMillis(ms)).also { if (it.isNotEmpty()) latest = it.last() }

    @Test fun `pause and buffering do not accrue time and resume keeps event identity`() {
        observe(0)
        val id = latest!!.eventId
        observe(10_000)
        observe(12_000, PlaybackSample(song, PlaybackStatus.PAUSED))
        observe(100_000, PlaybackSample(song, PlaybackStatus.BUFFERING))
        observe(105_000)
        observe(115_000)
        assertEquals(id, latest!!.eventId)
        assertEquals(22_000L, latest!!.listenedMs)
        assertEquals(start.toString(), latest!!.observedAt)
    }

    @Test fun `seeking forwards or backwards does not count skipped media or create events`() {
        observe(0, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 0))
        val id = latest!!.eventId
        observe(5_000, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 120_000))
        observe(10_000, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 0))
        assertEquals(10_000L, latest!!.listenedMs)
        assertEquals(id, latest!!.eventId)
    }

    @Test fun `track change closes old event and repeated callback does not create another`() {
        observe(0)
        val oldId = latest!!.eventId
        val next = PlaybackSample(song.copy(title = "다음 곡", externalId = "lmnopqrstuv"), PlaybackStatus.PLAYING)
        val changes = observe(5_000, next)
        assertTrue(changes.first { it.eventId == oldId && it.closed }.closed)
        assertEquals(5_000L, changes.first { it.closed }.listenedMs)
        val newId = latest!!.eventId
        observe(5_000, next)
        assertNotEquals(oldId, newId)
        assertEquals(newId, latest!!.eventId)
    }

    @Test fun `late external ID and metadata corrections keep frozen event payload`() {
        val initial = song.copy(externalId = null)
        observe(0, PlaybackSample(initial, PlaybackStatus.PLAYING))
        val id = latest!!.eventId
        observe(5_000)
        assertEquals(id, latest!!.eventId)
        assertNull(latest!!.track.externalId)
        observe(10_000, PlaybackSample(song.copy(title = "입춘 (수정)"), PlaybackStatus.PLAYING))
        assertEquals(id, latest!!.eventId)
        assertEquals(initial, latest!!.track)
    }

    @Test fun `natural end wrap creates new event but duplicate state update does not`() {
        observe(0, PlaybackSample(song, PlaybackStatus.PLAYING, 59_000, 60_000, stateUpdatedAtMs = 0))
        val id = latest!!.eventId
        observe(1_500, PlaybackSample(song, PlaybackStatus.PLAYING, 500, 60_000, stateUpdatedAtMs = 1_500))
        assertNotEquals(id, latest!!.eventId)
        val repeatedId = latest!!.eventId
        observe(1_500, PlaybackSample(song, PlaybackStatus.PLAYING, 500, 60_000, stateUpdatedAtMs = 1_500))
        assertEquals(repeatedId, latest!!.eventId)
    }

    @Test fun `queue item change distinguishes consecutive copies of the same song`() {
        observe(0, PlaybackSample(song, PlaybackStatus.PLAYING, queueId = 1))
        val id = latest!!.eventId
        observe(5_000, PlaybackSample(song, PlaybackStatus.PLAYING, queueId = 2))
        assertNotEquals(id, latest!!.eventId)
    }

    @Test fun `unobserved gap is discarded unless playback position confirms continuity`() {
        observe(0, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 0))
        observe(60_000, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 60_000))
        assertEquals(60_000L, latest!!.listenedMs)
        observe(120_000, PlaybackSample(song, PlaybackStatus.PLAYING, positionMs = 61_000))
        assertEquals(60_000L, latest!!.listenedMs)
    }

    @Test fun `pause callback timestamp prevents delayed callback overcount`() {
        observe(0)
        observe(5_000)
        observe(15_000, PlaybackSample(song, PlaybackStatus.PAUSED, stateUpdatedAtMs = 7_000))
        assertEquals(7_000L, latest!!.listenedMs)
    }

    @Test fun `disconnect only closes last checkpoint and reconnection starts fresh`() {
        observe(0)
        observe(5_000)
        val closed = tracker.disconnect().single()
        assertTrue(closed.closed)
        assertEquals(5_000L, closed.listenedMs)
        observe(360_000)
        assertNotEquals(closed.eventId, latest!!.eventId)
        assertEquals(0L, latest!!.listenedMs)
    }

    @Test fun `long pause starts new session and missing metadata suspends collection`() {
        observe(0)
        observe(5_000, PlaybackSample(song, PlaybackStatus.PAUSED))
        val id = latest!!.eventId
        observe(2_000_000)
        assertNotEquals(id, latest!!.eventId)
        observe(2_005_000, PlaybackSample(null, PlaybackStatus.PLAYING))
        assertTrue(latest!!.closed)
        assertTrue(observe(2_010_000, PlaybackSample(null, PlaybackStatus.PLAYING)).isEmpty())
    }

    @Test fun `twenty four hour sessions roll over without exceeding server duration limit`() {
        observe(0)
        val closed = mutableListOf<ListenSnapshot>()
        for (ms in 5_000L..86_405_000L step 5_000) closed += observe(ms).filter { it.closed }
        assertEquals(1, closed.size)
        assertEquals(86_400_000L, closed.single().listenedMs)
        assertEquals(5_000L, latest!!.listenedMs)
    }
}
