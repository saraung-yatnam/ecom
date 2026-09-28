# app/api/v1/admin/roles.py
"""Dynamic RBAC management: permission catalog + role CRUD.

- The permission catalog is seeded, not created here — POST/DELETE on
  permissions are intentionally absent. Admins *assign* permissions to roles.
- Role reads are visible to anyone who can assign roles (users.manage_roles)
  or manage roles (roles.manage); writes need roles.manage.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import SessionDep, require_perm
from app.models.user import User
from app.repositories import rbac as rbac_repo
from app.repositories import user as user_repo
from app.schemas.rbac import (
    PermissionRead,
    RoleCreate,
    RolePermissionRead,
    RoleUpdate,
    UserRolesUpdate,
)

router = APIRouter(prefix="/admin", tags=["Admin Roles"])


def _role_read(session: SessionDep, role) -> RolePermissionRead:
    return RolePermissionRead(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        slug=role.slug,
        description=role.description,
        is_system=role.is_system,
        permissions=rbac_repo.get_role_permission_keys(session, role.id),
        user_count=rbac_repo.count_role_users(session, role.id),
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


# ============ PERMISSIONS (catalog, read-only) ============

@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    session: SessionDep,
    current_user: User = Depends(
        require_perm("roles.manage", "users.manage_roles", require_all=False)
    ),
):
    """List the seeded permission catalog grouped client-side by module."""
    return rbac_repo.list_permissions(session)


# ============ ROLES ============

@router.get("/roles", response_model=list[RolePermissionRead])
def list_roles(
    session: SessionDep,
    current_user: User = Depends(
        require_perm("roles.manage", "users.manage_roles", require_all=False)
    ),
):
    """List all roles with their granted permission keys + user counts."""
    return [_role_read(session, role) for role in rbac_repo.list_roles(session)]


@router.post("/roles", response_model=RolePermissionRead,
             status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    session: SessionDep,
    current_user: User = Depends(require_perm("roles.manage")),
):
    """Create a custom role from catalog permission keys."""
    slug = data.slug or data.name.strip().lower().replace(" ", "-")
    try:
        role = rbac_repo.create_role(
            session,
            name=data.name,
            slug=slug,
            description=data.description,
            permission_keys=data.permission_keys,
            created_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return _role_read(session, role)


@router.get("/roles/{role_id}", response_model=RolePermissionRead)
def get_role(
    role_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("roles.manage", "users.manage_roles", require_all=False)
    ),
):
    role = rbac_repo.get_role_by_id(session, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return _role_read(session, role)


@router.put("/roles/{role_id}", response_model=RolePermissionRead)
def update_role(
    role_id: UUID,
    data: RoleUpdate,
    session: SessionDep,
    current_user: User = Depends(require_perm("roles.manage")),
):
    """Rename a role and/or REPLACE its permission set."""
    role = rbac_repo.get_role_by_id(session, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )

    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role name cannot be empty",
            )
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description
    if data.permission_keys is not None:
        try:
            rbac_repo.set_role_permissions(
                session, role, data.permission_keys
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            )
    else:
        session.add(role)
        session.commit()
        session.refresh(role)

    from datetime import datetime, timezone
    role.updated_at = datetime.now(timezone.utc)
    session.add(role)
    session.commit()
    session.refresh(role)
    return _role_read(session, role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("roles.manage")),
):
    """Delete a custom role (system roles and in-use roles are protected)."""
    role = rbac_repo.get_role_by_id(session, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    try:
        rbac_repo.delete_role(session, role)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return None


# ============ USER <-> ROLE ASSIGNMENT ============

@router.get("/users/{user_id}/roles", response_model=list[str])
def get_user_roles(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
):
    """Role slugs assigned to a user."""
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return rbac_repo.get_user_role_slugs(session, user_id)


@router.put("/users/{user_id}/roles", response_model=list[str])
def set_user_roles(
    user_id: UUID,
    data: UserRolesUpdate,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.manage_roles")),
):
    """REPLACE a user's role set with existing role slugs."""
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own roles",
        )
    roles = []
    for slug in data.role_slugs:
        role = rbac_repo.get_role_by_slug(session, slug)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown role: {slug}",
            )
        roles.append(role)
    rbac_repo.set_user_roles(
        session, user, roles, assigned_by=current_user.id
    )
    return [role.slug for role in roles]
