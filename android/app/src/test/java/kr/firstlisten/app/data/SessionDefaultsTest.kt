package kr.firstlisten.app.data

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class SessionDefaultsTest {
    @Test fun `fresh installs point to the USB forwarded development server`() {
        val context = ApplicationProvider.getApplicationContext<Application>()
        context.getSharedPreferences("firstlisten-session", 0).edit().clear().commit()
        assertEquals("http://127.0.0.1:8000", SessionStore(context).state.value.baseUrl)
    }

    @Test fun `legacy sessions with omitted server retain their original account namespace`() {
        val legacy = Json.decodeFromString<SessionState>("""{"memberId":"alice"}""")
        assertEquals("http://10.0.2.2:8000", legacy.baseUrl)
        assertEquals(SessionState.ownerKey("http://10.0.2.2:8000", "alice"), legacy.ownerKey)
    }

    @Test fun `new USB and custom server addresses survive persistence without substitution`() {
        for (address in listOf("http://127.0.0.1:8000", "https://firstlisten.example")) {
            val state = SessionState(baseUrl = address, memberId = "alice")
            val restored = Json.decodeFromString<SessionState>(Json.encodeToString(state))
            assertEquals(state.baseUrl, restored.baseUrl)
            assertEquals(state.ownerKey, restored.ownerKey)
        }
    }
}
