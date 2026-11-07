package kr.firstlisten.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import kr.firstlisten.app.LibraryUiState
import kr.firstlisten.app.network.TrackOut

@Composable
fun SignInPrompt(onLogin: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("내 청취 기록을 확인해 보세요", style = MaterialTheme.typography.headlineSmall)
        Text("기록 탭에서 로그인하면 내 곡과 질문을 사용할 수 있습니다.")
        Button(onClick = onLogin) { Text("로그인하러 가기") }
    }
}

@Composable
fun LibraryScreen(
    state: LibraryUiState,
    onQuery: (String) -> Unit,
    onRefresh: () -> Unit,
    onMore: () -> Unit,
    onTrack: (TrackOut) -> Unit,
    onBack: () -> Unit,
    onAsk: (TrackOut) -> Unit,
) {
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val selected = state.selectedTrack
        if (selected != null) {
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = onBack) { Text("‹ 내 곡 목록") }
                    TextButton(onClick = onRefresh, enabled = !state.detailLoading) { Text("새로고침") }
                }
            }
            item {
                Text(selected.title, style = MaterialTheme.typography.headlineMedium)
                Text(selected.artist ?: "가수 정보 없음", style = MaterialTheme.typography.titleMedium)
                selected.album?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            }
            if (state.detailLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.detailError?.let { error -> item {
                Text(error, color = MaterialTheme.colorScheme.error)
                OutlinedButton(onClick = onRefresh) { Text("다시 불러오기") }
            } }
            state.stats?.let { stats ->
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text("최초 기록 · 한국 시간", style = MaterialTheme.typography.labelLarge)
                            Text(formatTimestamp(stats.first_recorded_at), style = MaterialTheme.typography.titleLarge)
                            Text("측정된 청취 시간", style = MaterialTheme.typography.labelLarge)
                            Text(formatDuration(stats.total_listened_ms), style = MaterialTheme.typography.headlineSmall)
                            Text("전체 기록 ${stats.event_count}개")
                            Text("시간 측정 ${stats.measured_event_count}개 · 시간 미상 ${stats.unknown_duration_event_count}개")
                            if (stats.unknown_duration_event_count > 0) {
                                Text("청취 시간을 알 수 없는 가져오기 기록은 시간 합계에서 제외됩니다.",
                                    style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                item { Button(onClick = { onAsk(stats.track) }, modifier = Modifier.fillMaxWidth()) { Text("이 곡 질문하기") } }
            }
        } else {
            item {
                Row(Modifier.fillMaxWidth().padding(top = 16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("내 곡", style = MaterialTheme.typography.headlineLarge)
                    TextButton(onClick = onRefresh, enabled = !state.loading) { Text("새로고침") }
                }
                Text("서버에 저장된 나의 청취 기록", style = MaterialTheme.typography.bodyMedium)
            }
            item {
                OutlinedTextField(value = state.query, onValueChange = onQuery,
                    label = { Text("곡명 또는 가수 검색") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { onRefresh() }), modifier = Modifier.fillMaxWidth())
            }
            item { Text("${state.total}곡", style = MaterialTheme.typography.labelLarge) }
            if (state.loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { error -> item {
                Text(error, color = MaterialTheme.colorScheme.error)
                OutlinedButton(onClick = onRefresh,
                    enabled = !state.loading && !state.loadingMore) { Text("다시 시도") }
            } }
            if (!state.loading && state.error == null && state.tracks.isEmpty()) item {
                Text(if (state.query.isBlank()) "아직 서버에 저장된 곡이 없습니다. 기록 탭에서 동기화한 뒤 새로고침해 주세요."
                    else "검색 결과가 없습니다. 다른 곡명이나 가수를 입력해 주세요.")
            }
            items(state.tracks, key = TrackOut::id) { track ->
                Card(onClick = { onTrack(track) }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(track.title, style = MaterialTheme.typography.titleMedium)
                        Text(track.artist ?: "가수 정보 없음")
                        track.album?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
            if (state.loadingMore) item { CircularProgressIndicator() }
            if (state.hasMore) item {
                OutlinedButton(onClick = onMore, enabled = !state.loading && !state.loadingMore,
                    modifier = Modifier.fillMaxWidth()) { Text("더 보기") }
            }
        }
        item { Text("", Modifier.padding(bottom = 8.dp)) }
    }
}
