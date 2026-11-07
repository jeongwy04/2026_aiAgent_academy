package kr.firstlisten.app

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kr.firstlisten.app.ui.ChatScreen
import kr.firstlisten.app.ui.LibraryScreen
import kr.firstlisten.app.ui.RecordScreen
import kr.firstlisten.app.ui.SignInPrompt

private enum class Tab(val label: String, val icon: Int) {
    RECORDS("기록", R.drawable.ic_records),
    LIBRARY("내 곡", R.drawable.ic_library),
    CHAT("질문", R.drawable.ic_chat),
}

class MainActivity : ComponentActivity() {
    private val model: MainViewModel by viewModels()
    private val library: LibraryViewModel by viewModels()
    private val chat: ChatViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                FirstListenApp(model, library, chat) {
                    startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        model.refreshPermission()
    }
}

@Composable
private fun FirstListenApp(main: MainViewModel, library: LibraryViewModel, chat: ChatViewModel, openPermissions: () -> Unit) {
    val session by main.session.collectAsStateWithLifecycle()
    val libraryState by library.state.collectAsStateWithLifecycle()
    val chatState by chat.state.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableStateOf(Tab.RECORDS) }
    var tabOwner by rememberSaveable { mutableStateOf(session.ownerKey) }
    val signedIn = session.memberId != null && !session.needsLogin && !session.expired

    LaunchedEffect(session.ownerKey) {
        if (tabOwner != session.ownerKey) {
            tab = Tab.RECORDS
            tabOwner = session.ownerKey
        }
    }
    LaunchedEffect(tab, session.sessionId) {
        if (tab == Tab.LIBRARY && signedIn) library.refresh()
    }
    BackHandler(enabled = tab != Tab.RECORDS) {
        if (tab == Tab.LIBRARY && libraryState.selectedTrack != null) library.closeDetail()
        else tab = Tab.RECORDS
    }

    Scaffold(bottomBar = {
        NavigationBar {
            Tab.entries.forEach { destination ->
                NavigationBarItem(selected = tab == destination, onClick = { tab = destination },
                    icon = { Icon(painterResource(destination.icon), contentDescription = null) },
                    label = { Text(destination.label) })
            }
        }
    }) { insets ->
        Box(Modifier.fillMaxSize().padding(insets).consumeWindowInsets(insets)) {
            when {
                tab == Tab.RECORDS -> RecordScreen(main, openPermissions)
                !signedIn -> SignInPrompt { tab = Tab.RECORDS }
                tab == Tab.LIBRARY && libraryState.ownerKey == session.ownerKey -> LibraryScreen(
                    state = libraryState,
                    onQuery = library::setQuery,
                    onRefresh = library::refresh,
                    onMore = library::loadMore,
                    onTrack = library::selectTrack,
                    onBack = library::closeDetail,
                    onAsk = { track -> chat.selectTrack(track); tab = Tab.CHAT },
                )
                tab == Tab.CHAT && chatState.ownerKey == session.ownerKey -> ChatScreen(
                    state = chatState,
                    onQuestion = chat::setQuestion,
                    onSend = chat::send,
                    onAsk = chat::ask,
                    onClearTrack = { chat.selectTrack(null) },
                    onChooseTrack = { tab = Tab.LIBRARY },
                    onCandidate = chat::chooseCandidate,
                    onRetry = chat::retry,
                )
                else -> CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
        }
    }
}
