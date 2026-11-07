package kr.firstlisten.app

import android.app.Application
import android.net.Uri
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
import kr.firstlisten.app.network.FirstListenApi
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
import java.io.File
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class TakeoutImportViewModelTest {
    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val server = MockWebServer().apply { start() }
    private val api = FirstListenApi(allowHttp = true)
    private val alice = SyncAccount("alice", server.url("/").toString().trimEnd('/'), "token-a", "login-a")
    private val bob = alice.copy(ownerKey = "bob", token = "token-b", sessionId = "login-b")
    private val accounts = Accounts(alice)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
    private val files = mutableListOf<File>()
    private val uri = Uri.parse("content://documents/history.json")
    private class Accounts(initial: SyncAccount?) : AccountProvider {
        val changes = MutableStateFlow(initial)
        @Volatile var expired = false
        override fun currentAccount() = changes.value.takeUnless { expired }
        override fun requireLogin(account: SyncAccount) { if (changes.value == account) changes.value = null }
    }
    private fun model() = TakeoutImportViewModel(application, api, accounts, accounts.changes, {
        File.createTempFile("import-test-", ".json", application.cacheDir).apply {
            writeText("[]")
            synchronized(files) { files.add(this) }
        }
    }, scope)
    private val summary = """{"job_id":"job","status":"completed","total":3,"accepted":2,"inserted":1,"duplicates":1,"excluded":1,"review":0,"errors":0,"new_tracks":1,"distinct_tracks":1}"""
    private suspend fun TakeoutImportViewModel.await(predicate: (TakeoutImportState) -> Boolean) =
        withTimeout(5_000) { state.first(predicate) }
    @After fun cleanup() { scope.cancel(); server.shutdown(); files.forEach { it.delete() } }

    @Test fun `success shows counts removes the private file and prevents overlapping uploads`() = runBlocking {
        server.enqueue(MockResponse().setBody(summary).setBodyDelay(300, TimeUnit.MILLISECONDS))
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        assertTrue(vm.state.value.busy)
        assertFalse(vm.beginSelection())
        vm.importSelected(uri)
        val result = vm.await { it.result != null }
        assertEquals(1, result.result!!.inserted)
        assertEquals(1, result.result!!.duplicates)
        assertFalse(result.busy)
        assertFalse(files.single().exists())
        assertEquals(1, server.requestCount)
    }

    @Test fun `cancelling the picker does not prepare a file or send a request`() {
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(null)
        assertFalse(vm.state.value.busy)
        assertTrue(files.isEmpty())
        assertEquals(0, server.requestCount)
    }

    @Test fun `an old picker result cannot import into a different login`() {
        val vm = model()
        assertTrue(vm.beginSelection())
        accounts.changes.value = bob
        vm.importSelected(uri)
        assertEquals("bob", vm.state.value.ownerKey)
        assertTrue(files.isEmpty())
        assertEquals(0, server.requestCount)
        accounts.changes.value = null
        assertFalse(vm.beginSelection())
    }

    @Test fun `account change cancels in flight upload deletes its file and clears its result`() = runBlocking {
        server.enqueue(MockResponse().setBody(summary).setBodyDelay(500, TimeUnit.MILLISECONDS))
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        assertNotNull(server.takeRequest(3, TimeUnit.SECONDS))
        accounts.changes.value = bob
        vm.await { it.ownerKey == "bob" && !it.busy }
        withTimeout(5_000) { while (files.any { it.exists() }) delay(10) }
        delay(600)
        assertNull(vm.state.value.result)
        assertNull(vm.state.value.error)
    }

    @Test fun `rate limits show retry time and allow a manual retry with file cleanup`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(429).addHeader("Retry-After", "17"))
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        assertTrue(vm.await { it.error != null }.error!!.contains("17초"))
        assertFalse(files.single().exists())
        server.enqueue(MockResponse().setBody(summary))
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        vm.await { it.result != null }
        assertTrue(files.none { it.exists() })
    }

    @Test fun `unauthorized upload requires login and drops previous account data`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        vm.await { it.ownerKey == null }
        assertNull(accounts.currentAccount())
        assertFalse(vm.beginSelection())
        assertTrue(files.none { it.exists() })
    }

    @Test fun `local expiry while the picker is open requires login without uploading`() {
        val vm = model()
        assertTrue(vm.beginSelection())
        accounts.expired = true
        vm.importSelected(uri)
        assertNull(vm.state.value.ownerKey)
        assertNull(accounts.changes.value)
        assertEquals(0, server.requestCount)
        assertTrue(files.isEmpty())
    }

    @Test fun `local expiry during upload does not leave a permanently busy screen`() = runBlocking {
        server.enqueue(MockResponse().setBody(summary).setBodyDelay(300, TimeUnit.MILLISECONDS))
        val vm = model()
        assertTrue(vm.beginSelection())
        vm.importSelected(uri)
        assertNotNull(server.takeRequest(3, TimeUnit.SECONDS))
        accounts.expired = true
        vm.await { it.ownerKey == null && !it.busy }
        assertNull(accounts.changes.value)
        assertTrue(files.none { it.exists() })
    }
}
