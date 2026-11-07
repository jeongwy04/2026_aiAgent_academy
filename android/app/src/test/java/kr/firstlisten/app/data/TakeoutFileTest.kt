package kr.firstlisten.app.data

import android.app.Application
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadow.api.Shadow
import org.robolectric.shadows.ShadowContentResolver
import java.io.ByteArrayInputStream
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class TakeoutFileTest {
    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val resolver = Shadow.extract<ShadowContentResolver>(application.contentResolver)

    @Test fun `document URI is streamed into private cache without changing UTF8`() = runBlocking {
        val uri = Uri.parse("content://takeout/history.JSON")
        val bytes = """[{"title":"입춘"}]""".toByteArray()
        resolver.registerInputStream(uri, ByteArrayInputStream(bytes))
        val staged = stageTakeoutJson(application, uri)
        try {
            assertArrayEquals(bytes, staged.readBytes())
            assertEquals(application.cacheDir, staged.parentFile)
        } finally { staged.delete() }
    }

    @Test fun `non JSON documents and empty files fail before uploading and leave no temporary file`() = runBlocking {
        val before = application.cacheDir.listFiles()!!.toSet()
        try { stageTakeoutJson(application, Uri.parse("content://takeout/history.zip")); fail("must reject ZIP") }
        catch (error: IllegalArgumentException) { assertTrue(error.message!!.contains("JSON")) }
        val uri = Uri.parse("content://takeout/empty.json")
        resolver.registerInputStream(uri, ByteArrayInputStream(byteArrayOf()))
        try { stageTakeoutJson(application, uri); fail("must reject empty file") }
        catch (error: IllegalArgumentException) { assertTrue(error.message!!.contains("빈 파일")) }
        assertEquals(before, application.cacheDir.listFiles()!!.toSet())
    }

    @Test fun `copy enforces the byte limit even when the document size is unknown`() = runBlocking {
        val file = File.createTempFile("takeout-limit-", ".json", application.cacheDir)
        try {
            copyTakeoutJson(ByteArrayInputStream(ByteArray(8)), file, maxBytes = 8)
            assertEquals(8L, file.length())
            try { copyTakeoutJson(ByteArrayInputStream(ByteArray(9)), file, maxBytes = 8); fail("must enforce limit") }
            catch (error: IllegalArgumentException) { assertTrue(error.message!!.contains("100 MiB")) }
            assertEquals(0L, file.length())
        } finally { file.delete() }
    }
}
