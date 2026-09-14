from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Request

from .config import settings


@dataclass(frozen=True)
class AuthenticatedUser:
    uid: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    is_admin: bool = False


@dataclass(frozen=True)
class QuotaReservation:
    reservation_id: str
    user_document: str | None
    ip_document: str


def is_admin_claims(claims: dict[str, Any]) -> bool:
    return (
        claims.get("admin") is True
        or claims.get("role") == "admin"
        or str(claims.get("email") or "").casefold() in settings.admin_emails
    )


def _firebase_auth() -> Any:
    import firebase_admin
    from firebase_admin import auth

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
    return auth


async def authenticated_user(request: Request) -> AuthenticatedUser:
    if not settings.auth_required:
        return AuthenticatedUser(uid="local-development")

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in with Google to continue.")
    try:
        decoded = _firebase_auth().verify_id_token(token, check_revoked=False)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your sign-in session is invalid or expired.") from exc
    uid = decoded.get("uid") or decoded.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Your sign-in session is invalid.")
    return AuthenticatedUser(
        uid=str(uid),
        email=decoded.get("email"),
        name=decoded.get("name"),
        picture=decoded.get("picture"),
        is_admin=is_admin_claims(decoded),
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


class DailyQuota:
    def __init__(self) -> None:
        self._client: Any | None = None

    def _firestore(self) -> Any:
        if self._client is None:
            from firebase_admin import firestore

            _firebase_auth()
            self._client = firestore.client()
        return self._client

    def _day(self) -> str:
        try:
            timezone = ZoneInfo(settings.quota_timezone)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError("Configured quota timezone is unavailable.") from exc
        return datetime.now(timezone).date().isoformat()

    def _ip_hash(self, ip_address: str, day: str) -> str:
        digest = hmac.new(
            settings.ip_hash_secret.encode("utf-8"),
            f"{day}:{ip_address}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest[:32]

    def reserve(
        self,
        user: AuthenticatedUser,
        ip_address: str,
    ) -> QuotaReservation | None:
        if not settings.quota_enabled or user.is_admin:
            return None

        from google.cloud import firestore

        database = self._firestore()
        day = self._day()
        reservation_id = uuid4().hex
        ip_document = f"{day}_ip_{self._ip_hash(ip_address, day)}"
        ip_ref = database.collection("daily_analysis_quotas").document(ip_document)
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=settings.quota_reservation_minutes)
        delete_after = now + timedelta(days=8)

        @firestore.transactional
        def transaction_body(transaction: Any) -> None:
            quota_targets = ((ip_ref, "network"),)
            snapshots = [
                reference.get(transaction=transaction)
                for reference, _ in quota_targets
            ]
            for (reference, scope), snapshot in zip(
                quota_targets,
                snapshots,
                strict=True,
            ):
                if snapshot.exists:
                    record = snapshot.to_dict() or {}
                    reserved_until = record.get("reserved_until")
                    if record.get("status") == "completed" or (
                        record.get("status") == "reserved"
                        and reserved_until is not None
                        and reserved_until > now
                    ):
                        raise HTTPException(
                            status_code=429,
                            detail=(
                                "Today's free analysis has already been used for this "
                                f"{scope}. Please return tomorrow."
                            ),
                        )
                transaction.set(
                    reference,
                    {
                        "day": day,
                        "scope": scope,
                        "status": "reserved",
                        "reservation_id": reservation_id,
                        "reserved_at": now,
                        "reserved_until": expires_at,
                        "expires_at": delete_after,
                    },
                )

        transaction_body(database.transaction())
        return QuotaReservation(reservation_id, None, ip_document)

    def complete(self, reservation: QuotaReservation | None) -> None:
        self._finish(reservation, completed=True)

    def release(self, reservation: QuotaReservation | None) -> None:
        self._finish(reservation, completed=False)

    def _finish(self, reservation: QuotaReservation | None, completed: bool) -> None:
        if reservation is None:
            return
        database = self._firestore()
        from google.cloud import firestore

        references = [
            database.collection("daily_analysis_quotas").document(document_id)
            for document_id in (reservation.user_document, reservation.ip_document)
            if document_id
        ]

        @firestore.transactional
        def transaction_body(transaction: Any) -> None:
            snapshots = [reference.get(transaction=transaction) for reference in references]
            for reference, snapshot in zip(references, snapshots, strict=True):
                record = snapshot.to_dict() if snapshot.exists else None
                if not record or record.get("reservation_id") != reservation.reservation_id:
                    continue
                if completed:
                    transaction.update(
                        reference,
                        {
                            "status": "completed",
                            "completed_at": datetime.now(UTC),
                            "reserved_until": None,
                        },
                    )
                else:
                    transaction.delete(reference)

        transaction_body(database.transaction())


daily_quota = DailyQuota()
