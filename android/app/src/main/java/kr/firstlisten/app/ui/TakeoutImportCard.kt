package kr.firstlisten.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kr.firstlisten.app.TakeoutImportState

@Composable
fun TakeoutImportCard(state: TakeoutImportState, signedIn: Boolean, enabled: Boolean,
    onImport: () -> Unit, onImportedTracks: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Google Takeout 가져오기", style = MaterialTheme.typography.titleLarge)
            Text("Google Takeout에서 받은 활동 기록의 압축을 풀고 JSON 파일을 선택해 주세요. 최대 100 MiB까지 지원합니다.")
            Text("선택한 파일을 서버로 보내 현재 로그인한 계정에 음악 청취 기록을 저장합니다. 같은 기록은 다시 가져와도 중복 저장하지 않습니다.",
                style = MaterialTheme.typography.bodySmall)
            if (!signedIn) Text("로그인한 뒤 파일을 가져올 수 있습니다.")
            Button(enabled = signedIn && enabled && !state.busy, onClick = onImport) {
                Text(if (state.busy) "가져오는 중…" else "JSON 파일 선택 및 가져오기")
            }
            if (state.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Text("파일 업로드 및 기록 저장 중입니다. 큰 파일은 몇 분 걸릴 수 있습니다. 앱을 열어 두세요.")
            }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.result?.let { result ->
                Text("가져오기 완료", style = MaterialTheme.typography.titleMedium)
                Text("전체 ${result.total}건 · 음악 기록 ${result.accepted}건")
                Text("새로 저장 ${result.inserted}건 · 중복 ${result.duplicates}건")
                Text("제외 ${result.excluded}건 · 검토 필요 ${result.review}건 · 오류 ${result.errors}건")
                Text("새 곡 ${result.new_tracks}개 · 이번 파일의 곡 ${result.distinct_tracks}개")
                if (result.review > 0 || result.errors > 0) {
                    Text("검토 필요·오류 항목은 청취 기록에 추가되지 않았습니다.", style = MaterialTheme.typography.bodySmall)
                }
                Text("가져온 기록에는 재생 시간이 없어 시간 합계에서 제외됩니다. 내 곡에서 기록일과 횟수를 확인할 수 있습니다.",
                    style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = onImportedTracks) { Text("내 곡에서 확인") }
            }
        }
    }
}
