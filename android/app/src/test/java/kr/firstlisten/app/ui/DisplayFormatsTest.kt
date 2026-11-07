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
}
