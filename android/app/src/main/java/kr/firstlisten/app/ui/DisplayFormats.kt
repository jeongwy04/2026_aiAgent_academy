package kr.firstlisten.app.ui

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val SEOUL = ZoneId.of("Asia/Seoul")
private val PERIOD_KEYS = setOf("month", "week", "day")
private val COUNT_KEYS = setOf("n", "cnt", "count")

fun formatDuration(ms: Long?): String {
    if (ms == null) return "확인할 수 없음"
    val seconds = ms.coerceAtLeast(0) / 1_000
    return buildList {
        if (seconds >= 3_600) add("${seconds / 3_600}시간")
        if (seconds >= 60) add("${seconds / 60 % 60}분")
        add("${seconds % 60}초")
    }.joinToString(" ")
}

/** 시간대가 있는 시각(UTC 등)을 한국 시간으로. "+00:00" 오프셋 형식도 읽는다. */
fun formatTimestamp(value: String?): String {
    if (value == null) return "기록 없음"
    val instant = runCatching { OffsetDateTime.parse(value).toInstant() }.getOrNull()
        ?: runCatching { Instant.parse(value) }.getOrNull()
        ?: return value
    return DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm", Locale.KOREAN).withZone(SEOUL).format(instant)
}

/**
 * 서버 통계의 month/week/day 값. SQL이 observed_at AT TIME ZONE 'Asia/Seoul'로 이미 한국 날짜로 잘라
 * 시간대 없는 값("2026-10-01T00:00:00")으로 보내므로 변환하지 않는다 (서버 response.value()와 같은 표시).
 */
internal fun formatPeriod(key: String, raw: String): String {
    val date = runCatching { LocalDateTime.parse(raw).toLocalDate() }.getOrNull()
        ?: runCatching { LocalDate.parse(raw) }.getOrNull()
        ?: runCatching { OffsetDateTime.parse(raw).atZoneSameInstant(SEOUL).toLocalDate() }.getOrNull()
        ?: return raw
    return when (key) {
        "month" -> "${date.year}년 ${date.monthValue}월"
        "week" -> "${date.monthValue}월 ${date.dayOfMonth}일 주"
        else -> "${date.year}년 ${date.monthValue}월 ${date.dayOfMonth}일"
    }
}

/** 서버 Text-to-SQL 결과 열 이름 → 한국어. 서버 SQL_PROMPT의 열 이름 목록·response.LABELS와 맞춘다. */
internal fun statLabel(key: String): String = when (key) {
    "title" -> "곡명"
    "artist" -> "가수"
    "album" -> "앨범"
    "total_ms", "total_listened_ms", "listened_ms" -> "청취 시간"
    "play_count" -> "청취 횟수"
    "track_count" -> "곡 수"
    "artist_count" -> "가수 수"
    "unknown_count" -> "시간 미확인"
    "first_at", "first_recorded_at", "first_listened_at" -> "처음 기록"
    "last_at" -> "마지막 기록"
    "year" -> "연도"
    "month" -> "월"
    "week" -> "주"
    "day" -> "날짜"
    "hour" -> "시"
    "weekday" -> "요일"
    "rank" -> "순위"
    "event_count", "listen_count", "count", "n", "cnt" -> "개수"
    else -> when {
        key.endsWith("_ms") -> "청취 시간"
        key.endsWith("_count") -> "개수"
        else -> key  // 모르는 이름은 숨기지 않는다
    }
}

internal fun statValue(key: String, value: JsonElement): String {
    if (value is JsonNull) return "정보 없음"
    val primitive = value as? JsonPrimitive ?: return value.toString()
    val numeric = primitive.doubleOrNull?.takeIf { it.isFinite() }
    return when {
        key.endsWith("_ms") && numeric != null && numeric >= 0 -> formatDuration(primitive.longOrNull ?: numeric.toLong())
        primitive.isString && key in PERIOD_KEYS -> formatPeriod(key, primitive.content)
        primitive.isString && key.endsWith("_at") -> formatTimestamp(primitive.content)
        key == "weekday" && numeric != null -> "일월화수목금토"[numeric.toInt().mod(7)] + "요일"  // DOW 0=일, ISODOW 7=일
        key == "hour" && numeric != null -> "${numeric.toInt()}시"
        (key.endsWith("_count") || key in COUNT_KEYS) && numeric != null ->
            "${numeric.toLong()}${if (key == "play_count") "회" else "개"}"
        else -> primitive.content
    }
}
