import pytest

from app.services.takeout_metadata import extract_metadata


@pytest.mark.parametrize("title,channel,song,artist,basis", [
    ("More", "ILLIT - Topic", "More", "ILLIT", "topic_channel"),
    ("Artist - More", "Artist - Topic", "More", "Artist", "topic_channel"),
    ("More - Artist", "Artist - Topic", "More", "Artist", "topic_channel"),
    ("Song - Part 2", "Artist - Topic", "Song - Part 2", "Artist", "topic_channel"),
    ("Effie - Red Horse", "Effie", "Red Horse", "Effie", "title_and_channel"),
    ("Red Horse - Effie", "Effie", "Red Horse", "Effie", "title_and_channel"),
    ("Effie - down (Official MacBook Video)", "Effie", "down", "Effie", "title_and_channel"),
    ("The Deep - Angel Tattoo (Official Video)", "The Deep", "Angel Tattoo", "The Deep", "title_and_channel"),
    ("MEOVV(미야오) - 'In my hands' M/V", "THEBLACKLABEL", "In my hands", "MEOVV(미야오)", "quoted_music_video_title"),
    ("LE SSERAFIM (르세라핌) 'Perfect Night' OFFICIAL M/V with OVERWATCH 2", "HYBE LABELS", "Perfect Night", "LE SSERAFIM (르세라핌)", "quoted_music_video_title"),
    ("Hearts2Hearts 하츠투하츠 'Moonride' MV", "Hearts2Hearts", "Moonride", "Hearts2Hearts 하츠투하츠", "quoted_music_video_title"),
    ('Artist “Song” MV', "Label", "Song", "Artist", "quoted_music_video_title"),
    ("Artist ‘Song’ MV", "Label", "Song", "Artist", "quoted_music_video_title"),
])
def test_supported_artist_and_title_locations(title, channel, song, artist, basis):
    assert extract_metadata(title, [{"name": channel}]) == {
        "display_title": song, "artist": artist, "metadata_basis": basis,
    }


@pytest.mark.parametrize("title,channels", [
    ("More", [{"name": "HYBE LABELS"}]),
    ("Hey Hi", [{"name": "KiiiKiii"}]),  # Plain uploader names have no artist semantics.
    ("404 Walls - 키키 x f(x) (Feat. 니키 미나즈)", [{"name": "정했다일기석"}]),
    ("Effie - Song (Guide ver MV)", [{"name": "Effie"}]),
    ("Izna (이즈나) - ‘SIGN (House Remix)’", [{"name": "Rio"}]),
    ("Artist 'Song' COVER MV", [{"name": "Label"}]),
    ("Song", [{"name": "One - Topic"}, {"name": "Two - Topic"}]),
    ("Song", [{"name": " - Topic"}]),
    ("Song", [{"name": "A" * 301 + " - Topic"}]),
    ("Song", []),
])
def test_ambiguous_uploaders_and_titles_remain_unknown(title, channels):
    assert extract_metadata(title, channels) == {
        "display_title": title, "artist": None, "metadata_basis": None,
    }


def test_topic_retains_real_song_version_and_featured_artist_text():
    title = "Song (Remix) (feat. Guest)"
    result = extract_metadata(title, [{"name": "Artist - Topic"}])
    assert result["display_title"] == title
    assert result["artist"] == "Artist"
