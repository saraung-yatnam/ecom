# app/repositories/rbac.py
"""Data access for dynamic RBAC (permissions, roles, assignments)."""
from uuid import UUID

from sqlalchemy import func, select
from sqlmodel import Session

from app.core.rbac_catalog import PERMISSION_KEYS
from app.models.rbac import (
    Permission,
    Role,
    RolePermissionLink,
    UserRoleLink,
)
from app.models.user import User, UserRole


# Privilege rank for the single legacy ``users.role`` column, mirroring the
# declaration order of ``UserRole`` (customer < staff < manager < admin).
# Only legacy slugs are ranked; custom role slugs rank below every legacy one.
_LEGACY_ROLE_RANK: dict[str, int] = {
    slug.value: index for index, slug in enumerate(UserRole)
}


def legacy_role_rank(slug: str) -> int:
    """Higher is more privileged; unknown/custom slugs rank lowest."""
    return _LEGACY_ROLE_RANK.get(slug, -1)


def list_permissions(session: Session) -> list[Permission]:
    result = session.execute(
        select(Permission).order_by(Permission.module, Permission.key)
    )
    return list(result.scalars().all())


def get_permission_by_key(
    session: Session, key: str
) -> Permission | None:
    result = session.execute(select(Permission).where(Permission.key == key))
    return result.scalar_one_or_none()


def validate_permission_keys(keys: list[str]) -> list[str]:
    """Return unknown keys (empty list = all valid)."""
    known = set(PERMISSION_KEYS)
    return [key for key in keys if key not in known]


def get_role_by_id(session: Session, role_id: UUID) -> Role | None:
    return session.get(Role, role_id)


def get_role_by_slug(session: Session, slug: str) -> Role | None:
    result = session.execute(select(Role).where(Role.slug == slug))
    return result.scalar_one_or_none()


def list_roles(session: Session) -> list[Role]:
    result = session.execute(select(Role).order_by(Role.name))
    return list(result.scalars().all())


def get_role_permission_keys(
    session: Session, role_id: UUID
) -> list[str]:
    result = session.execute(
        select(Permission.key)
        .join(
            RolePermissionLink,
            RolePermissionLink.permission_id == Permission.id,
        )
        .where(RolePermissionLink.role_id == role_id)
        .order_by(Permission.key)
    )
    return list(result.scalars().all())


def set_role_permissions(
    session: Session, role: Role, permission_keys: list[str]
) -> Role:
    """Replace the role's permission set (keys must be pre-validated)."""
    unknown = validate_permission_keys(permission_keys)
    if unknown:
        raise ValueError(f"Unknown permission keys: {', '.join(unknown)}")

    existing = session.execute(
        select(RolePermissionLink).where(
            RolePermissionLink.role_id == role.id
        )
    ).scalars().all()
    for link in existing:
        session.delete(link)
    session.flush()

    if permission_keys:
        perms = session.execute(
            select(Permission).where(Permission.key.in_(permission_keys))
        ).scalars().all()
        for perm in perms:
            session.add(
                RolePermissionLink(role_id=role.id, permission_id=perm.id)
            )
    session.commit()
    session.refresh(role)
    return role


def create_role(
    session: Session,
    name: str,
    slug: str,
    description: str | None,
    permission_keys: list[str],
    created_by: UUID | None = None,
    max_refund_amount=None,
) -> Role:
    unknown = validate_permission_keys(permission_keys)
    if unknown:
        raise ValueError(f"Unknown permission keys: {', '.join(unknown)}")
    if get_role_by_slug(session, slug) is not None:
        raise ValueError(f"Role slug '{slug}' already exists")

    role = Role(
        name=name,
        slug=slug,
        description=description,
        is_system=False,
        created_by=created_by,
        max_refund_amount=max_refund_amount,
    )
    session.add(role)
    session.flush()
    # Reuse the replace logic for the initial grant set.
    set_role_permissions(session, role, permission_keys)
    session.refresh(role)
    return role


def delete_role(session: Session, role: Role) -> None:
    if role.is_system:
        raise ValueError("System roles cannot be deleted")
    assigned = session.execute(
        select(func.count())
        .select_from(UserRoleLink)
        .where(UserRoleLink.role_id == role.id)
    ).scalar() or 0
    if assigned:
        raise ValueError(
            f"Cannot delete role. {assigned} user(s) still have it assigned."
        )
    links = session.execute(
        select(RolePermissionLink).where(
            RolePermissionLink.role_id == role.id
        )
    ).scalars().all()
    for link in links:
        session.delete(link)
    session.delete(role)
    session.commit()


def count_role_users(session: Session, role_id: UUID) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(UserRoleLink)
            .where(UserRoleLink.role_id == role_id)
        ).scalar()
        or 0
    )


def get_user_roles(session: Session, user_id: UUID) -> list[Role]:
    result = session.execute(
        select(Role)
        .join(UserRoleLink, UserRoleLink.role_id == Role.id)
        .where(UserRoleLink.user_id == user_id)
        .order_by(Role.name)
    )
    return list(result.scalars().all())


def get_user_role_slugs(session: Session, user_id: UUID) -> list[str]:
    result = session.execute(
        select(Role.slug)
        .join(UserRoleLink, UserRoleLink.role_id == Role.id)
        .where(UserRoleLink.user_id == user_id)
        .order_by(Role.slug)
    )
    return list(result.scalars().all())


def get_user_permissions(session: Session, user_id: UUID) -> list[str]:
    """Union of permission keys across all of the user's roles (sorted)."""
    result = session.execute(
        select(Permission.key)
        .join(
            RolePermissionLink,
            RolePermissionLink.permission_id == Permission.id,
        )
        .join(Role, Role.id == RolePermissionLink.role_id)
        .join(UserRoleLink, UserRoleLink.role_id == Role.id)
        .where(UserRoleLink.user_id == user_id)
        .order_by(Permission.key)
    )
    return sorted(set(result.scalars().all()))


def user_has_permission(
    session: Session, user_id: UUID, permission: str
) -> bool:
    result = session.execute(
        select(func.count())
        .select_from(RolePermissionLink)
        .join(
            Permission,
            Permission.id == RolePermissionLink.permission_id,
        )
        .join(Role, Role.id == RolePermissionLink.role_id)
        .join(UserRoleLink, UserRoleLink.role_id == Role.id)
        .where(
            UserRoleLink.user_id == user_id,
            Permission.key == permission,
        )
    )
    return (result.scalar() or 0) > 0


def user_security_profile(session: Session, user: User) -> dict:
    """Roles + permissions payload attached to /auth/me and admin reads.

    Falls back to the legacy ``User.role`` enum when the user has no role
    links yet (pre-backfill databases), so old frontends keep working.
    """
    slugs = get_user_role_slugs(session, user.id)
    if not slugs and user.role is not None:
        slugs = [str(getattr(user.role, "value", user.role))]
    permissions = get_user_permissions(session, user.id)
    return {"roles": sorted(slugs), "permissions": permissions}


def set_user_roles(
    session: Session,
    user: User,
    roles: list[Role],
    assigned_by: UUID | None = None,
) -> list[Role]:
    """Replace a user's role set. Keeps legacy ``User.role`` in sync
    (primary role slug, for backward compatibility with old clients)."""
    existing = session.execute(
        select(UserRoleLink).where(UserRoleLink.user_id == user.id)
    ).scalars().all()
    for link in existing:
        session.delete(link)
    session.flush()

    for role in roles:
        session.add(
            UserRoleLink(
                user_id=user.id,
                role_id=role.id,
                assigned_by=assigned_by,
            )
        )
    # Legacy display field: the HIGHEST-privilege assigned slug, so stacking a
    # read-only role (e.g. ``customer``) on top of ``manager`` can never
    # downgrade the single ``users.role`` value old clients gate on. Falls back
    # to keeping the previous value when no assigned role is a legacy slug.
    if roles:
        legacy_values = {r.value for r in type(user.role)}
        candidates = [r.slug for r in roles if r.slug in legacy_values]
        if candidates:
            primary = max(candidates, key=legacy_role_rank)
            user.role = type(user.role)(primary)
    session.add(user)
    session.commit()
    session.refresh(user)
    return roles
