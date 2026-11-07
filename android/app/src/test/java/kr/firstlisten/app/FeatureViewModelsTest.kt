package kr.firstlisten.app

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kr.firstlisten.app.network.FirstListenApi
import kr.firstlisten.app.network.TrackOut
import kr.firstlisten.core.AccountProvider
import kr.firstlisten.core.SyncAccount
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class FeatureViewModelsTest {
    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val server = MockWebServer().apply { start() }
    private val api = FirstListenApi(allowHttp = true)
    private val alice = SyncAccount("alice", server.url("/").toString().trimEnd('/'), "token-a", "login-a")
    private val bob = alice.copy(ownerKey = "bob", token = "token-b", sessionId = "login-b")
    private val accounts = Accounts(alice)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
    private class Accounts(initial: SyncAccount?) : AccountProvider {
        val changes = MutableStateFlow(initial)
        override fun currentAccount() = changes.value
        override fun requireLogin(account: SyncAccount) { if (changes.value == account) changes.value = null }
    }

    @After fun cleanup() { scope.cancel(); server.shutdown() }
    private fun library() = LibraryViewModel(application, api, accounts, accounts.changes, scope)
    private fun chat() = ChatViewModel(application, api, accounts, accounts.changes, scope) { System.nanoTime() / 1_000_000 }
    private fun track(id: String, title: String = id) = TrackOut(id, title)
    private fun page(id: String, total: Int = 1, offset: Int = 0) =
        """{"items":[{"id":"$id","title":"$id","artist":null}],"total":$total,"limit":1,"offset":$offset}"""
    private fun answer(question: String = "질문", trackId: String = "track-1") =
        """{"question":"$question","answer":"기록된 답변","status":"answered","track":{"id":"$trackId","title":"$trackId","artist":null},"total_listened_ms":31000}"""
    private suspend fun LibraryViewModel.await(predicate: (LibraryUiState) -> Boolean) = withTimeout(5_000) { state.first(predicate) }
    private suspend fun ChatViewModel.await(predicate: (ChatUiState) -> Boolean) = withTimeout(5_000) { state.first(predicate) }

    @Test fun `library paginates and opens Takeout details without inventing a duration`() = runBlocking {
        server.enqueue(MockResponse().setBody(page("first", total = 2)))
        val vm = library()
        val first = vm.await { it.tracks.size == 1 && !it.loading }
        assertNull(first.tracks.single().artist)
        assertEquals("Bearer token-a", server.takeRequest(3, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        server.enqueue(MockResponse().setBody(page("second", total = 2, offset = 1)))
        vm.loadMore()
        vm.await { it.tracks.size == 2 }
        assertEquals("1", server.takeRequest(3, TimeUnit.SECONDS)!!.requestUrl!!.queryParameter("offset"))
        server.enqueue(MockResponse().setBody("""{"track":{"id":"first","title":"first","artist":null},"total_listened_ms":null,"event_count":2,"unknown_duration_event_count":2}"""))
        vm.selectTrack(first.tracks.single())
        val detail = vm.await { it.stats != null }
        assertNull(detail.stats!!.total_listened_ms)
        assertEquals(2, detail.stats!!.unknown_duration_event_count)
        vm.closeDetail()
        assertNull(vm.state.value.selectedTrack)
        assertEquals(2, vm.state.value.tracks.size)
    }

    @Test fun `new search cancels a slow previous response and keeps its encoded query`() = runBlocking {
        server.enqueue(MockResponse().setBody(page("initial")))
        val vm = library()
        vm.await { !it.loading && it.tracks.isNotEmpty() }
        server.takeRequest(3, TimeUnit.SECONDS)
        server.enqueue(MockResponse().setBody(page("old")).setBodyDelay(1, TimeUnit.SECONDS))
        vm.setQuery("old")
        server.takeRequest(3, TimeUnit.SECONDS)
        server.enqueue(MockResponse().setBody(page("new")))
        vm.setQuery("입춘 & 봄")
        vm.await { !it.loading && it.tracks.singleOrNull()?.id == "new" }
        assertEquals("입춘 & 봄", server.takeRequest(3, TimeUnit.SECONDS)!!.requestUrl!!.queryParameter("q"))
        delay(1_100)
        assertEquals("new", vm.state.value.tracks.single().id)
    }

    @Test fun `account change clears library and drops old in-flight results`() = runBlocking {
        server.enqueue(MockResponse().setBody(page("alice-track")).setBodyDelay(1, TimeUnit.SECONDS))
        val vm = library()
        server.takeRequest(3, TimeUnit.SECONDS)
        server.enqueue(MockResponse().setBody(page("bob-track")))
        accounts.changes.value = bob
        vm.await { it.ownerKey == "bob" && it.tracks.singleOrNull()?.id == "bob-track" }
        assertEquals("Bearer token-b", server.takeRequest(3, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        delay(1_100)
        assertEquals(listOf("bob-track"), vm.state.value.tracks.map { it.id })
    }

    @Test fun `unauthorized library request requires login and clears visible data`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"expired"}"""))
        val vm = library()
        withTimeout(5_000) { accounts.changes.first { it == null } }
        assertNull(vm.state.value.ownerKey)
        assertTrue(vm.state.value.tracks.isEmpty())
    }

    @Test fun `ambiguous reply can be answered again using the selected candidate ID`() = runBlocking {
        val vm = chat()
        server.enqueue(MockResponse().setBody("""{"question":"입춘 언제부터?","answer":"곡을 선택해 주세요.","status":"ambiguous","candidates":[{"id":"chosen","title":"입춘","artist":null}]}"""))
        vm.setQuestion("입춘 언제부터?")
        vm.send()
        val ambiguous = vm.await { it.messages.lastOrNull()?.reply?.status == "ambiguous" }
        server.takeRequest(3, TimeUnit.SECONDS)
        server.enqueue(MockResponse().setBody(answer(trackId = "chosen")))
        val message = ambiguous.messages.single()
        vm.chooseCandidate(message.id, message.reply!!.candidates.single())
        val answered = vm.await { it.messages.size == 2 && !it.sending }
        val body = Json.parseToJsonElement(server.takeRequest(3, TimeUnit.SECONDS)!!.body.readUtf8()).jsonObject
        assertEquals("chosen", body.getValue("track_id").jsonPrimitive.content)
        assertEquals("answered", answered.messages.last().reply!!.status)
        assertEquals("chosen", answered.selectedTrack!!.id)
    }

    @Test fun `needs-track reply can retry the original question after a library selection`() = runBlocking {
        val vm = chat()
        server.enqueue(MockResponse().setBody("""{"question":"이 노래 언제부터?","answer":"곡을 선택해 주세요.","status":"needs_track"}"""))
        vm.ask("이 노래 언제부터?")
        val needsTrack = vm.await { it.messages.lastOrNull()?.reply?.status == "needs_track" }
        server.takeRequest(3, TimeUnit.SECONDS)
        vm.selectTrack(track("picked"))
        server.enqueue(MockResponse().setBody(answer(trackId = "picked")))
        vm.retry(needsTrack.messages.single().id)
        vm.await { it.messages.size == 2 && !it.sending }
        val body = Json.parseToJsonElement(server.takeRequest(3, TimeUnit.SECONDS)!!.body.readUtf8()).jsonObject
        assertEquals("picked", body.getValue("track_id").jsonPrimitive.content)
        assertEquals("이 노래 언제부터?", body.getValue("question").jsonPrimitive.content)
    }

    @Test fun `rate limit blocks new requests until Retry-After expires then supports retry`() = runBlocking {
        val vm = chat()
        server.enqueue(MockResponse().setResponseCode(429).addHeader("Retry-After", "2").setBody("""{"detail":"limited"}"""))
        vm.ask("총 청취 시간")
        val limited = vm.await { it.retryAfterSec > 0 }
        vm.ask("too soon")
        assertEquals(1, server.requestCount)
        vm.await { it.retryAfterSec == 0L }
        server.enqueue(MockResponse().setBody(answer()))
        vm.retry(limited.messages.single().id)
        vm.await { it.messages.size == 2 && it.messages.last().reply != null }
        assertEquals(2, server.requestCount)
    }

    @Test fun `account switch clears chat history and prevents old answers from reappearing`() = runBlocking {
        val vm = chat()
        vm.selectTrack(track("alice-track"))
        server.enqueue(MockResponse().setBody(answer(trackId = "alice-track")).setBodyDelay(1, TimeUnit.SECONDS))
        vm.ask("Alice question")
        server.takeRequest(3, TimeUnit.SECONDS)
        accounts.changes.value = bob
        assertTrue(vm.state.value.messages.isEmpty())
        assertNull(vm.state.value.selectedTrack)
        server.enqueue(MockResponse().setBody(answer(trackId = "bob-track")))
        vm.ask("Bob question")
        vm.await { !it.sending && it.messages.lastOrNull()?.reply != null }
        assertEquals("Bearer token-b", server.takeRequest(3, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        delay(1_100)
        assertEquals("Bob question", vm.state.value.messages.single().question)
        assertEquals("bob-track", vm.state.value.selectedTrack!!.id)
    }

    @Test fun `repeat send presses do not create concurrent chat requests`() = runBlocking {
        val vm = chat()
        server.enqueue(MockResponse().setBody(answer()).setBodyDelay(200, TimeUnit.MILLISECONDS))
        vm.ask("first")
        vm.ask("second")
        vm.await { !it.sending && it.messages.lastOrNull()?.reply != null }
        assertEquals(1, server.requestCount)
        assertEquals(1, vm.state.value.messages.size)
    }
}
