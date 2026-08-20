from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.user import User
from app.repositories import address as address_repo
from app.schemas.address import AddressCreate, AddressRead, AddressUpdate


router = APIRouter(prefix="/addresses", tags=["Addresses"])


@router.get("", response_model=list[AddressRead])
def get_addresses(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Get all addresses for current user"""
    return address_repo.get_addresses_by_user(session, current_user.id)


@router.post("", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
def create_address(
    address_data: AddressCreate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Create a new address"""
    return address_repo.create_address(
        session,
        current_user.id,
        address_data.model_dump()
    )


@router.put("/{address_id}", response_model=AddressRead)
def update_address(
    address_id: UUID,
    address_data: AddressUpdate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Update an address"""
    address = address_repo.get_address_by_id(session, address_id)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    if address.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return address_repo.update_address(
        session,
        address,
        address_data.model_dump(exclude_unset=True)
    )


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Delete an address"""
    address = address_repo.get_address_by_id(session, address_id)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    if address.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if address can be deleted
    can_delete, message = address_repo.can_delete_address(session, address_id)
    
    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    
    address_repo.delete_address(session, address)
    return None


@router.post("/default/{address_id}", response_model=AddressRead)
def set_default_address(
    address_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Set an address as default"""
    address = address_repo.get_address_by_id(session, address_id)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    if address.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    address_repo.set_default_address(session, current_user.id, address_id)
    return address