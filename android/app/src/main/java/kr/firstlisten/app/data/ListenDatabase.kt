package kr.firstlisten.app.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow
import kr.firstlisten.core.ListenOutbox
import kr.firstlisten.core.ListenSnapshot
import kr.firstlisten.core.TrackMetadata

@Entity(tableName = "listen_events", primaryKeys = ["ownerKey", "eventId"], indices = [Index("ownerKey")])
data class ListenEventEntity(
    val ownerKey: String,
    val eventId: String,
    val title: String,
    val artist: String,
    val album: String?,
    val externalId: String?,
    val observedAt: String,
    val listenedMs: Long,
    val localVersion: Long,
    val uploadedVersion: Long = 0,
    val closed: Boolean,
    val trackId: String? = null,
    val error: String? = null,
) {
    fun snapshot() = ListenSnapshot(ownerKey, eventId, TrackMetadata(title, artist, album, externalId),
        observedAt, listenedMs, localVersion, closed)

    companion object {
        fun from(s: ListenSnapshot) = ListenEventEntity(s.ownerKey, s.eventId, s.track.title, s.track.artist,
            s.track.album, s.track.externalId, s.observedAt, s.listenedMs, s.version, closed = s.closed)
    }
}

@Dao
abstract class ListenEventDao {
    @Query("SELECT * FROM listen_events WHERE ownerKey = :ownerKey AND eventId = :eventId")
    abstract suspend fun find(ownerKey: String, eventId: String): ListenEventEntity?

    @Upsert
    abstract suspend fun upsert(entity: ListenEventEntity)

    @Transaction
    open suspend fun record(snapshot: ListenSnapshot) {
        val existing = find(snapshot.ownerKey, snapshot.eventId)
        if (existing != null && existing.localVersion >= snapshot.version) return
        upsert(ListenEventEntity.from(snapshot).copy(uploadedVersion = existing?.uploadedVersion ?: 0,
            trackId = existing?.trackId, error = existing?.error))
    }

    @Query("SELECT * FROM listen_events WHERE ownerKey = :ownerKey AND listenedMs >= 30000 AND localVersion > uploadedVersion AND error IS NULL ORDER BY observedAt, eventId LIMIT :limit")
    abstract suspend fun pending(ownerKey: String, limit: Int): List<ListenEventEntity>

    @Query("UPDATE listen_events SET uploadedVersion = MAX(uploadedVersion, :version), trackId = :trackId WHERE ownerKey = :ownerKey AND eventId = :eventId")
    abstract suspend fun acknowledge(ownerKey: String, eventId: String, version: Long, trackId: String)

    @Query("UPDATE listen_events SET error = :reason WHERE ownerKey = :ownerKey AND eventId = :eventId")
    abstract suspend fun reject(ownerKey: String, eventId: String, reason: String)

    @Query("UPDATE listen_events SET error = NULL WHERE ownerKey = :ownerKey")
    abstract suspend fun retryRejected(ownerKey: String)

    @Query("SELECT * FROM listen_events WHERE ownerKey = :ownerKey ORDER BY observedAt DESC, eventId LIMIT 30")
    abstract fun recent(ownerKey: String): Flow<List<ListenEventEntity>>

    @Query("SELECT COUNT(*) FROM listen_events WHERE ownerKey = :ownerKey AND listenedMs >= 30000 AND localVersion > uploadedVersion AND error IS NULL")
    abstract fun pendingCount(ownerKey: String): Flow<Int>

    @Query("SELECT COUNT(*) FROM listen_events WHERE ownerKey = :ownerKey AND error IS NOT NULL")
    abstract fun rejectedCount(ownerKey: String): Flow<Int>

    @Query("UPDATE listen_events SET closed = 1, localVersion = localVersion + 1 WHERE closed = 0")
    abstract suspend fun closeInterruptedEvents()
}

@Database(entities = [ListenEventEntity::class], version = 1, exportSchema = true)
abstract class ListenDatabase : RoomDatabase() {
    abstract fun events(): ListenEventDao
}

class RoomOutbox(private val dao: ListenEventDao) : ListenOutbox {
    override suspend fun pending(ownerKey: String, limit: Int) = dao.pending(ownerKey, limit).map { it.snapshot() }
    override suspend fun acknowledge(ownerKey: String, eventId: String, version: Long, trackId: String) =
        dao.acknowledge(ownerKey, eventId, version, trackId)
    override suspend fun reject(ownerKey: String, eventId: String, reason: String) = dao.reject(ownerKey, eventId, reason)
}
