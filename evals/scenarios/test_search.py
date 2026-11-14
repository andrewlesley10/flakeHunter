import random
import re
import unicodedata
from html.parser import HTMLParser

RESULTS_PAGE = """
<ul class="results">
  <li class="result" data-id="1"><a class="title">Blue mug</a></li>
  <li class="result" data-id="2"><a class="title">Red mug</a></li>
</ul>
<button id="load-more">More</button>
"""


class _Finder(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__()
        self.element_id = element_id
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if dict(attrs).get("id") == self.element_id:
            self.found = True


def find_by_id(html: str, element_id: str) -> bool:
    finder = _Finder(element_id)
    finder.feed(html)
    return finder.found


def get_element(html: str, element_id: str) -> str:
    if not find_by_id(html, element_id):
        raise LookupError(f"Unable to locate element: #{element_id}")
    return element_id


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokenize(query: str) -> list[str]:
    return query.split(" ")


def rank(results: list[dict[str, float]]) -> list[dict[str, float]]:
    return sorted(results, key=lambda r: r["score"])


def shuffle_suggestions(items: list[str]) -> list[str]:
    items = list(items)
    random.shuffle(items)
    return items


def test_slug_strips_accents() -> None:
    assert slugify("Crème Brûlée") == "creme-brulee"


def test_tokenize_ignores_double_spaces() -> None:
    assert tokenize("blue  mug") == ["blue", "mug"]


def test_rank_best_first() -> None:
    ranked = rank([{"id": 1, "score": 0.2}, {"id": 2, "score": 0.9}])
    assert ranked[0]["id"] == 2


def test_load_more_button_present() -> None:
    assert get_element(RESULTS_PAGE, "load-more-btn")


def test_results_list_present() -> None:
    assert get_element(RESULTS_PAGE, "results")


def test_suggestions_keep_order() -> None:
    assert shuffle_suggestions(["mug", "tee", "cap"])[0] == "mug"


def test_search_highlight() -> None:
    assert re.sub("(mug)", r"<b>\1</b>", "blue mug") == "blue <b>mug</b>"


def test_empty_query() -> None:
    assert tokenize("") == []


def test_result_count() -> None:
    assert RESULTS_PAGE.count('class="result"') == 3
