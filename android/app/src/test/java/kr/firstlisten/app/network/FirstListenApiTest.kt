package kr.firstlisten.app.network

import kotlinx.coroutines.runBlocking
import kr.firstlisten.core.HttpFailure
import kr.firstlisten.core.ListenSnapshot
import kr.firstlisten.core.SyncAccount
import kr.firstlisten.core.TrackMetadata
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class FirstListenApiTest {
    private val server = MockWebServer().apply { start() }
    private val api = FirstListenApi(allowHttp = true)
    private val account = SyncAccount("alice", server.url("/").toString().trimEnd('/'), "secret-token", "login")
    private val event = ListenSnapshot("alice", "3c473c97-0a37-4d64-99be-18574b1cec08",
        TrackMetadata("입춘", "한로로"), "2026-11-07T00:00:00Z", 31_000)
    @After fun cleanup() { server.shutdown() }

    @Test fun `sync serializes the existing FastAPI contract without local owner fields`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"results":[{"event_id":"${event.eventId}","status":"accepted","track_id":"track","listened_ms":31000}]}"""))
        val ack = api.send(account, listOf(event)).single()
        val request = server.takeRequest()
        assertEquals("/api/v1/listens/sync", request.path)
        assertEquals("Bearer secret-token", request.getHeader("Authorization"))
        val body = request.body.readUtf8()
        assertTrue(body.contains("\"listened_ms\":31000"))
        assertTrue(body.contains("\"observed_at\""))
        assertFalse(body.contains("ownerKey"))
        assertFalse(body.contains("version"))
        assertEquals(31_000L, ack.listenedMs)
    }

    @Test fun `login preserves password whitespace`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"access_token":"token","expires_at":"2026-12-01T00:00:00Z"}"""))
        api.login(account.baseUrl, "user@example.com", "  password  ")
        assertTrue(server.takeRequest().body.readUtf8().contains("\"password\":\"  password  \""))
    }

    @Test fun `redirects never forward a bearer token to another host`() = runBlocking {
        val other = MockWebServer().apply { start() }
        try {
            server.enqueue(MockResponse().setResponseCode(307).addHeader("Location", other.url("/steal")))
            try { api.send(account, listOf(event)); fail("redirect must fail") }
            catch (error: HttpFailure) { assertEquals(307, error.code) }
            assertEquals(0, other.requestCount)
        } finally { other.shutdown() }
    }

    @Test fun `malformed responses remain retryable and HTTP errors retain status`() = runBlocking {
        server.enqueue(MockResponse().setBody("not json"))
        try { api.send(account, listOf(event)); fail("must reject malformed response") }
        catch (_: IOException) { }
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"로그인 필요"}"""))
        try { api.send(account, listOf(event)); fail("must reject expired token") }
        catch (error: HttpFailure) { assertEquals(401, error.code) }
    }

    @Test fun `release configuration rejects cleartext and embedded credentials`() {
        val releaseApi = FirstListenApi(allowHttp = false)
        assertThrows(IllegalArgumentException::class.java) { releaseApi.normalizeBaseUrl(account.baseUrl) }
        assertThrows(IllegalArgumentException::class.java) { api.normalizeBaseUrl("https://user:password@example.com") }
        assertThrows(IllegalArgumentException::class.java) { api.normalizeBaseUrl("https://example.com?token=secret") }
    }
}
