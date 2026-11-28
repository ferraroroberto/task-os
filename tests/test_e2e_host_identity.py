"""The gallery's host-identity guard (#351), proven without a browser.

``tests/e2e/_host_identity.py`` is what ``shot()`` asks before it captures: does
the page render the home directory or the account name of the machine running
the suite? These tests hand it a synthetic home and name, never the real ones,
so they say nothing about the machine they run on.
"""

from __future__ import annotations

from tests.e2e._host_identity import describe, host_needles, leaks

HOME = r"C:\Users\sample"
# an empty vocabulary: the placeholder is itself a word the fixtures print
NEEDLES = host_needles(home=HOME, user="sample", vocabulary=frozenset())
#: A profile path names the account too, so it trips both kinds.
PATH_LEAK = ["account name", "home directory"]


def test_a_path_under_the_home_directory_is_caught_in_either_slash_form() -> None:
    assert leaks([r"onedrive=C:\Users\sample\AppData\Local\Temp\taskos-e2e\folders\od"], NEEDLES) == PATH_LEAK
    assert leaks(["C:/Users/sample/AppData/Local/Temp/od/house/kitchen"], NEEDLES) == PATH_LEAK
    assert leaks(["c:/users/SAMPLE/od"], NEEDLES) == PATH_LEAK


def test_a_text_field_value_counts_like_painted_text() -> None:
    assert leaks(["Folder", r"C:\Users\sample\od\admin\car"], NEEDLES) == PATH_LEAK


def test_the_bare_account_name_is_caught_as_a_word_only() -> None:
    assert leaks(["owner: Sample"], NEEDLES) == ["account name"]
    assert leaks(["Sampleson", "sample_2"], NEEDLES) == []


def test_a_short_account_name_is_matched_in_a_path_but_not_as_a_word() -> None:
    needles = host_needles(home="/home/you", user="you")
    assert leaks(["Waiting on You"], needles) == []                  # an ordinary word on a page
    assert leaks(["/home/you/od/house"], needles) == ["home directory"]


def test_an_account_named_like_an_app_word_is_still_caught_in_a_path_only() -> None:
    # a CI account named like a word the app prints would otherwise match that label
    needles = host_needles(home="/Users/sample", user="sample", vocabulary=frozenset({"sample", "issues"}))
    assert leaks(["sample · last synced", "Issues synced"], needles) == []
    assert leaks(["/Users/sample/od/house"], needles) == ["home directory"]


def test_the_app_vocabulary_holds_ui_words_but_not_this_hosts_account() -> None:
    from tests.e2e._host_identity import _account_name, app_vocabulary

    vocabulary = app_vocabulary()
    assert "github" in vocabulary
    assert _account_name().lower() not in vocabulary, "the guard would be blind to this host's own name"


def test_a_synthetic_path_is_clean() -> None:
    assert leaks(["onedrive=C:/Users/me/taskos-e2e/folders/od", "{onedrive}/house/kitchen"], NEEDLES) == []


def test_the_failure_message_never_repeats_what_it_found() -> None:
    message = describe(leaks([r"C:\Users\sample\od"], NEEDLES))
    assert "sample" not in message.lower()
    assert "home directory" in message


def test_no_home_and_no_name_means_nothing_to_find() -> None:
    assert host_needles(home="", user="") == []
