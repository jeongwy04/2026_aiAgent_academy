package kr.firstlisten.app.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kr.firstlisten.core.AccountProvider
import kr.firstlisten.core.SyncAccount
import java.security.KeyStore
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@Serializable
data class SessionState(
    val baseUrl: String = "http://10.0.2.2:8000",
    val memberId: String? = null,
    val email: String? = null,
    val token: String? = null,
    val expiresAt: String? = null,
    val sessionId: String = "",
    val captureEnabled: Boolean = false,
    val needsLogin: Boolean = false,
) {
    val ownerKey: String? get() = memberId?.let { ownerKey(baseUrl, it) }
    val expired: Boolean get() = expiresAt?.let { runCatching { !Instant.parse(it).isAfter(Instant.now()) }.getOrDefault(true) } ?: true

    companion object {
        fun ownerKey(baseUrl: String, memberId: String): String = MessageDigest.getInstance("SHA-256")
            .digest("$baseUrl|$memberId".toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }
}

/** Token-bearing data stays in app-private storage, encrypted by an Android Keystore key. */
class SessionStore(context: Context) : AccountProvider {
    private val prefs = context.getSharedPreferences("firstlisten-session", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }
    private val mutable = MutableStateFlow(read())
    val state = mutable.asStateFlow()

    override fun currentAccount(): SyncAccount? {
        val s = mutable.value
        if (s.token == null || s.ownerKey == null || s.needsLogin || s.expired) return null
        return SyncAccount(s.ownerKey!!, s.baseUrl, s.token, s.sessionId)
    }

    @Synchronized
    fun signIn(baseUrl: String, memberId: String, email: String, token: String, expiresAt: String) {
        val old = mutable.value
        update(SessionState(baseUrl, memberId, email, token, expiresAt, UUID.randomUUID().toString(),
            captureEnabled = old.captureEnabled && old.ownerKey == SessionState.ownerKey(baseUrl, memberId)))
    }

    @Synchronized
    fun setCapture(enabled: Boolean) {
        update(mutable.value.copy(captureEnabled = enabled && mutable.value.memberId != null))
    }

    @Synchronized
    fun signOut() { update(SessionState(baseUrl = mutable.value.baseUrl)) }

    @Synchronized
    override fun requireLogin(account: SyncAccount) {
        if (mutable.value.sessionId == account.sessionId) update(mutable.value.copy(needsLogin = true))
    }

    private fun update(value: SessionState) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val payload = cipher.iv + cipher.doFinal(json.encodeToString(value).toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("payload", Base64.encodeToString(payload, Base64.NO_WRAP)).commit()) {
            "로그인 정보를 저장하지 못했습니다."
        }
        mutable.value = value
    }

    private fun read(): SessionState = runCatching {
        val encoded = prefs.getString("payload", null) ?: return SessionState()
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        }
        json.decodeFromString<SessionState>(String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8))
    }.getOrElse { SessionState() }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    companion object { private const val KEY_ALIAS = "firstlisten-session-v1" }
}
