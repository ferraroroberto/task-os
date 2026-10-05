"""The gallery's host-identity guard (#351), proven without a browser.

``tests/e2e/_host_identity.py`` is what ``shot()`` asks before it captures: does
the page render the home directory or the account name of the machine running
the suite? These tests hand it a synthetic home and name, never the real ones,
so they say nothing about the machine they run on.
"""

from __future__ import annotations

from tests.e2e._host_identity import describe, host_needles, leaks

HOME = r"C:\Users\alexandra"
NEEDLES = host_needles(home=HOME, user="alexandra")
#: A profile path names the account too, so it trips both kinds.
PATH_LEAK = ["account name", "home directory"]


def test_a_path_under_the_home_directory_is_caught_in_either_slash_form() -> None:
    assert leaks([r"onedrive=C:\Users\alexandra\AppData\Local\Temp\taskos-e2e\folders\od"], NEEDLES) == PATH_LEAK
    assert leaks(["C:/Users/alexandra/AppData/Local/Temp/od/house/kitchen"], NEEDLES) == PATH_LEAK
    assert leaks(["c:/users/ALEXANDRA/od"], NEEDLES) == PATH_LEAK


def test_a_text_field_value_counts_like_painted_text() -> None:
    assert leaks(["Folder", r"C:\Users\alexandra\od\admin\car"], NEEDLES) == PATH_LEAK


def test_the_bare_account_name_is_caught_as_a_word_only() -> None:
    assert leaks(["owner: Alexandra"], NEEDLES) == ["account name"]
    assert leaks(["Alexandrasson", "alexandra_2"], NEEDLES) == []


def test_a_short_account_name_is_matched_in_a_path_but_not_as_a_word() -> None:
    needles = host_needles(home="/home/sam", user="sam")
    assert leaks(["Waiting on Sam"], needles) == []                  # the seed's own people
    assert leaks(["/home/sam/od/house"], needles) == ["home directory"]


def test_a_synthetic_path_is_clean() -> None:
    assert leaks(["onedrive=C:/Users/Public/taskos-e2e/folders/od", "{onedrive}/house/kitchen"], NEEDLES) == []


def test_the_failure_message_never_repeats_what_it_found() -> None:
    message = describe(leaks([r"C:\Users\alexandra\od"], NEEDLES))
    assert "alexandra" not in message.lower()
    assert "home directory" in message


def test_no_home_and_no_name_means_nothing_to_find() -> None:
    assert host_needles(home="", user="") == []
