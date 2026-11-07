package kr.firstlisten.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kr.firstlisten.app.MainViewModel

@Composable
fun RecordScreen(model: MainViewModel, openPermissions: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val capture by model.capture.collectAsStateWithLifecycle()
    val sync by model.sync.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    val message by model.message.collectAsStateWithLifecycle()
    val allowed by model.permission.collectAsStateWithLifecycle()
    val recent by model.recent.collectAsStateWithLifecycle()
    val pending by model.pending.collectAsStateWithLifecycle()
    val rejected by model.rejected.collectAsStateWithLifecycle()
    var url by remember(session.baseUrl) { mutableStateOf(session.baseUrl) }
    var email by remember(session.email) { mutableStateOf(session.email.orEmpty()) }
    // Passwords deliberately do not survive Activity recreation or process death.
    var password by remember { mutableStateOf("") }

        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("FirstListen", style = MaterialTheme.typography.headlineLarge)
            Text("YouTube Music에서 관찰한 청취 기록을 모읍니다.")
            message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("계정", style = MaterialTheme.typography.titleLarge)
                    if (session.memberId == null || session.needsLogin || session.expired) {
                        if (session.memberId != null) Text("로그인이 만료되었습니다. 같은 계정으로 로그인하면 전송을 이어갑니다.")
                        OutlinedTextField(url, { url = it }, label = { Text("서버 주소") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(email, { email = it }, label = { Text("이메일") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(password, { password = it }, label = { Text("비밀번호") }, singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(enabled = !busy, onClick = {
                                model.authenticate(url, email, password, false)
                                password = ""
                            }) { Text("로그인") }
                            OutlinedButton(enabled = !busy, onClick = {
                                model.authenticate(url, email, password, true)
                                password = ""
                            }) { Text("회원가입") }
                        }
                    } else {
                        Text(session.email.orEmpty())
                        Text(session.baseUrl, style = MaterialTheme.typography.bodySmall)
                    }
                    if (session.memberId != null) TextButton(enabled = !busy, onClick = model::logout) { Text("로그아웃") }
                }
            }

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("자동 기록", style = MaterialTheme.typography.titleLarge)
                    Text(if (allowed) "알림 접근 허용됨" else "알림 접근 권한이 필요합니다.")
                    Text("허용 후 YouTube Music의 곡 정보와 재생 상태를 읽습니다.")
                    OutlinedButton(onClick = openPermissions) { Text("알림 접근 설정") }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("청취 기록 수집")
                        Switch(checked = session.captureEnabled, enabled = session.memberId != null && !busy,
                            onCheckedChange = model::setCapture)
                    }
                    Text(capture.message)
                    capture.track?.let { Text(it); Text("관찰한 시간 ${duration(capture.listenedMs)}") }
                    Text("30초 이상 들은 기록을 전송합니다. 수집이 중단된 구간은 추정하지 않습니다.",
                        style = MaterialTheme.typography.bodySmall)
                }
            }

            if (session.memberId != null) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("동기화", style = MaterialTheme.typography.titleLarge)
                        Text("전송 대기 ${pending}개 · 보류 ${rejected}개")
                        Text(sync)
                        Button(enabled = !busy, onClick = { model.syncNow() }) { Text("지금 동기화") }
                        if (rejected > 0) TextButton(enabled = !busy, onClick = { model.syncNow(true) }) { Text("보류 기록 다시 시도") }
                    }
                }
                Text("최근 기기 기록", style = MaterialTheme.typography.titleLarge)
                val ownedRecent = recent.filter { it.ownerKey == session.ownerKey }
                if (ownedRecent.isEmpty()) Text("자동 기록을 켜고 YouTube Music을 재생해 주세요.")
                ownedRecent.forEach { event ->
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("${event.title} · ${event.artist}")
                        Text("${duration(event.listenedMs)} · ${when {
                            event.error != null -> "전송 보류"
                            event.listenedMs < 30_000 -> "30초 미만"
                            event.localVersion > event.uploadedVersion -> "전송 대기"
                            else -> "전송 완료"
                        }}", style = MaterialTheme.typography.bodySmall)
                        event.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                        HorizontalDivider()
                    }
                }
            }
        }
}

private fun duration(ms: Long): String = "${ms / 60_000}분 ${(ms / 1_000) % 60}초"
