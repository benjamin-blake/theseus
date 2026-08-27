"""Home for TestCheckValidation and TestOwnerMetadata, relocated from the retired
tests/test_checks_registry.py monolith (Decision 169, amends Decision 104).

TestCheckValidation is the only cover of Check.__post_init__'s _VALID_OWNERS raise.
TestOwnerMetadata is what scripts/checks/registry.py's own Check docstring names as the sole
reader of owner metadata.
"""

from __future__ import annotations

import pytest

import scripts.checks.registry as registry


class TestCheckValidation:
    """Check.__post_init__'s owner validation (the _VALID_OWNERS guard)."""

    def test_invalid_owner_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="owner must be one of"):
            registry.Check(name="bogus_check", owner="not-a-real-owner")

    def test_platform_is_the_only_valid_owner(self) -> None:
        assert registry._VALID_OWNERS == ("platform",)


class TestOwnerMetadata:
    """Owner metadata correctness -- populated once per check's @register(...) call site,
    never derived from dispatch."""

    def setup_method(self) -> None:
        # registry.get_check() reads _REGISTRY, populated only after a check module has been
        # imported at least once (Decision 169's lazy-import contract) -- all_checks() imports
        # every manifest-declared module, so it is the reliable way to populate _REGISTRY here.
        registry.all_checks()
        self.all_names = tuple(sorted(registry._ALL_ENTRIES))

    def test_every_registered_check_is_platform_owned(self) -> None:
        for name in self.all_names:
            assert registry.get_check(name).owner == "platform", name

    def test_owner_metadata_is_well_typed_for_every_check(self) -> None:
        for name in self.all_names:
            check = registry.get_check(name)
            assert check.name == name
            assert isinstance(check.product_coupled, bool), name
