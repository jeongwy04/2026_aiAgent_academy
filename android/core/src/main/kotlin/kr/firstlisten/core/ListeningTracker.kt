package kr.firstlisten.core

import java.text.Normalizer
import java.time.Instant
import java.util.Locale
import java.util.UUID
import kotlin.math.abs

data class TrackMetadata(
    val title: String,
    val artist: String,
    val album: String? = null,
    val externalId: String? = null,
) {
    fun sameRecording(other: TrackMetadata): Boolean =
        if (externalId != null && other.externalId != null) externalId == other.externalId
        else listOf(title, artist, album).map(::normalize) ==
            listOf(other.title, other.artist, other.album).map(::normalize)

    private fun normalize(value: String?): String = Normalizer.normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase(Locale.ROOT).trim().replace(Regex("\\s+"), " ")
}

enum class PlaybackStatus { PLAYING, PAUSED, BUFFERING, STOPPED, UNKNOWN }

data class PlaybackSample(
    val track: TrackMetadata?,
    val status: PlaybackStatus,
    val positionMs: Long? = null,
    val durationMs: Long? = null,
    val queueId: Long? = null,
    val stateUpdatedAtMs: Long? = null,
    val speed: Float = 1f,
)

data class ListenSnapshot(
    val ownerKey: String,
    val eventId: String,
    val track: TrackMetadata,
    val observedAt: String,
    val listenedMs: Long = 0,
    val version: Long = 1,
    val closed: Boolean = false,
)

/** One instance belongs to one account and one attached media session. Never infer a disconnected gap. */
class ListeningTracker(
    private val ownerKey: String,
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    private var current: ListenSnapshot? = null
    private var previous: PlaybackSample? = null
    private var previousAt: Long? = null
    private var pausedAt: Long? = null

    fun observe(sample: PlaybackSample, elapsedMs: Long, wallClock: Instant): List<ListenSnapshot> {
        val changes = mutableListOf<ListenSnapshot>()
        val before = previous
        val lastAt = previousAt
        val event = current
        // Compare live observations while preserving the event's original upload identity.
        // A stable ID discovered later can then identify subsequent metadata corrections.
        val identityTrack = before?.track ?: event?.track
        val changedTrack = event != null && sample.track != null && !identityTrack!!.sameRecording(sample.track)
        val changedQueueItem = before?.queueId != null && sample.queueId != null && before.queueId != sample.queueId
        val repeat = event != null && before != null && lastAt != null && !changedTrack &&
            naturalWrap(before, sample, elapsedMs - lastAt)
        val longPause = sample.status == PlaybackStatus.PLAYING && pausedAt?.let { elapsedMs - it > PAUSE_TIMEOUT_MS } == true

        if (event != null && before != null && lastAt != null) {
            var endAt = elapsedMs
            if (before.status == PlaybackStatus.PLAYING && sample.status != PlaybackStatus.PLAYING) {
                sample.stateUpdatedAtMs?.takeIf { it in lastAt..elapsedMs }?.let { endAt = it }
            }
            val delta = (endAt - lastAt).coerceAtLeast(0)
            val continuous = delta <= MAX_UNCONFIRMED_GAP_MS ||
                (!changedTrack && !changedQueueItem && !repeat && positionConfirms(before, sample, delta))
            if (before.status == PlaybackStatus.PLAYING && continuous && delta > 0) {
                addTime(delta, wallClock, changes)
            }
        }

        if (changedTrack || changedQueueItem || repeat || longPause || sample.track == null || sample.status == PlaybackStatus.STOPPED) {
            closeCurrent(changes)
        }
        if (current == null && sample.track != null && sample.status == PlaybackStatus.PLAYING) {
            current = ListenSnapshot(ownerKey, newId(), sample.track, wallClock.toString())
            changes += current!!
        }
        if (sample.status == PlaybackStatus.PAUSED && before?.status != PlaybackStatus.PAUSED) pausedAt = elapsedMs
        if (sample.status == PlaybackStatus.PLAYING) pausedAt = null
        previous = sample
        previousAt = elapsedMs
        return changes
    }

    /** Close only the last checkpoint. The time after the last observation is unknown. */
    fun disconnect(): List<ListenSnapshot> = mutableListOf<ListenSnapshot>().also {
        closeCurrent(it)
        previous = null
        previousAt = null
        pausedAt = null
    }

    private fun addTime(delta: Long, now: Instant, changes: MutableList<ListenSnapshot>) {
        var remaining = delta
        while (remaining > 0) {
            val event = current ?: return
            val amount = minOf(remaining, MAX_EVENT_MS - event.listenedMs)
            current = event.copy(listenedMs = event.listenedMs + amount, version = event.version + 1)
            changes += current!!
            remaining -= amount
            if (current!!.listenedMs == MAX_EVENT_MS) {
                closeCurrent(changes)
                current = ListenSnapshot(ownerKey, newId(), event.track, now.minusMillis(remaining).toString())
                changes += current!!
            }
        }
    }

    private fun closeCurrent(changes: MutableList<ListenSnapshot>) {
        current?.let { changes += it.copy(closed = true, version = it.version + 1) }
        current = null
    }

    private fun positionConfirms(before: PlaybackSample, after: PlaybackSample, delta: Long): Boolean {
        if (after.status != PlaybackStatus.PLAYING || before.track == null || after.track == null ||
            !before.track.sameRecording(after.track) || before.positionMs == null || after.positionMs == null) return false
        return abs((after.positionMs - before.positionMs) - delta * before.speed.toDouble()) <= 2_000
    }

    private fun naturalWrap(before: PlaybackSample, after: PlaybackSample, delta: Long): Boolean {
        val duration = before.durationMs ?: return false
        val oldPosition = before.positionMs ?: return false
        val newPosition = after.positionMs ?: return false
        return before.status == PlaybackStatus.PLAYING && after.status == PlaybackStatus.PLAYING &&
            before.stateUpdatedAtMs != after.stateUpdatedAtMs && delta in 0..MAX_UNCONFIRMED_GAP_MS &&
            duration > 10_000 && oldPosition >= duration - 2_000 && newPosition < 2_000 &&
            oldPosition + delta * before.speed >= duration - 500
    }

    companion object {
        const val MIN_LISTENED_MS = 30_000L
        const val MAX_EVENT_MS = 86_400_000L
        const val MAX_UNCONFIRMED_GAP_MS = 15_000L
        const val PAUSE_TIMEOUT_MS = 30 * 60_000L
    }
}
