package kr.firstlisten.app.data

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.io.InputStream

internal const val TAKEOUT_MAX_BYTES = 104_857_600L

/** Called on IO; stream into private temporary storage without loading the history into memory. */
internal suspend fun stageTakeoutJson(context: Context, uri: Uri): File {
    val resolver = context.contentResolver
    val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (column >= 0 && cursor.moveToFirst()) cursor.getString(column) else null
    } ?: uri.lastPathSegment.orEmpty()
    require(name.endsWith(".json", ignoreCase = true)) { "압축을 푼 Google Takeout JSON 파일을 선택해 주세요." }
    val file = File.createTempFile("takeout-", ".json", context.cacheDir)
    try {
        val input = resolver.openInputStream(uri) ?: error("파일을 열 수 없습니다. 다른 위치의 파일을 선택해 주세요.")
        input.use { copyTakeoutJson(it, file) }
        return file
    } catch (error: Throwable) {
        file.delete()
        throw error
    }
}

internal suspend fun copyTakeoutJson(input: InputStream, target: File, maxBytes: Long = TAKEOUT_MAX_BYTES) {
    target.outputStream().use { output ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        var total = 0L
        while (true) {
            currentCoroutineContext().ensureActive()
            val read = input.read(buffer)
            if (read < 0) break
            total += read
            require(total <= maxBytes) { "JSON 파일은 최대 100 MiB까지 가져올 수 있습니다." }
            output.write(buffer, 0, read)
        }
        require(total > 0) { "빈 파일입니다. Google Takeout JSON 파일을 선택해 주세요." }
    }
}
