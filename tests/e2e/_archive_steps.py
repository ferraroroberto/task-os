"""Story 24's constants, helpers and walk steps.

``test_story_24_archive`` calls the steps in order; the ``surface()`` capture
sits in the test body between them. A step is a slice of the walk, not an
isolated test: it leaves the page where the next one expects it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e._ui import (
    assert_action_row_budget,
    board_mode,
    close_settings_sheet,
    open_settings_sheet,
)
from tests.e2e.conftest import INTERCEPT, _get, dismiss_toasts, shot
from tests.fixtures.archiver_fake import calls

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

KITCHEN = "Kitchen quotes from the installer"
SCHOOL = "School enrolment forms — deadline Friday"

# The synthetic archive tree. `{archive}` is a placeholder of this instance, so
# the *Other folder…* field can name a folder the way the drawer would.
HOUSE = "E:\\archive\\house\\heating"
BILLS = "E:\\archive\\admin\\bills"
HOUSE_FILE = "E:\\archive\\house\\heating\\0042 - boiler service.msg"
BILLS_FILE = "E:\\archive\\admin\\bills\\0007 - something ambiguous.msg"
STUCK_FILE = "E:\\archive\\house\\heating\\0043 - roof survey.msg"
# Deep enough that the reason it appears in is wider than a 390px card, which
# is what the phone's last-three-components fold is for (#168).
UNREACHABLE = "E:\\archive\\house\\heating\\2026\\surveys\\pending"
MEMBERSHIPS = "E:\\archive\\admin\\renewals"

FILED_ID = "boiler@example.invalid"
UNSURE_ID = "ambiguous@example.invalid"
STUCK_ID = "roof@example.invalid"
#: A mail the archiver's index already has **and** which is still sitting in the
#: Inbox — what a refused move leaves behind on every later plan (#174). The run
#: finishes it instead of recording it as done: nothing is written, the file it
#: already has is reused, and the mail finally leaves the Inbox.
REUSED_ID = "insurance@example.invalid"
REUSED_FILE = "E:\\archive\\admin\\renewals\\0031 - insurance policy.msg"
#: Two more mails the ranking would not decide (#168): one gets accepted on the
#: desktop leg, so the phone shows a **reviewed** row that offers nothing; the
#: other is left open, so the phone also shows a live *File it…* and a bulk
#: button whose count is the rows that really do still offer *Accept*.
REVIEWED_ID = "renewal@example.invalid"
OPEN_ID = "invoice@example.invalid"
#: A filed mail whose `.msg` name alone is ~90 characters, with three
#: attachment files beside it — the phone card #173 fixes: on the school
#: mail's real card the `.msg` chip ran past the card's right edge and the
#: pane scrolled sideways, exactly what the run below reproduces before the
#: fix (and stays clean after it).
LONG_ID = "school-enrolment@example.invalid"
LONG_FILE = ("E:\\archive\\house\\heating\\2026-09-08 - 0006 - "
             "School enrolment forms for the autumn term and the after-school club.msg")
LONG_ATT_1 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - enrolment-form.pdf"
LONG_ATT_2 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - payment-schedule.docx"
LONG_ATT_3 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - club-timetable.pdf"
#: A fourth attachment (#178) — five files total, so the desktop table's cap
#: (four shown, a "+1 more" chip standing in for the rest) and the row's
#: consequent second line of chips both have something real to prove against.
LONG_ATT_4 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - medical-form.pdf"

#: Long enough that the running state is observable from the page and from a
#: second POST, short enough that the story stays a few seconds. Only the run's
#: own `plan` pays it: the single-mail apply / revert the story presses by hand
#: are one-shot calls nothing observes mid-flight.
CHILD_SLEEP_S = 1.1

class ArchiveInstance:
    def __init__(self, base: str, od: Path, repo: Path, db: Path) -> None:
        self.base = base
        self.od = od
        self.repo = repo
        self.db = db

def _post_status(base: str, path: str, body: dict) -> int:
    """POST and hand back the status code — including a 4xx, which is the point."""
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return int(res.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _row(page: Page, message_id: str, items: list[dict]):
    """The report row for one mail, by the item id the API gave it."""
    item = next(i for i in items if i["message_id"] == message_id)
    return page.locator(f".archive-row[data-id='{item['id']}']"), item


def _menu(page: Page, row) -> list[str]:
    """The actions a desktop row's ⋮ offers, in order (#350); the menu is closed again after."""
    row.locator(".archive-kebab").click()
    items = page.locator(".row-menu .row-menu-item")
    expect(items.first).to_be_visible()
    actions = items.evaluate_all("els => els.map(e => e.dataset.action)")
    page.keyboard.press("Escape")
    expect(page.locator(".row-menu")).to_have_count(0)
    return actions


def _choose(page: Page, row, action: str) -> None:
    """Run one of a desktop row's review levels from its ⋮ (#350)."""
    row.locator(".archive-kebab").click()
    page.locator(f".row-menu [data-action='{action}']").click()


def _menus(page: Page) -> dict[int, list[str]]:
    """Every desktop row's ⋮ actions by item id; a row with nothing to press has no ⋮."""
    out = {}
    for row in page.locator(".archive-row").all():
        rid = int(row.get_attribute("data-id"))
        out[rid] = _menu(page, row) if row.locator(".archive-kebab").count() else []
    return out


def _items(base: str, run_id: int) -> list[dict]:
    return _get(base, f"/api/archive/runs/{run_id}")["items"]


#: One caption line at this width, with room for the row's own leading. The
#: card's second line taller than this has wrapped, which is the thing #168
#: removed (the head's status readings may wrap since #427 — never be cut).
_ONE_LINE_PX = 24.0

# The visible row verbs on a phone card (fleet-config#1420): what each one is
# called, and whether anything is painted on it at rest.
ROW_VERB_SHAPE_JS = (
    "els => els.map(el => { const cs = getComputedStyle(el); return {"
    " tag: el.tagName, label: el.getAttribute('aria-label'), title: el.title,"
    " height: Math.round(el.offsetHeight), font: cs.fontSize, pad: cs.padding,"
    " bg: cs.backgroundColor, border: cs.borderTopWidth + ' ' + cs.borderTopStyle}; })"
)


def _assert_unpainted(shapes: list[dict]) -> None:
    for shape in shapes:
        assert shape["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), f"{shape['label']} is filled: {shape}"
        assert shape["border"].split()[0] == "0px" or shape["border"].endswith("none"), (
            f"{shape['label']} is outlined: {shape}"
        )


def _box(locator) -> dict[str, float]:
    """The rendered box of the one element *locator* matches; missing fails loud."""
    box = locator.bounding_box()
    if box is None:
        raise AssertionError(f"{locator} has no box — it is not rendered")
    return box


def _mid_y(box: dict[str, float]) -> float:
    return box["y"] + box["height"] / 2


def _pin_scroller(page: Page) -> None:
    """Park the report's own scroller at its left edge, and prove it stayed.

    The nine columns fit 1440 with only a few pixels of slack, so focusing a
    control inside the panel can nudge the scroller — enough to reframe a shot
    between two runs of one commit (rule 3 in `docs/validation.md`).
    """
    scroller = page.locator("#archiveCard .archive-grid-scroll")
    scroller.evaluate("el => { el.scrollLeft = 0; }")
    assert scroller.evaluate("el => el.scrollLeft") == 0


#: The desktop grid's computed look, captured before its classes were renamed
#: from the Table view's `.task-table` / `.table-wrap` / `.table-scroll` to
#: `.archive-grid*` (#442). A rename must not move a pixel, so the look is
#: pinned here by element role (wrap › scroll › table › th / td), not by class.
GRID_LOOK = {
    "wrap": {
        "border-top-width": "0px", "padding-top": "0px", "padding-left": "0px",
        "overflow-x": "hidden", "overflow-y": "hidden", "background-color": "rgb(255, 255, 255)",
    },
    "scroll": {"overflow-x": "auto", "overflow-y": "auto", "max-height": "670px"},
    "table": {
        "border-collapse": "separate", "-webkit-border-horizontal-spacing": "0px",
        "-webkit-border-vertical-spacing": "0px", "font-size": "14px",
    },
    "th": {
        "position": "sticky", "top": "0px", "z-index": "1", "background-color": "rgb(255, 255, 255)",
        "color": "rgb(101, 109, 118)", "font-size": "12px", "font-weight": "600", "text-align": "left",
        "text-wrap-mode": "nowrap", "padding-top": "8px", "padding-left": "10px",
        "border-bottom-width": "1px",
    },
    "td": {
        "padding-top": "6px", "padding-left": "10px", "border-top-width": "0px",
        "vertical-align": "middle",
    },
}


def _assert_grid_look(page: Page) -> None:
    """The report grid still paints as it did under its old class names."""
    got = page.evaluate(
        """(look) => {
          const table = document.querySelector('#archiveCard table');
          const scroll = table.parentElement;
          const els = {wrap: scroll.parentElement, scroll, table,
                       th: table.querySelector('thead th'), td: table.querySelector('tbody td')};
          const out = {};
          for (const [role, props] of Object.entries(look)) {
            const cs = getComputedStyle(els[role]);
            out[role] = Object.fromEntries(Object.keys(props).map(p => [p, cs.getPropertyValue(p)]));
          }
          return out;
        }""",
        GRID_LOOK,
    )
    assert got == GRID_LOOK


def _confirm(page: Page, action: str) -> None:
    """The one vendored destructive-action dialog (#121) — press its primary."""
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".button-tint.danger")).to_have_text(action)
    dialog.locator(".button-tint.danger").click()
    expect(dialog).to_be_hidden()

def _item_id(base: str, run_id: int, message_id: str) -> int:
    return next(i["id"] for i in _items(base, run_id) if i["message_id"] == message_id)

# ------------------------------------------------------------- the walk

def _capture_into_inbox(page: Page, base: str, shots: Path) -> None:
    """Settings' Capture sheet lands the flagged mails as Inbox tasks carrying their .msg chip."""
    #    flagged mails as Inbox tasks (the on-screen half of story 21).
    card = open_settings_sheet(page, "capture")
    expect(page.locator("#captureCardMeta")).to_have_text("on")          # the row's word (#397)
    expect(card.locator("#statusCaptureRun")).to_have_text("not yet")
    card.locator("#captureRunNow").click()
    expect(page.locator("#captureCardMeta")).to_have_text("checked")
    expect(card.locator("#statusCaptureRun")).to_contain_text("2 flagged · 2 new")
    shot(page, shots / "story-24-archive-1-desktop.png")

    # 2. …as Inbox tasks the capture made, each carrying the .msg its chip opens
    page.get_by_role("tab", name="Board").click()
    board_mode(page, "status")                      # the status columns (#396)
    inbox = page.locator("#paneBoard .board-status .board-col[data-col='inbox']")
    expect(inbox.locator(".trow-title", has_text=KITCHEN)).to_be_visible()
    captured = _get(base, "/api/tasks?status=inbox")["items"]
    assert {t["title"] for t in captured} == {KITCHEN, SCHOOL}
    assert all(t["created_by"] == "email-archiver" for t in captured)
    inbox.locator(".trow-main", has_text=KITCHEN).first.click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    chip = drawer.locator(".drawer-pill-row a.chip", has_text="Kitchen quotes.msg")   # the link pills (#394)
    expect(chip).to_contain_text("2026-08-10 Kitchen quotes.msg")
    expect(chip).to_have_attribute(
        "href",
        "taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse%2F2026-08-10%20Kitchen%20quotes.msg",
    )
    shot(page, shots / "story-24-archive-2-desktop.png")
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()

def _archive_sheet_before_run(page: Page, inst: ArchiveInstance, shots: Path) -> object:
    """Email archiving before anything has run: configured, bounded, no run to show. Returns the sheet."""
    pane = open_settings_sheet(page, "archive")
    expect(pane.locator("#statusArchive .status-ok")).to_have_text("ready")
    # the reading is in words, not config ids (#339): the model by name, the batch in mails
    expect(pane.locator("#statusArchive")).to_contain_text("sorted by Claude Haiku · 8 mails a batch")
    expect(pane.locator("#statusArchiveRun")).to_have_text("never")
    expect(pane.locator("#statusArchiveRecent")).to_have_text("no finished run yet")
    expect(pane.locator("#statusArchiveRepo code")).to_have_text(str(inst.repo))
    expect(pane.locator("#statusArchiveThreshold")).to_contain_text("70%")
    expect(pane.locator("#archiveLimit")).to_have_value("")
    expect(pane.locator("#archiveRun")).to_be_enabled()
    expect(pane.locator("#archiveHost .empty-state-message")).to_contain_text("No run yet")
    shot(page, shots / "story-24-archive-3-desktop.png")
    return pane

def _run_archive(page: Page, base: str, pane) -> tuple:
    """Press Run: the button is disabled and a second run is refused, then the report fills in."""
    # 4. Press it. While the child is working the button is disabled and a
    #    second run is refused by the API with its own reason — one Outlook,
    #    one run at a time.
    pane.locator("#archiveRun").click()
    expect(pane.locator("#archiveRun")).to_be_disabled()
    expect(pane.locator("#archiveRunLabel")).to_have_text("Archiving…")
    assert _post_status(base, "/api/archive/run", {}) == 409

    # 5. It finishes on its own and the report fills in: two filed, one that
    #    needs a human, one the archiver broke on.
    expect(pane.locator("#archiveRun")).to_be_enabled(timeout=30000)
    expect(pane.locator(".archive-row")).to_have_count(7)
    run_id = _get(base, "/api/archive/runs")["runs"][0]["id"]
    items = _items(base, run_id)
    return run_id, items

def _report_rows(page: Page, pane, items: list[dict]) -> tuple:
    """The report's counts and the filed and long-named rows. Returns the filed row, its item, the long row."""
    assert {i["message_id"]: i["status"] for i in items} == {
        FILED_ID: "archived", UNSURE_ID: "needs_review", STUCK_ID: "failed",
        REVIEWED_ID: "needs_review", OPEN_ID: "needs_review", LONG_ID: "archived",
        REUSED_ID: "archived",
    }
    expect(pane.locator("#statusArchiveRun")).to_contain_text(
        "7 mail(s) · 3 filed · 3 need you · 1 failed"
    )
    filed_row, filed_item = _row(page, FILED_ID, items)
    expect(filed_row.locator(".archive-state")).to_have_text("filed")
    expect(filed_row.locator(".archive-dest")).to_have_text("archive › house › heating")
    expect(filed_row.locator(".archive-files a.chip")).to_have_attribute(
        "href", "taskos://open?ref=" + "E%3A%5Carchive%5Chouse%5Cheating%5C0042%20-%20boiler%20service.msg"
    )
    long_row, long_item = _row(page, LONG_ID, items)
    expect(long_row.locator(".archive-state")).to_have_text("filed")
    # Five files on this mail: the desktop table shows one chip and folds the
    # rest behind a "+4 more" chip (#178; one since #339's J-10, so a row reads
    # in two lines and keeps to the action-row budget with its ⋮, #350) — the
    # phone card, checked further down, still shows all five.
    expect(long_row.locator(".archive-files a.chip")).to_have_count(1)
    expect(long_row.locator(".archive-files-more")).to_have_text("+4 more")
    # Desktop keeps the full name, date prefix and all (#173) — the phone-only
    # trim is a card-width concession, not a change to what the desktop shows.
    expect(long_row.locator(".archive-files a.chip").first).to_have_text(
        "2026-09-08 - 0006 - School enrolment forms for the autumn term and the after-school club.msg"
    )
    return filed_row, filed_item, long_row

def _long_row_chips(page: Page, long_row) -> None:
    """The +4 more chip expands in place and the row's cells stay vertically centred."""
    # 5c. The "+4 more" chip expands the rest in place, one click, no
    #     re-render — and once all five chips are on screen the file column
    #     wraps onto a second line, taller than every other cell in the row.
    #     That used to read as the row's other cells having drifted to the
    #     top; centred vertical alignment (#178) keeps them level with it.
    # #305: the file chips are 44px targets (the "+4 more" one too), and on the
    # wrapped second line they touch the first without overlapping it.
    assert_min_target(long_row.locator(".archive-files .chip"))
    assert_no_overlap(long_row.locator(".archive-files .chip"))
    # #350: at rest a row carries its file chip, the "+N more" and the ⋮ —
    # the action-row budget (design.md) — with the review levels in the menu
    assert_action_row_budget(page.locator(".archive-grid tr.archive-row"))
    long_row.locator(".archive-files-more").click()
    expect(long_row.locator(".archive-files a.chip")).to_have_count(5)
    expect(long_row.locator(".archive-files-more")).to_have_count(0)
    assert_min_target(long_row.locator(".archive-files .chip"))
    assert_no_overlap(long_row.locator(".archive-files .chip"))
    subject_box = _box(long_row.locator(".c-subject > *"))
    files_box = _box(long_row.locator(".c-files > *"))
    assert files_box["height"] > subject_box["height"] + 4, (
        "five expanded chips did not wrap onto a second line — "
        f"the centring check below would prove nothing ({files_box} vs {subject_box})"
    )
    assert abs(_mid_y(subject_box) - _mid_y(files_box)) < 2, (
        f"the file-chip cell is not vertically centred on the row ({files_box} vs {subject_box})"
    )
    for col in (".c-dest", ".c-conf", ".c-state", ".c-act"):
        box = _box(long_row.locator(f"{col} > *"))
        assert abs(_mid_y(subject_box) - _mid_y(box)) < 2, (
            f"{col} is not vertically centred on the row ({box} vs subject {subject_box})"
        )

    # #339: the table fits the window, so every row's ⋮ is on screen rather
    # than scrolled past the right edge
    scroller = page.locator("#archiveCard .archive-grid-scroll")
    fit = scroller.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert fit[0] <= fit[1] + 1, f"the Archive grid scrolls sideways at {DESKTOP['width']}px: {fit}"

def _stuck_row_and_menus(page: Page, items: list[dict]) -> tuple:
    """The row the archiver broke on is the one that offers Retry. Returns it and every row's menu."""
    stuck_row, _ = _row(page, STUCK_ID, items)
    expect(stuck_row.locator(".archive-state")).to_have_text("failed")
    expect(stuck_row.locator(".archive-reason")).to_contain_text("move_failed")
    # …and, because the file was written before the move was refused, it is the
    # one row that can be *finished* rather than only undone (#174). No other
    # row offers it: a retry re-sends a decision, which anywhere else would file
    # a mail twice.
    menus = _menus(page)
    assert menus[int(stuck_row.get_attribute("data-id"))] == ["accept", "move", "retry", "revert"]
    assert [rid for rid, acts in menus.items() if "retry" in acts] == [int(stuck_row.get_attribute("data-id"))]
    return stuck_row, menus

def _reused_row_and_kebab(
    page: Page, inst: ArchiveInstance, shots: Path, items: list[dict], menus: dict,
    filed_item: dict, stuck_row,
) -> None:
    """A mail already on disk is finished, not re-filed; the grid's look and a row's kebab menu."""
    # 5b. The mail whose `.msg` the archiver's index already had, still sitting
    #     in the Inbox: the run finished it — the folder is the one its file
    #     lives in, nothing was ranked and nothing was written.
    reused_row, reused_item = _row(page, REUSED_ID, items)
    expect(reused_row.locator(".archive-state")).to_have_text("filed")
    expect(reused_row.locator(".archive-dest")).to_have_text("archive › admin › renewals")
    expect(reused_row.locator(".archive-reason")).to_contain_text("finished a mail already on disk")
    expect(reused_row.locator(".archive-files a.chip")).to_have_count(1)
    assert reused_item["files"] == [REUSED_FILE] and reused_item["chosen_rank"] is None
    # A reuse allocates no sequence number, and the row says so.
    assert reused_item["sequence"] is None
    assert {
        "message_id": REUSED_ID, "folder_path": "E:/archive/admin/renewals", "date_prefix": False,
    } in [c for c in calls(inst.repo) if c["verb"] == "apply"][0]["payload"]

    # An `archived` row is finished, not reviewed: the API answers 409 on
    # accept, so the screen does not offer it.
    assert "accept" not in menus[filed_item["id"]] and "accept" not in menus[reused_item["id"]]
    # The bulk button's N is the rows that really do offer *Accept*, not a
    # second count that drifts from them (#168).
    assert len([rid for rid, acts in menus.items() if "accept" in acts]) == 4
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 4 that need you")
    dismiss_toasts(page)
    _pin_scroller(page)
    _assert_grid_look(page)
    shot(page, shots / "story-24-archive-4-desktop.png")
    # #350: the table is no ARIA grid any more — its rows are list rows
    expect(page.locator(".archive-grid")).not_to_have_attribute("role", "grid")
    assert_min_target(page.locator(".archive-kebab"))
    # #424: the ⋮ is named for the menu it opens, not for the row action
    expect(stuck_row.locator(".archive-kebab")).to_have_attribute("aria-label", re.compile(r"^Actions for "))
    # the menu names the levels the row allows, Revert last behind its divider
    stuck_row.locator(".archive-kebab").click()
    expect(stuck_row.locator(".archive-kebab")).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".row-menu .row-menu-item")).to_have_text(["Accept", "Move to…", "Retry", "Revert"])
    expect(page.locator(".row-menu .row-menu-divider")).to_be_visible()
    page.keyboard.press("Escape")
    expect(stuck_row.locator(".archive-kebab")).to_be_focused()

def _file_unsure_by_hand(
    page: Page, inst: ArchiveInstance, shots: Path, items: list[dict], run_id: int
) -> None:
    """File the mail the ranking would not decide into a candidate with a hint."""
    base = inst.base
    # 6. The mail the ranking would not decide: open its menu, the candidates it
    #    ranked are there, type why, and file it into one of them.
    unsure_row, unsure_item = _row(page, UNSURE_ID, items)
    expect(unsure_row.locator(".archive-state")).to_have_text("needs you")
    expect(unsure_row.locator(".archive-dest")).to_have_text("archive › admin › bills")
    _choose(page, unsure_row, "move")
    # the panel is a full-width row of its own, under the mail's
    panel = page.locator(f".archive-move-row[data-id='{unsure_item['id']}']")
    expect(panel).to_be_visible()
    cands = panel.locator(".archive-cand")
    expect(cands).to_have_count(2)
    expect(cands.first.locator(".archive-cand-path")).to_have_text("archive › admin › bills")
    panel.locator(".archive-hint").fill("anything from this sender belongs with the bills")
    dismiss_toasts(page)
    _pin_scroller(page)
    shot(page, shots / "story-24-archive-5-desktop.png")
    cands.first.click()
    _confirm(page, "File it")
    expect(page.locator(f".archive-row[data-id='{unsure_item['id']}'] .archive-state")).to_have_text(
        "moved by you"
    )
    moved = next(i for i in _items(base, run_id) if i["message_id"] == UNSURE_ID)
    assert moved["status"] == "moved" and moved["files"] == [BILLS_FILE]
    assert moved["reason"] == "filed here by hand from the Inbox"
    # It was never on disk, so nothing was undone first — the archiver was
    # asked to file it, once.
    assert [c["verb"] for c in calls(inst.repo)] == ["plan", "apply", "apply"]

def _accept_and_bulk_cancel(page: Page, base: str, items: list[dict], run_id: int, stuck_row) -> dict:
    """Accept the broken row and a needs-review row; cancelling the bulk dialog hands the button back."""
    # 7. Accept the row the archiver broke on — "I have seen this", no file moved
    _choose(page, stuck_row, "accept")
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 2 that need you")
    assert next(i for i in _items(base, run_id) if i["message_id"] == STUCK_ID)["decided_at"]
    # Seeing it is not finishing it: the mail is still in the Inbox, so the
    # offer to finish it stands and the error text stays on screen until a
    # retry actually succeeds (#174).
    assert _menu(page, stuck_row) == ["move", "retry", "revert"]
    expect(stuck_row.locator(".archive-reason")).to_contain_text("move_failed")

    # 7b. A `needs_review` row that has had its human stops asking for one
    #     (#168): it reads *reviewed*, offers neither *Accept* nor *File it…*,
    #     and the bulk count follows the rows down instead of drifting from
    #     them — the run with three *needs you* rows used to say *Accept all 2*.
    reviewed_row, reviewed_item = _row(page, REVIEWED_ID, items)
    expect(reviewed_row.locator(".archive-state")).to_have_text("needs you")
    _choose(page, reviewed_row, "accept")
    reviewed_row = page.locator(f".archive-row[data-id='{reviewed_item['id']}']")
    expect(reviewed_row.locator(".archive-state")).to_have_text("reviewed")
    expect(reviewed_row.locator(".c-act")).to_have_text("nothing left to do")
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 1 that need you")
    assert len([rid for rid, acts in _menus(page).items() if "accept" in acts]) == 1

    # 7c. Cancelling the bulk confirmation hands the button back (#187): it is a
    #     static element, and only the report's redraw re-enables it — it used
    #     to stay dead until a page reload.
    bulk = page.locator("#archiveAcceptAll")
    bulk.click()
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    dialog.locator(".detail-close").click()
    expect(dialog).to_be_hidden()
    expect(bulk).to_be_enabled()
    expect(bulk).to_have_text("Accept all 1 that need you")
    return reviewed_item

def _revert_filed_row(
    page: Page, inst: ArchiveInstance, shots: Path, run_id: int, filed_row, filed_item: dict
) -> None:
    """Undo the one the run filed: the files go and the mail is back in the Inbox (dark)."""
    base = inst.base
    # 8. Undo the one the run filed: the files go, the mail is back in the Inbox
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    _choose(page, filed_row, "revert")
    _confirm(page, "Undo it")
    expect(page.locator(f".archive-row[data-id='{filed_item['id']}'] .archive-state")).to_have_text(
        "reverted"
    )
    undone = next(i for i in _items(base, run_id) if i["message_id"] == FILED_ID)
    assert undone["status"] == "reverted" and undone["files"] == []
    sent = [c for c in calls(inst.repo) if c["verb"] == "revert"][0]["payload"]
    assert sent == [{"message_id": FILED_ID, "files": [HOUSE_FILE]}]
    # …and there is nothing left to press on it, which the row says out loud.
    expect(page.locator(f".archive-row[data-id='{filed_item['id']}'] .c-act")).to_have_text(
        "back in the Inbox"
    )
    dismiss_toasts(page)
    _pin_scroller(page)
    shot(page, shots / "story-24-archive-6-desktop.png")

def _palette_and_settings_header(page: Page, shots: Path) -> None:
    """Go to Archive from the palette; Settings names what the run left for a human."""
    # 9. What the run left for a human is named where the sheet is reached:
    #    the palette's Go to Archive, which opens Settings → Email archiving
    #    (#397). The Board's Inbox column carried a pointer too, until the
    #    mail tools left the task columns (#396).
    page.emulate_media(color_scheme="light")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("tab", name="Board").click()
    expect(page.locator("#paneBoard .board-archive-link")).to_have_count(0)
    page.keyboard.press("Control+K")
    page.fill("#paletteInput", ">go to archive")
    expect(page.locator("#palette")).to_contain_text("3 mail(s) from the last run need you")
    page.keyboard.press("Enter")
    acard = page.locator("#archiveCard")
    expect(acard).to_be_visible()
    expect(page).to_have_url(re.compile(r"#settings/archive$"))

    # 9b. Settings gives the archiver the picture every other service has
    #     (#167, #397): the row's word, read from the very block the sheet
    #     renders, and the header naming what the last run left for a human.
    #     The sheet's Done goes back to the list.
    close_settings_sheet(page)
    expect(page.locator("#paneSettings")).to_be_visible()
    expect(page.locator("#archiveCardMeta")).to_have_text("on")
    expect(page.locator("#homeHeadStatus")).to_contain_text("3 mails need you")
    dismiss_toasts(page)
    shot(page, shots / "story-24-archive-9-desktop.png")

def _open_phone_report(browser: Browser, base: str) -> tuple:
    """A 390-wide touch context opens the report as cards. Returns the context and its page."""
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True,
                                has_touch=True, color_scheme="light")
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/")
    expect(p.locator("nav.tabs .tab")).to_have_count(4)
    open_settings_sheet(p, "archive", tap=True)
    expect(p.locator(".archive-card")).to_have_count(7)
    expect(p.locator(".archive-grid")).to_have_count(0)
    return phone, p

def _phone_long_card(p: Page, base: str, run_id: int) -> None:
    """The long .msg name's five chips stay inside the card."""
    # 10a-1. The long `.msg` name with three attachments beside it (#173):
    #        every chip stays inside the card, cut with an ellipsis, rather
    #        than widening the card and scrolling the pane sideways — the
    #        defect #168 fixed for the subject/path/reason columns, now for
    #        the file chips too.
    # The phone card carries all five files (#178 caps the desktop table only —
    # a card already has room to grow, and #173 already made every chip wrap
    # to its own line rather than widen the card).
    long_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, LONG_ID)}']")
    long_card.locator(".archive-menu-toggle").tap()      # the files wait behind Review (#339)
    long_chips = long_card.locator(".archive-files .chip")
    expect(long_chips).to_have_count(5)
    card_box = _box(long_card)
    for chip_index in range(5):
        chip_box = _box(long_chips.nth(chip_index))
        assert chip_box["x"] + chip_box["width"] <= card_box["x"] + card_box["width"] + 1, (
            f"chip {chip_index} runs past the card's right edge ({chip_box} vs {card_box})"
        )
    # #305: each stacked file chip is a 44px target, none sharing a pixel
    assert_min_target(long_chips)
    assert_no_overlap(long_chips)
    assert_no_horizontal_overflow(p)
    long_card.locator(".archive-menu-toggle").tap()

def _phone_head_readings(p: Page) -> None:
    """The head is one line and the readings wrap rather than being cut."""
    # 10a. The head is one line, and the three readings are one line each — no
    #      label column, short wording, and the bound compact beside the button
    #      that grew into what it left (#168).
    head_run, head_limit = _box(p.locator("#archiveRun")), _box(p.locator(".archive-limit"))
    assert abs(_mid_y(head_run) - _mid_y(head_limit)) < 6, "the head wrapped onto two lines"
    assert head_run["width"] > head_limit["width"], "the button did not take the free width"
    expect(p.locator("#statusArchive")).to_contain_text("Claude Haiku · 8 a batch")
    expect(p.locator("#archiveRecentLabel")).to_have_text("Recent")
    # `09/09 09:00`, not `9/9/26, 9:00 AM` — no year, a 24-hour clock, and the
    # day still in the locale's own order (the date moves, so the shape is what
    # is asserted).
    expect(p.locator("#statusArchiveRun")).to_have_text(
        re.compile(r"^\d{2}\D\d{2} \d{2}:\d{2} · done · 3 filed")
    )
    # #427: a reading that is longer than the line wraps; it is never cut. The
    # Last run row carries the failure count at its tail, which the old
    # one-line-with-an-ellipsis rule hid at 390 (LAYOUT-09).
    expect(p.locator("#statusArchiveRun")).to_contain_text("3 filed · 3 need you · 1 failed")
    for index in range(5):
        reading = p.locator("#archiveCard .archive-head .status-row dd").nth(index)
        cut = reading.evaluate(
            "el => ({ over: el.scrollWidth - el.clientWidth, ellipsis: getComputedStyle(el).textOverflow,"
            " hidden: getComputedStyle(el).overflowX })"
        )
        assert cut["ellipsis"] != "ellipsis" and cut["over"] <= 0, (
            f"status reading {index} is cut at {PHONE['width']}px: {cut}"
        )

def _phone_bulk_and_reviewed(p: Page, shots: Path, reviewed_item: dict) -> None:
    """The picker reaches the edge, the bulk button is full width, the reviewed row asks nothing."""
    # 10b. The picker reaches the right edge and the bulk button is a full-width
    #      one under it, counting exactly the rows that still offer *Accept*.
    bar = _box(p.locator(".archive-runbar"))
    pick = _box(p.locator("#archiveRunPick"))
    assert pick["x"] + pick["width"] >= bar["x"] + bar["width"] - 1, "the picker stops short"
    bulk = p.locator("#archiveAcceptAll")
    expect(bulk).to_have_text("Accept all (1)")
    assert abs(_box(bulk)["width"] - bar["width"]) < 1, "the bulk button is not full width"
    assert_min_target(bulk)

    # 10c. …and the row that already had its human says so and asks nothing.
    reviewed_card = p.locator(f".archive-card[data-id='{reviewed_item['id']}']")
    expect(reviewed_card.locator(".archive-state")).to_have_text("reviewed")
    expect(reviewed_card.locator(".archive-menu-toggle")).to_have_attribute("aria-label", "Details")
    expect(reviewed_card.locator(".archive-menu-word")).to_have_text("Details")   # #424: the word is shown beside the glyph
    expect(reviewed_card).to_contain_text("nothing left to do")
    # #339: a card reads at a glance in two lines (the subject with its state,
    # then who · when · where): the files and the reason wait behind its
    # Review / Details disclosure
    for card in p.locator(".archive-card").all():
        assert _box(card.locator(".archive-card-meta"))["height"] < _ONE_LINE_PX, "the card's second line wraps"
        expect(card.locator(".archive-card-why")).to_be_hidden()
        expect(card.locator(".archive-files")).to_be_hidden()
    assert_no_horizontal_overflow(p)
    assert_min_target(p.locator("#archiveRun"))
    assert_min_target(p.locator("#archiveLimit"))
    shot(p, shots / "story-24-archive-7-phone.png")

def _phone_review_menu(p: Page, base: str, run_id: int, shots: Path) -> tuple:
    """One review menu and its File it… panel, in dark. Returns the stuck and open cards."""
    # 10d. The long path the archiver failed on is folded to its last three
    #      components on screen, with the whole sentence still in the title —
    #      an absolute path is what used to push the pane sideways.
    stuck_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, STUCK_ID)}']")
    reason = stuck_card.locator(".archive-reason")
    expect(reason).to_contain_text("… 2026 › surveys › pending")
    assert UNREACHABLE in (reason.get_attribute("title") or "")

    # 10e. Open one review menu: *Review* is the same button as the three it
    #      hides, and the *File it…* panel is a phone panel — two-line
    #      candidates, one full-width field with the glyph inside it, a
    #      full-width *Archive here*, every control on its own line at the same
    #      height, nothing overlapping, nothing pushing the pane sideways.
    p.emulate_media(color_scheme="dark")
    p.evaluate("document.documentElement.dataset.theme = 'dark'")
    open_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, OPEN_ID)}']")
    expect(open_card.locator(".archive-menu-word")).to_have_text("Review")   # #424
    open_card.locator(".archive-menu-word").tap()                           # …and the word presses the toggle
    expect(open_card.locator(".archive-menu-toggle")).to_have_attribute("aria-expanded", "true")
    expect(open_card.locator(".archive-move-toggle")).to_be_visible()
    assert_min_target(open_card.locator(".archive-action"))
    shapes = open_card.locator(".archive-action").evaluate_all(ROW_VERB_SHAPE_JS)
    assert len(shapes) == 3, shapes                          # Review · Accept · File it…
    assert {s["tag"] for s in shapes} == {"BUTTON"}, shapes   # no link-styled <summary>
    for key in ("height", "font", "pad"):
        assert len({s[key] for s in shapes}) == 1, f"row actions differ in {key}: {shapes}"
    _assert_unpainted(shapes)
    open_card.locator(".archive-move-toggle").tap()
    panel = open_card.locator(".archive-move-body")
    expect(panel).to_be_visible()
    cand = panel.locator(".archive-cand").first
    name, path = _box(cand.locator(".archive-cand-name")), _box(cand.locator(".archive-cand-path"))
    assert path["y"] >= name["y"] + name["height"] - 1, "the candidate is still one line"
    assert abs(_mid_y(name) - _mid_y(_box(cand.locator(".archive-cand-score")))) < 4
    field = _box(panel.locator(".archive-other-field"))
    go = _box(panel.locator(".archive-other-go"))
    body = _box(panel)
    assert field["width"] > body["width"] - 20 and go["width"] > body["width"] - 20
    assert go["y"] >= field["y"] + field["height"] - 1, "*Archive here* is not on its own line"
    assert abs(_box(panel.locator(".archive-hint"))["height"] - field["height"]) < 1
    assert_min_target(panel.locator(".archive-other-field"))
    assert_min_target(panel.locator(".archive-other-field .folder-pick"))
    assert_min_target(panel.locator(".archive-other-go"))
    assert_min_target(panel.locator(".archive-hint"))
    assert_min_target(panel.locator(".archive-cand"))
    assert_no_overlap([
        panel.locator(".archive-other-field"),
        panel.locator(".archive-other-go"),
        panel.locator(".archive-hint"),
    ])
    assert_no_horizontal_overflow(p)
    # The panel is what this shot is for, so put it on screen and check it got
    # there — clear of the floating pill, which owns the last ~90px (rule 3 in
    # docs/validation.md: a position is asserted, never assumed).
    panel.evaluate("el => el.scrollIntoView({block: 'center'})")
    seat = _box(panel)
    assert seat["y"] >= 0 and seat["y"] + seat["height"] <= PHONE["height"] - 90, seat
    shot(p, shots / "story-24-archive-8-phone.png")
    return stuck_card, open_card

def _phone_retry_stuck(
    p: Page, inst: ArchiveInstance, shots: Path, run_id: int, stuck_card, open_card
) -> None:
    """The mail the archiver could not move offers Retry on the phone; one tap files it."""
    base = inst.base
    # 10f. The mail the archiver wrote and could not move, on the phone (#174).
    #      Its menu offers *Retry* in the same `.archive-action` shape as the
    #      rest — *Accept* is gone because it was accepted on the desktop leg,
    #      and being seen is not being finished. One tap and it is filed: the
    #      file it already had is reused, the error text goes, and the mail has
    #      left the Inbox.
    open_card.locator(".archive-menu-toggle").tap()      # close the one before it
    expect(open_card.locator(".archive-move-toggle")).to_be_hidden()
    stuck_card.locator(".archive-menu-toggle").tap()
    retry = stuck_card.locator(".archive-action[aria-label='Retry']")
    expect(retry).to_be_visible()
    stuck_shapes = stuck_card.locator(".archive-action").evaluate_all(ROW_VERB_SHAPE_JS)
    # Review · Move to… · Retry — no *Accept* on a row already seen — and
    # *Revert*, which deletes the archived file, is never a visible verb: it
    # is the last item of the card's kebab (fleet-config#1420).
    assert [s["label"] for s in stuck_shapes] == [
        "Review", "Move to…", "Retry",
    ], stuck_shapes
    assert all(s["title"] == s["label"] for s in stuck_shapes), stuck_shapes   # the tooltip
    assert {s["tag"] for s in stuck_shapes} == {"BUTTON"}, stuck_shapes
    for key in ("height", "font", "pad"):
        assert len({s[key] for s in stuck_shapes}) == 1, f"row actions differ in {key}: {stuck_shapes}"
    _assert_unpainted(stuck_shapes)
    assert_min_target(retry)
    expect(stuck_card.get_by_text("Revert", exact=True)).to_have_count(0)
    stuck_kebab = stuck_card.locator(".archive-kebab")
    assert_min_target(stuck_kebab)
    assert_no_horizontal_overflow(p)
    # the open card holds its files and reason too now (#339): seat the whole
    # card, clear of the floating pill, not just its Retry
    stuck_card.evaluate("el => el.scrollIntoView({block: 'center'})")
    seat = _box(stuck_card)
    assert seat["y"] >= 0 and seat["y"] + seat["height"] <= PHONE["height"] - 90, seat
    dismiss_toasts(p)
    shot(p, shots / "story-24-archive-10-phone.png")
    stuck_kebab.tap()
    menu_items = p.locator(".row-menu .row-menu-item")
    expect(menu_items.last).to_have_text("Revert")
    expect(menu_items.last).to_have_attribute("data-action", "revert")
    p.keyboard.press("Escape")
    expect(p.locator(".row-menu")).to_have_count(0)

    retry.tap()
    expect(stuck_card.locator(".archive-state")).to_have_text("filed")
    expect(stuck_card.locator(".archive-reason")).not_to_contain_text("move_failed")
    done = next(i for i in _items(base, run_id) if i["message_id"] == STUCK_ID)
    assert done["status"] == "archived" and done["error"] is None
    # Nothing was written and nothing re-decided: the same message, the same
    # folder, the same naming form — and the sequence the first attempt
    # allocated survives a reuse that allocates none.
    assert done["files"] == [STUCK_FILE] and done["sequence"] == "0043"
    assert calls(inst.repo)[-1] == {
        "verb": "apply", "argv": calls(inst.repo)[-1]["argv"],
        "payload": [{"message_id": STUCK_ID, "folder_path": HOUSE, "date_prefix": False}],
    }

def _phone_back_to_settings(p: Page, phone: BrowserContext, shots: Path) -> None:
    """Done goes back to the Settings list at 390; the phone context closes."""
    # 10g. Done goes back to the Settings list at 390 (#397): the row's word
    #      and the header's "needs you", the sheet's five readings behind it.
    expect(p.locator("#archiveCard .status-row")).to_have_count(5)
    p.locator("#settingsSheet .settings-sheet-done").tap()
    expect(p.locator("#settingsSheet")).to_be_hidden()
    expect(p.locator("#archiveCardMeta")).to_have_text("on")
    expect(p.locator("#homeHeadStatus")).to_contain_text("3 mails need you")
    assert_min_target(p.locator("#paneSettings [data-settings-sheet='archive']"))
    assert_no_horizontal_overflow(p)
    dismiss_toasts(p)
    # Full page, as story 09's Settings shot is: the list is taller than 844 px
    # and the floating pill sits over its last rows.
    shot(p, shots / "story-24-archive-9-phone.png", full_page=True)
    phone.close()

def _second_run(page: Page, ctx: BrowserContext, base: str) -> None:
    """A second run follows the Settings row, then both runs are history."""
    # 11. A second run, and the Settings row follows it (#397): the sheet's
    #     button goes out while the archiver works and the row beside it reads
    #     "running", then both come back on their own — the sheet follows the
    #     run and publishes the status it reads (#262) — no reload. (One run at
    #     a time is the API's answer, proven in step 4.) Left until last: a
    #     second run re-plans the same mails and would move the report the
    #     steps above read. It is waited out, so nothing races the shutdown.
    acard = open_settings_sheet(page, "archive")
    run_now = acard.locator("#archiveRun")
    expect(run_now).to_be_enabled()
    run_now.click()
    expect(page.locator("#archiveCardMeta")).to_have_text("running")
    expect(run_now).to_be_disabled()
    expect(run_now).to_be_enabled(timeout=30000)
    expect(page.locator("#archiveCardMeta")).not_to_have_text("running")
    ctx.close()

    # 12. Both runs are history now, and reading them back needs no archiver at
    #     all — the picker is the whole record. (`limit`, the bound that makes a
    #     first real run safe, is proven over the API in tests/archive/test_archive_api.py.)
    listed = _get(base, "/api/archive/runs")
    assert listed["count"] == 2 and listed["runs"][1]["planned"] == 7
