from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.wallet import Wallet
from app.schemas.wallet import WalletCreate, WalletRead, WalletUpdate

router = APIRouter()


@router.get("/", response_model=list[WalletRead])
async def list_wallets(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[Wallet]:
    result = await db.execute(select(Wallet).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.post("/", response_model=WalletRead, status_code=status.HTTP_201_CREATED)
async def create_wallet(
    payload: WalletCreate,
    db: AsyncSession = Depends(get_db),
) -> Wallet:
    wallet = Wallet(**payload.model_dump())
    db.add(wallet)
    await db.flush()
    await db.refresh(wallet)
    return wallet


@router.get("/{wallet_id}", response_model=WalletRead)
async def get_wallet(
    wallet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Wallet:
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


@router.patch("/{wallet_id}", response_model=WalletRead)
async def update_wallet(
    wallet_id: uuid.UUID,
    payload: WalletUpdate,
    db: AsyncSession = Depends(get_db),
) -> Wallet:
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wallet, field, value)

    await db.flush()
    await db.refresh(wallet)
    return wallet


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wallet(
    wallet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    await db.delete(wallet)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
