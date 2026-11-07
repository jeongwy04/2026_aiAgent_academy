package kr.firstlisten.app.network

import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kr.firstlisten.app.data.SessionStore
import kr.firstlisten.core.HttpFailure
import java.io.IOException

internal fun SessionStore.accounts() = state.map { currentAccount() }.distinctUntilChanged()

internal fun requestMessage(error: Exception): String = when (error) {
    is HttpFailure -> when (error.code) {
        401 -> "로그인이 만료되었습니다. 기록 탭에서 다시 로그인해 주세요."
        404 -> "해당 곡의 기록을 찾을 수 없습니다. 내 곡 목록을 새로고침해 주세요."
        429 -> "요청이 많습니다. 잠시 후 다시 시도해 주세요."
        else -> error.message ?: "서버 요청을 완료하지 못했습니다."
    }
    is IOException -> "서버에 연결할 수 없습니다. 서버 주소와 연결 상태를 확인해 주세요."
    else -> error.message ?: "요청을 완료하지 못했습니다."
}
