package kr.firstlisten.app.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.JsonObject
import kr.firstlisten.app.ChatMessage
import kr.firstlisten.app.ChatUiState
import kr.firstlisten.app.network.TrackOut

@Composable
fun ChatScreen(
    state: ChatUiState,
    onQuestion: (String) -> Unit,
    onSend: () -> Unit,
    onAsk: (String) -> Unit,
    onClearTrack: () -> Unit,
    onChooseTrack: () -> Unit,
    onCandidate: (String, TrackOut) -> Unit,
    onRetry: (String) -> Unit,
) {
    val list = rememberLazyListState()
    val canSend = !state.sending && state.retryAfterSec == 0L
    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) list.animateScrollToItem(state.messages.lastIndex)
    }
    Column(Modifier.fillMaxSize().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("질문", style = MaterialTheme.typography.headlineLarge)
        Text("내 청취 기록에 대해 물어보세요.")
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                state.selectedTrack?.let { track ->
                    Text("대화 중인 곡 · ${track.title}", style = MaterialTheme.typography.titleSmall)
                    Text(track.artist ?: "가수 정보 없음", style = MaterialTheme.typography.bodySmall)
                    Text("'이 노래', '그 노래'로 물으면 이 곡 기준으로 답합니다.", style = MaterialTheme.typography.bodySmall)
                } ?: Text("곡명을 질문에 쓰거나 내 곡에서 선택하세요.")
                Row {
                    TextButton(onClick = onChooseTrack) { Text("내 곡에서 선택") }
                    if (state.selectedTrack != null) TextButton(onClick = onClearTrack, enabled = !state.sending) { Text("선택 해제") }
                }
            }
        }
        LazyColumn(state = list, modifier = Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (state.messages.isEmpty()) item {
                Text("예: 입춘 언제부터 들었어?\n이번 달 가장 많이 들은 곡은?", style = MaterialTheme.typography.bodyMedium)
            }
            items(state.messages, key = ChatMessage::id) { message ->
                ChatExchange(message, state, canSend, onCandidate, onRetry, onChooseTrack)
            }
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (state.retryAfterSec > 0) Text("${state.retryAfterSec}초 후 다시 질문할 수 있습니다.", color = MaterialTheme.colorScheme.primary)
        if (state.selectedTrack != null) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { onAsk("이 노래 언제부터 들었어?") }, enabled = canSend) { Text("최초 기록일") }
            OutlinedButton(onClick = { onAsk("이 노래 총 재생 시간이 얼마야?") }, enabled = canSend) { Text("청취 시간") }
        }
        OutlinedTextField(state.question, onQuestion, label = { Text("질문 입력") },
            supportingText = { Text("${state.question.length}/500") }, minLines = 1, maxLines = 3, modifier = Modifier.fillMaxWidth())
        Button(onClick = onSend, enabled = canSend && state.question.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
            Text(if (state.sending) "답변을 기다리는 중" else "질문 보내기")
        }
    }
}

@Composable
private fun ChatExchange(
    message: ChatMessage,
    state: ChatUiState,
    canSend: Boolean,
    onCandidate: (String, TrackOut) -> Unit,
    onRetry: (String) -> Unit,
    onChooseTrack: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), modifier = Modifier.fillMaxWidth()) {
            Text(message.question, Modifier.padding(14.dp))
        }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (message.pending) { CircularProgressIndicator(); Text("기록을 확인하고 있습니다.") }
                message.error?.let {
                    Text(it, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = { onRetry(message.id) }, enabled = canSend) { Text("다시 질문") }
                }
                message.reply?.let { reply ->
                    SelectionContainer { Text(reply.answer) }
                    when (reply.status) {
                        "ambiguous" -> {
                            Text("질문할 곡을 골라 주세요.", style = MaterialTheme.typography.labelLarge)
                            reply.candidates.forEach { candidate ->
                                OutlinedButton(onClick = { onCandidate(message.id, candidate) }, enabled = canSend,
                                    modifier = Modifier.fillMaxWidth()) {
                                    Column(Modifier.fillMaxWidth()) {
                                        Text(candidate.title)
                                        Text(candidate.artist ?: "가수 정보 없음", style = MaterialTheme.typography.bodySmall)
                                        candidate.album?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                                    }
                                }
                            }
                        }
                        "needs_track" -> {
                            TextButton(onClick = onChooseTrack) { Text("내 곡에서 선택하기") }
                            if (state.selectedTrack != null) TextButton(onClick = { onRetry(message.id) }, enabled = canSend) {
                                Text("선택한 곡으로 다시 질문")
                            }
                        }
                        "not_found" -> Text("내 곡에 해당 기록이 있는지 확인해 주세요.", style = MaterialTheme.typography.bodySmall)
                        "unsupported" -> Text("곡별 최초 기록일·청취 시간이나 내 청취 통계를 질문해 주세요.", style = MaterialTheme.typography.bodySmall)
                    }
                    if (reply.rows.isNotEmpty()) StatsTable(reply.rows)
                }
            }
        }
    }
}

@Composable
private fun StatsTable(rows: List<JsonObject>) {
    val columns = rows.flatMap { it.keys }.distinct()
    Column(Modifier.horizontalScroll(rememberScrollState())) {
        Row {
            columns.forEach { key -> Text(statLabel(key), Modifier.width(150.dp).padding(8.dp), fontWeight = FontWeight.SemiBold) }
        }
        HorizontalDivider(Modifier.width((columns.size * 150).dp))
        rows.forEach { row ->
            Row {
                columns.forEach { key -> Text(row[key]?.let { statValue(key, it) } ?: "정보 없음",
                    Modifier.width(150.dp).padding(8.dp)) }
            }
        }
    }
}
