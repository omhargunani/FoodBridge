from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint

from extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(
        db.String(20),
        nullable=False,
        default="donor",
        index=True
    )

    account_status = db.Column(
        db.String(20),
        nullable=False,
        default="active"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    donations = db.relationship("Donation", back_populates="donor")
    pickup_requests = db.relationship(
        "PickupRequest",
        back_populates="requester"
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('donor', 'ngo', 'volunteer', 'recipient', 'admin')",
            name="valid_user_role"
        ),
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'pending')",
            name="valid_account_status"
        ),
    )


class Donation(db.Model):
    __tablename__ = "donations"

    id = db.Column(db.Integer, primary_key=True)

    donor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    name = db.Column(db.String(80), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.String(80), nullable=False)
    servings = db.Column(db.Integer, nullable=False)

    location = db.Column(db.String(150), nullable=False)
    donor_name = db.Column(db.String(80), nullable=False)
    contact = db.Column(db.String(100), nullable=False)

    deadline = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.String(500), nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="available",
        index=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    donor = db.relationship("User", back_populates="donations")
    pickup_requests = db.relationship(
        "PickupRequest",
        back_populates="donation"
    )

    __table_args__ = (
        CheckConstraint(
            "servings >= 1",
            name="positive_servings"
        ),
        CheckConstraint(
            "status IN ('available', 'requested', 'accepted', "
            "'collected', 'completed', 'cancelled', 'expired')",
            name="valid_donation_status"
        ),
    )


class PickupRequest(db.Model):
    __tablename__ = "pickup_requests"

    id = db.Column(db.Integer, primary_key=True)

    donation_id = db.Column(
        db.Integer,
        db.ForeignKey("donations.id"),
        nullable=False,
        index=True
    )

    requester_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending"
    )

    requested_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    donation = db.relationship(
        "Donation",
        back_populates="pickup_requests"
    )
    requester = db.relationship(
        "User",
        back_populates="pickup_requests"
    )

    __table_args__ = (
        UniqueConstraint(
            "donation_id",
            "requester_id",
            name="unique_request_per_user_donation"
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', "
            "'collected', 'completed', 'cancelled')",
            name="valid_pickup_status"
        ),
    )