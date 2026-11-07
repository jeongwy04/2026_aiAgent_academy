package kr.firstlisten.app.network

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kr.firstlisten.core.HttpFailure
import kr.firstlisten.core.ListenSnapshot
import kr.firstlisten.core.SyncAccount
import kr.firstlisten.core.SyncAck
import kr.firstlisten.core.SyncTransport
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

@Serializable private data class Credentials(val email: String, val password: String)
@Serializable data class TokenResponse(val access_token: String, val expires_at: String)
@Serializable data class MemberResponse(val id: String, val email: String)
@Serializable data class TrackOut(
    val id: String,
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    val external_id: String? = null,
)
@Serializable data class TrackPage(val items: List<TrackOut>, val total: Int, val limit: Int, val offset: Int)
@Serializable data class TrackStats(
    val track: TrackOut,
    val first_recorded_at: String? = null,
    val total_listened_ms: Long? = null,
    val event_count: Int,
    val measured_event_count: Int = 0,
    val unknown_duration_event_count: Int = 0,
)
@Serializable private data class ChatBody(val question: String, val track_id: String? = null)
@Serializable data class ChatReply(
    val question: String,
    val answer: String,
    val status: String,
    val metric: String? = null,
    val track: TrackOut? = null,
    val candidates: List<TrackOut> = emptyList(),
    val first_recorded_at: String? = null,
    val total_listened_ms: Long? = null,
    val rows: List<JsonObject> = emptyList(),
)
@Serializable private data class TrackDto(val title: String, val artist: String, val album: String?, val external_id: String?)
@Serializable private data class EventDto(val event_id: String, val track: TrackDto, val observed_at: String, val listened_ms: Long)
@Serializable private data class SyncBody(val events: List<EventDto>)
@Serializable private data class AckDto(val event_id: String, val status: String, val track_id: String? = null, val listened_ms: Long? = null)
@Serializable private data class SyncResponse(val results: List<AckDto>)

class FirstListenApi(
    private val allowHttp: Boolean,
    private val client: OkHttpClient = OkHttpClient.Builder()
        // Stats chat runs LLM Text-to-SQL with retries (often 10–30s); OkHttp's default 10s read timeout cut it off.
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).callTimeout(60, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build(),
) : SyncTransport {
    private val json = Json { ignoreUnknownKeys = true }

    fun normalizeBaseUrl(input: String): String {
        val url = input.trim().toHttpUrl()
        require(url.isHttps || allowHttp) { "HTTPS 서버 주소를 입력해 주세요." }
        require(url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null) {
            "서버 주소에는 계정 정보, 쿼리, 프래그먼트를 넣을 수 없습니다."
        }
        return url.toString().trimEnd('/')
    }

    suspend fun login(baseUrl: String, email: String, password: String): TokenResponse =
        decode(request(baseUrl, "/api/v1/auth/login", body = json.encodeToString(Credentials(email, password))))

    suspend fun register(baseUrl: String, email: String, password: String) {
        request(baseUrl, "/api/v1/members", body = json.encodeToString(Credentials(email, password)))
    }

    suspend fun me(baseUrl: String, token: String): MemberResponse = decode(request(baseUrl, "/api/v1/members/me", token))
    suspend fun logout(account: SyncAccount) { request(account.baseUrl, "/api/v1/auth/logout", account.token, "") }

    suspend fun tracks(account: SyncAccount, q: String?, limit: Int = 20, offset: Int = 0): TrackPage =
        decode(request(account.baseUrl, "/api/v1/tracks", account.token, query = buildMap {
            q?.trim()?.takeIf { it.isNotEmpty() }?.let { put("q", it.take(300)) }
            put("limit", "$limit")
            put("offset", "$offset")
        }))

    suspend fun stats(account: SyncAccount, trackId: String): TrackStats =
        decode(request(account.baseUrl, "/api/v1/tracks/$trackId/stats", account.token))

    suspend fun chat(account: SyncAccount, question: String, trackId: String?): ChatReply =
        decode(request(account.baseUrl, "/api/v1/chat", account.token,
            json.encodeToString(ChatBody(question.trim().take(500), trackId))))

    override suspend fun send(account: SyncAccount, events: List<ListenSnapshot>): List<SyncAck> {
        require(events.size in 1..100 && events.all { it.ownerKey == account.ownerKey })
        val body = SyncBody(events.map { EventDto(it.eventId,
            TrackDto(it.track.title, it.track.artist, it.track.album, it.track.externalId), it.observedAt, it.listenedMs) })
        return decode<SyncResponse>(request(account.baseUrl, "/api/v1/listens/sync", account.token, json.encodeToString(body)))
            .results.map { SyncAck(it.event_id, it.status, it.track_id, it.listened_ms) }
    }

    private inline fun <reified T> decode(body: String): T = try { json.decodeFromString(body) }
        catch (error: SerializationException) { throw IOException("서버 응답 형식을 확인할 수 없습니다.", error) }

    private suspend fun request(
        baseUrl: String, path: String, token: String? = null, body: String? = null,
        query: Map<String, String> = emptyMap(),
    ): String {
        val url = (normalizeBaseUrl(baseUrl) + path).toHttpUrl().newBuilder()
            .apply { query.forEach { (key, value) -> addQueryParameter(key, value) } }.build()
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        token?.let { builder.header("Authorization", "Bearer $it") }
        if (body != null) builder.post(body.toRequestBody("application/json; charset=utf-8".toMediaType()))
        return client.newCall(builder.build()).await().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val node = json.parseToJsonElement(text).jsonObject["detail"]
                    node?.jsonPrimitive?.content
                        ?: node?.jsonArray?.firstOrNull()?.jsonObject?.get("msg")?.jsonPrimitive?.content
                }.getOrNull()
                throw HttpFailure(response.code, detail ?: "서버 요청 실패 (${response.code})",
                    response.header("Retry-After")?.toLongOrNull())
            }
            text
        }
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { cancel() }
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { if (!continuation.isCancelled) continuation.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) {
                continuation.resume(response) { _, value, _ -> value.close() }
            }
        })
    }
}
