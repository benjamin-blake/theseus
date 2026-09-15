"""Mirror test for scripts/checks/hygiene/validate_raises_discrimination.py.

Deliberately imports NO pytest name and makes no real pytest.raises call: this module is itself
under the census's scanned tree, so a live call here would move the very numbers the census
reports. Every raises shape below is fixture SOURCE TEXT written into a tmp_path tree instead.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.checks.hygiene.validate_raises_discrimination as guard


def _module_source(body: str) -> str:
    """A fixture test module whose single function body is `body` (already indented)."""
    return "import pytest\n\n\ndef test_case():\n" + body


def _write(tmp_path: Path, source: str, name: str = "test_fixture.py") -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def _scan(tmp_path: Path, source: str, name: str = "test_fixture.py") -> list[guard.RaisesSite]:
    path = _write(tmp_path, source, name)
    with patch("scripts.checks._common.ROOT", tmp_path):
        return guard.scan_file(path)


def _hit_count(tmp_path: Path, body: str, name: str = "test_fixture.py") -> int:
    return len(guard.hits(_scan(tmp_path, _module_source(body), name)))


def _module_hit_count(tmp_path: Path, source: str, name: str = "test_fixture.py") -> int:
    return len(guard.hits(_scan(tmp_path, source, name)))


class TestFrozenRoster:
    """The roster is a frozen, collocated constant -- pinned by equality, not by size."""

    _EXPECTED = frozenset(
        {
            "AssertionError",
            "AttributeError",
            "BaseException",
            "EnvironmentError",
            "Exception",
            "IOError",
            "IndexError",
            "KeyError",
            "LookupError",
            "NameError",
            "OSError",
            "RuntimeError",
            "SystemExit",
            "TypeError",
            "ValueError",
        }
    )

    _DELIBERATELY_ABSENT = (
        "ValidationError",
        "FileNotFoundError",
        "CalledProcessError",
        "TimeoutExpired",
        "ClientError",
    )

    def test_roster_is_frozen_exactly(self) -> None:
        assert guard.BROAD_EXCEPTION_TYPES == self._EXPECTED

    def test_roster_is_an_immutable_frozenset(self) -> None:
        assert isinstance(guard.BROAD_EXCEPTION_TYPES, frozenset)

    def test_narrow_library_types_are_deliberately_absent(self) -> None:
        """The brief is a high-value target list, not universal zero -- a type naming a single
        failure mode already discriminates, so it stays out of the roster."""
        assert [name for name in self._DELIBERATELY_ABSENT if name in guard.BROAD_EXCEPTION_TYPES] == []

    def test_waiver_marker_is_a_local_free_text_token(self) -> None:
        """The `-ok:` suppression shape, not a Decision-citing authorization grammar."""
        assert guard.WAIVER_MARKER == "# raises-discrimination-ok:"
        assert "dec-" not in guard.WAIVER_MARKER


class TestTupleMembershipIsAny:
    """A tuple of types is an OR of what the site catches, so ANY roster member makes it broad.

    The ALL reading would drop every mixed tuple off the census -- including the
    (YAMLError, Exception) shape that motivates the narrowing sweep -- so the rule is pinned at
    the is_broad seam and at the scan seam together.
    """

    def test_any_member_in_the_roster_is_broad(self) -> None:
        assert guard.is_broad(("CustomError", "ValueError")) is True
        assert guard.is_broad(("ValueError", "CustomError")) is True

    def test_no_member_in_the_roster_is_not_broad(self) -> None:
        assert guard.is_broad(("CustomError", "ZeroDivisionError")) is False

    def test_empty_name_tuple_is_never_broad(self) -> None:
        assert guard.is_broad(()) is False

    def test_mixed_tuple_site_is_reported(self, tmp_path: Path) -> None:
        assert _hit_count(tmp_path, "    with pytest.raises((CustomError, ValueError)):\n        pass\n") == 1


class TestDiscriminationRule:
    """One case per arm: a broad type with none of the three suppressors is a hit, and EACH
    suppressor alone takes the site off the list."""

    def test_broad_type_with_no_suppressor_is_a_hit(self, tmp_path: Path) -> None:
        assert _hit_count(tmp_path, "    with pytest.raises(Exception):\n        pass\n") == 1

    def test_narrow_type_is_not_a_hit(self, tmp_path: Path) -> None:
        assert _hit_count(tmp_path, "    with pytest.raises(ZeroDivisionError):\n        pass\n") == 0

    def test_match_keyword_suppresses_the_hit(self, tmp_path: Path) -> None:
        assert _hit_count(tmp_path, '    with pytest.raises(Exception, match="boom"):\n        pass\n') == 0

    def test_excinfo_read_after_the_with_suppresses_the_hit(self, tmp_path: Path) -> None:
        body = "    with pytest.raises(SystemExit) as excinfo:\n        pass\n    assert excinfo.value.code == 2\n"
        assert _hit_count(tmp_path, body) == 0

    def test_bound_but_never_read_excinfo_does_not_suppress_the_hit(self, tmp_path: Path) -> None:
        """Binding alone discriminates nothing; the follow-up READ is what clears the site."""
        assert _hit_count(tmp_path, "    with pytest.raises(SystemExit) as excinfo:\n        pass\n") == 1

    def test_excinfo_read_in_a_different_function_does_not_suppress_the_hit(self, tmp_path: Path) -> None:
        source = (
            "import pytest\n\n\ndef test_a():\n"
            "    with pytest.raises(SystemExit) as excinfo:\n        pass\n\n\n"
            "def test_b():\n    assert excinfo.value.code == 0\n"
        )
        assert _module_hit_count(tmp_path, source) == 1

    def test_waiver_marker_suppresses_the_hit(self, tmp_path: Path) -> None:
        body = "    with pytest.raises(Exception):  # raises-discrimination-ok: deliberate breadth\n        pass\n"
        assert _hit_count(tmp_path, body) == 0

    def test_waiver_on_a_continuation_line_of_a_multiline_call_suppresses_the_hit(self, tmp_path: Path) -> None:
        body = (
            "    with pytest.raises(\n"
            "        Exception,\n"
            "    ):  # raises-discrimination-ok: deliberate breadth\n"
            "        pass\n"
        )
        assert _hit_count(tmp_path, body) == 0

    def test_waiver_on_the_line_above_the_call_does_not_suppress_the_hit(self, tmp_path: Path) -> None:
        """The marker waives only within the call's own lineno..end_lineno span -- the
        _assert_has_waiver placement rule of validate_test_count_coupling.py."""
        body = "    # raises-discrimination-ok: deliberate breadth\n    with pytest.raises(Exception):\n        pass\n"
        assert _hit_count(tmp_path, body) == 1

    def test_non_with_call_form_is_still_a_site(self, tmp_path: Path) -> None:
        """pytest.raises(ValueError, fn, arg) binds no excinfo, so it is reported like any other."""
        assert _hit_count(tmp_path, "    pytest.raises(ValueError, int, 'x')\n") == 1

    def test_class_body_site_is_scanned(self, tmp_path: Path) -> None:
        source = "import pytest\n\n\nclass TestThing:\n    ctx = pytest.raises(KeyError)\n"
        assert _module_hit_count(tmp_path, source) == 1


class TestCallShapeMatrix:
    """The rule is TOTAL: every pytest.raises call shape classifies without raising.

    Arm 3 is the subtle one, so its shapes are pinned here rather than in prose. It credits a
    READ of the bound name inside the SAME enclosing scope, strictly after the with-statement
    ends -- scope-local and positioned, because binding names repeat across a module (`exc_info`
    is bound a dozen times over in a single test module) and a module-wide, position-free search
    silently suppresses undiscriminating sites that never read anything back. It is a READ, not
    an assert: the repo's own helper shape ends `return exc_info.value.code` for its CALLER to
    assert, and that discriminates exactly as well. Conversely a read inside the with-body (where
    pytest has not filled the excinfo yet), a read that precedes the with-statement, and a read
    in a different function that merely reuses the binding name each leave the site reported.
    """

    _SHAPES: tuple[tuple[str, str, int], ...] = (
        ("positional broad type", "    with pytest.raises(ValueError):\n        pass\n", 1),
        ("positional narrow type", "    with pytest.raises(ZeroDivisionError):\n        pass\n", 0),
        ("tuple with a broad member", "    with pytest.raises((ZeroDivisionError, KeyError)):\n        pass\n", 1),
        ("mixed tuple of a custom and a broad type", "    with pytest.raises((CustomError, ValueError)):\n        pass\n", 1),
        ("tuple of only narrow types", "    with pytest.raises((ZeroDivisionError, StopIteration)):\n        pass\n", 0),
        ("attribute-qualified type", "    with pytest.raises(pydantic.ValidationError):\n        pass\n", 0),
        ("no argument", "    with pytest.raises():\n        pass\n", 0),
        ("keyword-only expected_exception", "    with pytest.raises(expected_exception=RuntimeError):\n        pass\n", 1),
        ("starred argument", "    with pytest.raises(*EXPECTED):\n        pass\n", 0),
        ("kwargs splat", "    with pytest.raises(**OPTIONS):\n        pass\n", 0),
        ("subscript", '    with pytest.raises(EXPECTED["kind"]):\n        pass\n', 0),
        ("match keyword", '    with pytest.raises(TypeError, match="nope"):\n        pass\n', 0),
        (
            "excinfo bound and read after the with",
            "    with pytest.raises(SystemExit) as excinfo:\n        pass\n    assert excinfo.value.code == 2\n",
            0,
        ),
        (
            "excinfo read only inside the with body",
            "    with pytest.raises(SystemExit) as excinfo:\n        print(excinfo)\n",
            1,
        ),
        (
            "excinfo name read only before the with",
            "    excinfo = _prior()\n    assert excinfo.value\n    with pytest.raises(SystemExit) as excinfo:\n        pass\n",
            1,
        ),
        (
            "binding name reused, read between the two with-statements",
            (
                "    with pytest.raises(ValueError) as excinfo:\n        pass\n    assert excinfo.value\n"
                "    with pytest.raises(KeyError) as excinfo:\n        pass\n"
            ),
            1,
        ),
        (
            "waiver marker on the call's own line",
            "    with pytest.raises(Exception):  # raises-discrimination-ok: deliberate\n        pass\n",
            0,
        ),
        (
            "waiver marker on the line above the call",
            "    # raises-discrimination-ok: deliberate\n    with pytest.raises(Exception):\n        pass\n",
            1,
        ),
    )

    _MODULE_SHAPES: tuple[tuple[str, str, int], ...] = (
        (
            "helper returns the excinfo value for its caller",
            (
                "import pytest\n\n\ndef _exit_code():\n"
                "    with pytest.raises(SystemExit) as exc_info:\n        pass\n"
                "    return exc_info.value.code\n\n\n"
                "def test_case():\n    assert _exit_code() == 2\n"
            ),
            0,
        ),
        (
            "binding name reused in a different function",
            (
                "import pytest\n\n\ndef test_a():\n"
                "    with pytest.raises(ValueError) as excinfo:\n        pass\n\n\n"
                "def test_b():\n"
                "    with pytest.raises(KeyError) as excinfo:\n        pass\n"
                "    assert excinfo.value\n"
            ),
            1,
        ),
    )

    _DESIGNED_TOTAL = 8
    _DESIGNED_MODULE_TOTAL = 1

    def test_every_call_shape_classifies_without_raising(self, tmp_path: Path) -> None:
        measured: dict[str, int] = {}
        designed: dict[str, int] = {}
        for index, (label, body, expected) in enumerate(self._SHAPES):
            measured[label] = _hit_count(tmp_path, body, f"test_shape_{index}.py")
            designed[label] = expected
        assert measured == designed
        assert sum(measured.values()) == self._DESIGNED_TOTAL, measured

    def test_every_module_level_shape_classifies_without_raising(self, tmp_path: Path) -> None:
        measured: dict[str, int] = {}
        designed: dict[str, int] = {}
        for index, (label, source, expected) in enumerate(self._MODULE_SHAPES):
            measured[label] = _module_hit_count(tmp_path, source, f"test_module_shape_{index}.py")
            designed[label] = expected
        assert measured == designed
        assert sum(measured.values()) == self._DESIGNED_MODULE_TOTAL, measured

    def test_unparseable_module_yields_no_sites(self, tmp_path: Path) -> None:
        """A parse failure is caught by name and yields no sites -- the tier dispatcher wraps a
        check in no try/except, so an escaping SyntaxError would abort the whole run."""
        assert _scan(tmp_path, "import pytest\n\ndef test_x(:\n    pass\n") == []


class TestUnreadableFilesAreCountedNotRaised:
    """Both I/O seams are guarded BY NAME and route the lost file to a PRINTED skipped count --
    a check is dispatched with no try/except, so an escaping failure aborts the whole tier."""

    def test_failure_sets_are_frozen_by_name(self) -> None:
        assert guard._READ_FAILURES == (OSError, TypeError, UnicodeDecodeError)
        assert guard._PARSE_FAILURES == (SyntaxError, ValueError, RecursionError, MemoryError)

    def test_unparseable_file_is_counted_as_skipped(self, tmp_path: Path) -> None:
        skipped: list[str] = []
        path = _write(tmp_path, "import pytest\n\ndef test_x(:\n    pass\n")
        assert guard.scan_file(path, tmp_path, skipped) == []
        assert skipped == ["tests/test_fixture.py"]

    def test_undecodable_file_is_counted_as_skipped(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        path = tests_dir / "test_bytes.py"
        path.write_bytes(b"import pytest\n# \xff\xfe\n")
        skipped: list[str] = []
        assert guard.scan_file(path, tmp_path, skipped) == []
        assert skipped == ["tests/test_bytes.py"]

    def test_absent_file_is_counted_as_skipped(self, tmp_path: Path) -> None:
        skipped: list[str] = []
        assert guard.scan_file(tmp_path / "tests" / "test_absent.py", tmp_path, skipped) == []
        assert skipped == ["tests/test_absent.py"]

    def test_symlink_loop_is_counted_as_skipped_not_raised(self, tmp_path: Path) -> None:
        """A self-referential symlink is an OSError at the read seam, never a RuntimeError out of
        a resolve() call -- the shape that would abort the tier before either guard is reached."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        loop = tests_dir / "test_loop.py"
        loop.symlink_to(loop)
        skipped: list[str] = []
        assert guard.scan_file(loop, tmp_path, skipped) == []
        assert skipped == ["tests/test_loop.py"]
        assert guard.scan_tests(tmp_path, []) == []

    def test_skipped_line_renders_the_frozen_grammar(self) -> None:
        assert guard.skipped_line([]) == "unreadable or unparseable files skipped: 0"
        assert guard.skipped_line(["tests/test_a.py"]) == "unreadable or unparseable files skipped: 1"

    def test_scan_tests_accumulates_skips_without_raising(self, tmp_path: Path) -> None:
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"), "test_ok.py")
        _write(tmp_path, "import pytest\n\ndef test_x(:\n    pass\n", "test_broken.py")
        skipped: list[str] = []
        scanned = guard.scan_tests(tmp_path, skipped)
        assert len(guard.hits(scanned)) == 1
        assert skipped == ["tests/test_broken.py"]

    def test_check_always_prints_the_skipped_count(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"), "test_ok.py")
        _write(tmp_path, "import pytest\n\ndef test_x(:\n    pass\n", "test_broken.py")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            guard.validate_raises_discrimination(failed)
        out = capsys.readouterr().out
        assert failed == []
        assert "unreadable or unparseable files skipped: 1" in out
        assert "? tests/test_broken.py" in out


class TestImportAliases:
    """Detection follows the scanned module's OWN import aliases, never a bare-name match."""

    def test_module_alias_is_followed(self, tmp_path: Path) -> None:
        source = "import pytest as pt\n\n\ndef test_x():\n    with pt.raises(Exception):\n        pass\n"
        assert _module_hit_count(tmp_path, source) == 1

    def test_direct_import_is_followed(self, tmp_path: Path) -> None:
        source = "from pytest import raises\n\n\ndef test_x():\n    with raises(Exception):\n        pass\n"
        assert _module_hit_count(tmp_path, source) == 1

    def test_aliased_direct_import_is_followed(self, tmp_path: Path) -> None:
        source = (
            "from pytest import raises as expect_raises\n\n\ndef test_x():\n    with expect_raises(Exception):\n        pass\n"
        )
        assert _module_hit_count(tmp_path, source) == 1

    def test_module_without_a_pytest_import_yields_no_sites(self, tmp_path: Path) -> None:
        source = "import os\nfrom os import path\n\n\ndef test_x():\n    with raises(Exception):\n        pass\n"
        assert _scan(tmp_path, source) == []

    def test_unrelated_pytest_attribute_call_is_not_a_site(self, tmp_path: Path) -> None:
        source = "import pytest\n\n\ndef test_x():\n    pytest.fail('nope')\n"
        assert _scan(tmp_path, source) == []


class TestScannerPrimitives:
    """The resolution helpers used by the four arms, exercised at their own seams."""

    def test_unresolvable_type_expression_yields_no_names(self) -> None:
        assert guard.type_names(None) == ()

    def test_type_text_renders_each_arity(self) -> None:
        assert guard.type_text(()) == "<unresolved>"
        assert guard.type_text(("ValueError",)) == "ValueError"
        assert guard.type_text(("ValueError", "KeyError")) == "(ValueError, KeyError)"

    def test_summary_line_renders_the_frozen_grammar(self) -> None:
        site = guard.RaisesSite(
            path="tests/test_x.py",
            lineno=3,
            type_text="Exception",
            broad=True,
            has_match=False,
            loads_excinfo=False,
            waived=False,
        )
        assert site.directory == "tests"
        assert guard.summary_line([site]) == "raises-discrimination scanned=1 hits=1 directories=1 (advisory)"

    def test_path_outside_the_root_falls_back_to_its_own_posix_text(self, tmp_path: Path) -> None:
        """A site path is a report line, never worth a raise: a file that does not sit under the
        scan root is rendered as its own posix text instead of blowing up relative_to."""
        path = _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"))
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        sites = guard.scan_file(path, outside)
        assert [site.path for site in sites] == [path.as_posix()]

    def test_hits_by_directory_counts_per_parent_directory(self, tmp_path: Path) -> None:
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"), "test_a.py")
        nested = tmp_path / "tests" / "nested"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "test_b.py").write_text(
            _module_source("    with pytest.raises(KeyError):\n        pass\n"), encoding="utf-8"
        )
        scanned = guard.scan_tests(tmp_path)
        assert guard.hits_by_directory(guard.hits(scanned)) == {"tests": 1, "tests/nested": 1}
