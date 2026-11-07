package kr.firstlisten.app.network

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
import java.io.File

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

    @Test fun `library query encodes Korean spaces and ampersands and parses missing artists`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":"track-1","title":"입춘","artist":null,"album":null,"external_id":null}],"total":21,"limit":5,"offset":20}"""))
        val page = api.tracks(account, "  입춘 & 봄 / ?  ", limit = 5, offset = 20)
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("Bearer secret-token", request.getHeader("Authorization"))
        assertEquals("/api/v1/tracks", request.requestUrl!!.encodedPath)
        assertEquals("입춘 & 봄 / ?", request.requestUrl!!.queryParameter("q"))
        assertEquals("5", request.requestUrl!!.queryParameter("limit"))
        assertEquals("20", request.requestUrl!!.queryParameter("offset"))
        assertEquals(setOf("q", "limit", "offset"), request.requestUrl!!.queryParameterNames)
        assertNull(page.items.single().artist)
    }

    @Test fun `blank library query is omitted and long queries respect the server boundary`() = runBlocking {
        val empty = """{"items":[],"total":0,"limit":20,"offset":0}"""
        server.enqueue(MockResponse().setBody(empty))
        api.tracks(account, "  ")
        assertNull(server.takeRequest().requestUrl!!.queryParameter("q"))
        server.enqueue(MockResponse().setBody(empty))
        api.tracks(account, "가".repeat(301))
        assertEquals(300, server.takeRequest().requestUrl!!.queryParameter("q")!!.length)
    }

    @Test fun `Takeout stats keep unknown duration distinct from a measured zero`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"track":{"id":"track-1","title":"입춘","artist":null},"first_recorded_at":"2020-01-01T00:00:00Z","total_listened_ms":null,"event_count":2,"measured_event_count":0,"unknown_duration_event_count":2}"""))
        val stats = api.stats(account, "track-1")
        assertEquals("/api/v1/tracks/track-1/stats", server.takeRequest().path)
        assertNull(stats.track.artist)
        assertNull(stats.total_listened_ms)
        assertEquals(2, stats.unknown_duration_event_count)
    }

    @Test fun `chat keeps dynamic row columns and ignores server debug data`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"question":"통계","answer":"결과입니다.","status":"answered","metric":"stats","rows":[{"title":"입춘","total_ms":8100000},{"month":"2026-11","total_ms":null,"average_ms":31500.5}],"debug":{"sql_attempts":["private SQL"]}}"""))
        val reply = api.chat(account, "  " + "가".repeat(501) + "  ", "track-1")
        val request = server.takeRequest()
        assertEquals("/api/v1/chat", request.path)
        assertEquals("Bearer secret-token", request.getHeader("Authorization"))
        val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals(500, body.getValue("question").jsonPrimitive.content.length)
        assertEquals("track-1", body.getValue("track_id").jsonPrimitive.content)
        assertEquals("입춘", reply.rows[0].getValue("title").jsonPrimitive.content)
        assertEquals(JsonNull, reply.rows[1]["total_ms"])
        assertNull(reply.rows[1]["title"])
    }

    @Test fun `HTTP failures carry Retry-After seconds without changing status handling`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(429).addHeader("Retry-After", "17").setBody("""{"detail":"요청 한도"}"""))
        try { api.chat(account, "질문", null); fail("must be rate limited") }
        catch (error: HttpFailure) {
            assertEquals(429, error.code)
            assertEquals(17L, error.retryAfterSec)
        }
        server.enqueue(MockResponse().setResponseCode(429).addHeader("Retry-After", "invalid"))
        try { api.chat(account, "질문", null); fail("must be rate limited") }
        catch (error: HttpFailure) { assertNull(error.retryAfterSec) }
    }

    @Test fun `Takeout uploads an authenticated multipart JSON file and parses the import contract`() = runBlocking {
        val file = File.createTempFile("takeout-test-", ".json")
        try {
            val payload = """[{"title":"입춘 노래를 들었습니다.","time":"2020-01-01T00:00:00Z"}]"""
            file.writeText(payload)
            server.enqueue(MockResponse().setBody("""{"job_id":"job-1","status":"completed","parser_version":"1","json_sha256":"hash","total":10,"accepted":6,"inserted":4,"duplicates":2,"excluded":2,"review":1,"errors":1,"new_tracks":3,"distinct_tracks":4,"reasons":{}}"""))
            val result = api.importTakeout(account, file)
            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/imports", request.path)
            assertEquals("Bearer secret-token", request.getHeader("Authorization"))
            assertTrue(request.getHeader("Content-Type")!!.startsWith("multipart/form-data; boundary="))
            val body = request.body.readUtf8()
            assertTrue(body.contains("name=\"file\"; filename=\"takeout.json\""))
            assertTrue(body.contains("Content-Type: application/json"))
            assertTrue(body.contains(payload))
            assertEquals("completed", result.status)
            assertEquals(4, result.inserted)
            assertEquals(2, result.duplicates)
            assertEquals(1, result.review)
            assertEquals(1, result.errors)
        } finally { file.delete() }
    }

    @Test fun `Takeout redirects and size failures retain the upload error status`() = runBlocking {
        val file = File.createTempFile("takeout-test-", ".json").apply { writeText("[]") }
        val other = MockWebServer().apply { start() }
        try {
            server.enqueue(MockResponse().setResponseCode(307).addHeader("Location", other.url("/steal")))
            try { api.importTakeout(account, file); fail("must reject redirect") }
            catch (error: HttpFailure) { assertEquals(307, error.code) }
            assertEquals(0, other.requestCount)
            server.enqueue(MockResponse().setResponseCode(413).setBody("""{"detail":"파일 크기 초과"}"""))
            try { api.importTakeout(account, file); fail("must reject oversized upload") }
            catch (error: HttpFailure) { assertEquals(413, error.code) }
        } finally { file.delete(); other.shutdown() }
    }
}
