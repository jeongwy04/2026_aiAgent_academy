package kr.firstlisten.app.capture

import android.app.Application
import android.media.MediaMetadata
import android.media.session.PlaybackState
import kr.firstlisten.core.PlaybackStatus
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class MediaSessionObserverTest {
    @Test fun `playing session exposes metadata and estimates position without treating it as duration`() {
        val metadata = MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, "입춘")
            .putString(MediaMetadata.METADATA_KEY_ARTIST, "한로로")
            .putString(MediaMetadata.METADATA_KEY_MEDIA_ID, "https://music.youtube.com/watch?v=abcdefghijk")
            .putLong(MediaMetadata.METADATA_KEY_DURATION, 180_000).build()
        val state = PlaybackState.Builder().setState(PlaybackState.STATE_PLAYING, 90_000, 1f, 1_000).build()
        val sample = MediaSessionObserver.sample(metadata, state, 6_000)
        assertEquals(PlaybackStatus.PLAYING, sample.status)
        assertEquals("abcdefghijk", sample.track!!.externalId)
        assertEquals("한로로", sample.track!!.artist)
        assertEquals(95_000L, sample.positionMs)
    }

    @Test fun `missing artist and opaque media IDs are not fabricated`() {
        val incomplete = MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, "입춘").build()
        assertNull(MediaSessionObserver.sample(incomplete, null, 0).track)
        val opaque = MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, "입춘")
            .putString(MediaMetadata.METADATA_KEY_ARTIST, "한로로")
            .putString(MediaMetadata.METADATA_KEY_MEDIA_ID, "opaque-local-identifier").build()
        assertNull(MediaSessionObserver.sample(opaque, null, 0).track!!.externalId)
    }

    @Test fun `buffering and zero-speed playing states do not count as playing`() {
        val buffering = PlaybackState.Builder().setState(PlaybackState.STATE_BUFFERING, 5_000, 1f).build()
        assertEquals(PlaybackStatus.BUFFERING, MediaSessionObserver.sample(null, buffering, 0).status)
        val stopped = PlaybackState.Builder().setState(PlaybackState.STATE_PLAYING, 5_000, 0f).build()
        assertEquals(PlaybackStatus.PAUSED, MediaSessionObserver.sample(null, stopped, 0).status)
    }
}
