package kr.firstlisten.app.ui

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class DisplayFormatsTest {
    @Test fun `unknown durations are never displayed as a measured zero`() {
        assertNotEquals(formatDuration(0), formatDuration(null))
        assertEquals("0초", formatDuration(0))
        assertEquals("2시간 15분 0초", formatDuration(8_100_000))
    }

    @Test fun `UTC timestamps display the correct Korean calendar date`() {
        assertEquals("2026.11.07 00:00", formatTimestamp("2026-11-06T15:00:00Z"))
    }

    @Test fun `dynamic statistics support nullable and fractional millisecond columns`() {
        assertEquals("정보 없음", statValue("total_ms", Json.parseToJsonElement("null")))
        assertEquals("31초", statValue("average_ms", Json.parseToJsonElement("31500.5")))
        assertEquals("입춘", statValue("title", Json.parseToJsonElement("\"입춘\"")))
    }

    @Test fun `server stats columns use Korean labels`() {
        assertEquals("청취 횟수", statLabel("play_count"))
        assertEquals("곡 수", statLabel("track_count"))
        assertEquals("요일", statLabel("weekday"))
        assertEquals("청취 시간", statLabel("sum_ms"))
        assertEquals("foo_bar", statLabel("foo_bar"))
    }

    @Test fun `period values are shown as Korean local dates without timezone shift`() {
        assertEquals("2026년 10월", statValue("month", Json.parseToJsonElement("\"2026-10-01T00:00:00\"")))
        assertEquals("11월 2일 주", statValue("week", Json.parseToJsonElement("\"2026-11-02T00:00:00\"")))
        assertEquals("2026년 11월 7일", statValue("day", Json.parseToJsonElement("\"2026-11-07\"")))
        assertEquals("2026.11.07 00:00", formatTimestamp("2026-11-06T15:00:00+00:00"))
        assertEquals("not-a-date", statValue("month", Json.parseToJsonElement("\"not-a-date\"")))
    }

    @Test fun `weekday hour and count values are readable`() {
        assertEquals("일요일", statValue("weekday", Json.parseToJsonElement("0")))
        assertEquals("일요일", statValue("weekday", Json.parseToJsonElement("7")))
        assertEquals("토요일", statValue("weekday", Json.parseToJsonElement("6")))
        assertEquals("13시", statValue("hour", Json.parseToJsonElement("13")))
        assertEquals("14회", statValue("play_count", Json.parseToJsonElement("14")))
        assertEquals("3개", statValue("track_count", Json.parseToJsonElement("3")))
        assertEquals("1", statValue("rank", Json.parseToJsonElement("1")))
    }
}
