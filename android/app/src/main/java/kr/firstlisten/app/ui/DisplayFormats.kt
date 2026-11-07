package kr.firstlisten.app.ui

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun formatDuration(ms: Long?): String {
    if (ms == null) return "확인할 수 없음"
    val seconds = ms.coerceAtLeast(0) / 1_000
    return buildList {
        if (seconds >= 3_600) add("${seconds / 3_600}시간")
        if (seconds >= 60) add("${seconds / 60 % 60}분")
        add("${seconds % 60}초")
    }.joinToString(" ")
}

fun formatTimestamp(value: String?): String {
    if (value == null) return "기록 없음"
    return runCatching {
        DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm", Locale.KOREAN)
            .withZone(ZoneId.of("Asia/Seoul")).format(Instant.parse(value))
    }.getOrDefault(value)
}

internal fun statLabel(key: String): String = when (key) {
    "title" -> "곡명"
    "artist" -> "가수"
    "album" -> "앨범"
    "month" -> "월"
    "year" -> "연도"
    "total_ms", "total_listened_ms", "listened_ms" -> "청취 시간"
    "first_recorded_at", "first_listened_at" -> "최초 기록"
    "event_count", "listen_count", "count" -> "기록 수"
    else -> key
}

internal fun statValue(key: String, value: JsonElement): String {
    val numeric = (value as? JsonPrimitive)?.doubleOrNull
    return when {
        value is JsonNull -> "정보 없음"
        value is JsonPrimitive && key.endsWith("_ms") && numeric != null && numeric.isFinite() && numeric >= 0 ->
            formatDuration(value.longOrNull ?: numeric.toLong())
        value is JsonPrimitive && key.endsWith("_at") && value.isString -> formatTimestamp(value.content)
        value is JsonPrimitive -> value.content
        else -> value.toString()
    }
}
