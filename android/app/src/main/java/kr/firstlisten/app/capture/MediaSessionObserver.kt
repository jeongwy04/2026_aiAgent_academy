package kr.firstlisten.app.capture

import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.PlaybackState
import android.net.Uri
import kr.firstlisten.core.PlaybackSample
import kr.firstlisten.core.PlaybackStatus
import kr.firstlisten.core.TrackMetadata

object MediaSessionObserver {
    const val YOUTUBE_MUSIC_PACKAGE = "com.google.android.apps.youtube.music"

    fun sample(controller: MediaController, elapsedMs: Long): PlaybackSample =
        sample(controller.metadata, controller.playbackState, elapsedMs)

    internal fun sample(metadata: MediaMetadata?, state: PlaybackState?, elapsedMs: Long): PlaybackSample {
        val status = when (state?.state) {
            PlaybackState.STATE_PLAYING -> if (state.playbackSpeed > 0) PlaybackStatus.PLAYING else PlaybackStatus.PAUSED
            PlaybackState.STATE_PAUSED -> PlaybackStatus.PAUSED
            PlaybackState.STATE_BUFFERING, PlaybackState.STATE_CONNECTING -> PlaybackStatus.BUFFERING
            PlaybackState.STATE_STOPPED, PlaybackState.STATE_NONE, PlaybackState.STATE_ERROR -> PlaybackStatus.STOPPED
            else -> PlaybackStatus.UNKNOWN
        }
        val duration = metadata?.getLong(MediaMetadata.METADATA_KEY_DURATION)?.takeIf { it > 0 }
        val position = state?.position?.takeIf { it >= 0 }?.let { position ->
            val advance = if (status == PlaybackStatus.PLAYING && state.lastPositionUpdateTime > 0)
                ((elapsedMs - state.lastPositionUpdateTime).coerceAtLeast(0) * state.playbackSpeed).toLong() else 0
            (position + advance).let { if (duration != null) it.coerceAtMost(duration) else it }
        }
        return PlaybackSample(metadata?.let(::track), status, position, duration,
            state?.activeQueueItemId?.takeIf { it >= 0 }, state?.lastPositionUpdateTime?.takeIf { it > 0 }, state?.playbackSpeed ?: 1f)
    }

    private fun track(metadata: MediaMetadata): TrackMetadata? {
        val title = (metadata.getString(MediaMetadata.METADATA_KEY_TITLE)
            ?: metadata.getString(MediaMetadata.METADATA_KEY_DISPLAY_TITLE))?.trim()?.takeIf { it.isNotBlank() } ?: return null
        val artist = metadata.getString(MediaMetadata.METADATA_KEY_ARTIST)?.trim()?.takeIf { it.isNotBlank() } ?: return null
        val album = metadata.getString(MediaMetadata.METADATA_KEY_ALBUM)?.trim()?.takeIf { it.isNotBlank() }
        val externalId = youtubeId(metadata.getString(MediaMetadata.METADATA_KEY_MEDIA_ID))
            ?: youtubeId(metadata.getString(MediaMetadata.METADATA_KEY_MEDIA_URI))
        return TrackMetadata(title, artist, album, externalId)
    }

    // A media ID can be opaque. Only recognizable YouTube IDs/URLs are sent as external_id.
    private fun youtubeId(value: String?): String? {
        if (value == null) return null
        if (VIDEO_ID.matches(value)) return value
        val uri = Uri.parse(value)
        val id = when (uri.host?.lowercase()) {
            "youtube.com", "www.youtube.com", "music.youtube.com" -> if (uri.path == "/watch") uri.getQueryParameter("v") else null
            "youtu.be" -> uri.lastPathSegment
            else -> null
        }
        return id?.takeIf(VIDEO_ID::matches)
    }

    private val VIDEO_ID = Regex("[A-Za-z0-9_-]{11}")
}
