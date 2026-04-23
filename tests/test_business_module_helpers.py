from api.routes.business_module import _is_owner_scope, _matches_staff_marker
from api.dependencies import CurrentUser


def _user(role: str, uid: int) -> CurrentUser:
    return CurrentUser(
        id=uid,
        email=f"{role}@example.com",
        organization_id=1,
        role_name=role,
        role_level=1,
        is_active=True,
    )


def test_owner_scope_for_owner_admin() -> None:
    assert _is_owner_scope(_user("owner", 1))
    assert _is_owner_scope(_user("admin", 2))
    assert not _is_owner_scope(_user("staff", 3))


def test_staff_marker_match() -> None:
    assert _matches_staff_marker("business_module:user:42", 42)
    assert not _matches_staff_marker("business_module:user:43", 42)
