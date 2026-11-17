import os
import re
from flask import redirect, url_for, session
from flask_login import login_required, logout_user
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
)
from flask_login import (
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

from extensions import db, login_manager
from models import User, Donation, PickupRequest


# ==========================================================
# 1. APPLICATION CONFIGURATION
# ==========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "local-development-key-change-before-deployment"
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///foodbridge.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Keep the login session for up to 30 days.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

db.init_app(app)
login_manager.init_app(app)

login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"


# ==========================================================
# 2. LOGIN MANAGEMENT
# ==========================================================

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def roles_required(*allowed_roles):
    """Restrict a route to authenticated users with allowed roles."""

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):

            if not current_user.is_authenticated:
                if request.path.startswith("/api/"):
                    return jsonify(error="Please log in first."), 401

                return redirect(url_for("login"))

            if current_user.account_status != "active":
                logout_user()

                if request.path.startswith("/api/"):
                    return jsonify(error="Your account is not active."), 403

                flash("Your account is not active.", "error")
                return redirect(url_for("login"))

            if current_user.role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify(error="You do not have permission."), 403

                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("home"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


# ==========================================================
# 3. HOMEPAGE AND ROLE-BASED DASHBOARDS
# ==========================================================

@app.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    if current_user.account_status != "active":
        logout_user()
        flash("Your account is not active.", "error")
        return redirect(url_for("login"))

    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))

    # All non-admin users see the main FoodBridge website.
    return render_template("index.html")


@app.route("/admin")
@login_required
@roles_required("admin")
def admin_dashboard():
    return render_template("admin.html")

# ==========================================================
# 4. REGISTRATION
# ==========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "donor").strip().lower()

        if not name or len(name) > 80:
            flash("Enter a name between 1 and 80 characters.", "error")
            return render_template("register.html")

        if (
            not email
            or len(email) > 120
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        ):
            flash("Enter a valid email address.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Your password must contain at least 8 characters.", "error")
            return render_template("register.html")

        # Public registration must never create an administrator.
        allowed_roles = {"donor", "ngo", "volunteer", "recipient"}

        if role not in allowed_roles:
            role = "donor"

        existing_user = db.session.scalar(
            db.select(User).where(User.email == email)
        )

        if existing_user:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            account_status="active"
        )

        try:
            db.session.add(user)
            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ==========================================================
# 5. LOGIN
# ==========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.session.scalar(
            db.select(User).where(User.email == email)
        )

        if user is None or not check_password_hash(
            user.password_hash, password
        ):
            flash("Incorrect email or password.", "error")
            return render_template("login.html")

        if user.account_status != "active":
            flash("Your account is not active.", "error")
            return render_template("login.html")

        # Remember the login session across browser restarts.
        session.permanent = True
        login_user(user, remember=True)

        return redirect(url_for("home"))

    return render_template("login.html")


# ==========================================================
# 6. LOGOUT
# ==========================================================

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))



# ==========================================================
# 7. CURRENT USER API
# ==========================================================

@app.get("/api/session")
def api_session():

    if not current_user.is_authenticated:
        return jsonify(authenticated=False)

    if current_user.account_status != "active":
        logout_user()
        return jsonify(authenticated=False)

    return jsonify(
        authenticated=True,
        user={
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role
        }
    )


# ==========================================================
# 8. DONATION SERIALIZATION
# ==========================================================

def donation_json(donation):

    return {
        "id": donation.id,
        "donor_id": donation.donor_id,
        "name": donation.name,
        "category": donation.category,
        "quantity": donation.quantity,
        "servings": donation.servings,
        "location": donation.location,
        "donor": donation.donor_name,
        "contact": donation.contact,
        "deadline": donation.deadline.isoformat(),
        "notes": donation.notes or "",
        "status": donation.status,
        "createdAt": donation.created_at.isoformat()
    }


# ==========================================================
# 9. VIEW AVAILABLE DONATIONS
# ==========================================================

# ==========================================================
# 9. VIEW AVAILABLE DONATIONS
# ==========================================================

@app.get("/api/donations")
@roles_required("donor", "ngo", "recipient", "volunteer", "admin")
def api_donations():

    if current_user.role == "admin":
        donations = db.session.scalars(
            db.select(Donation).order_by(Donation.created_at.desc())
        ).all()

    else:
        donations = db.session.scalars(
            db.select(Donation)
            .where(Donation.status.in_(("available", "requested")))
            .order_by(Donation.created_at.desc())
        ).all()

    return jsonify([donation_json(item) for item in donations])

# ==========================================================
# 10. CREATE DONATION
# ==========================================================

@app.post("/api/donations")
@roles_required("donor", "admin")
def api_create_donation():

    data = request.get_json(silent=True) or {}

    required_fields = [
        "name",
        "category",
        "quantity",
        "servings",
        "location",
        "contact",
        "deadline"
    ]

    for field in required_fields:
        if data.get(field) is None or str(data[field]).strip() == "":
            return jsonify(error=f"{field} is required."), 400

    name = str(data["name"]).strip()
    category = str(data["category"]).strip()
    quantity = str(data["quantity"]).strip()
    location = str(data["location"]).strip()
    contact = str(data["contact"]).strip()
    notes = str(data.get("notes", "")).strip()

    if (
        len(name) > 80
        or len(category) > 50
        or len(quantity) > 80
        or len(location) > 150
        or len(contact) > 100
        or len(notes) > 500
    ):
        return jsonify(error="One or more fields are too long."), 400

    try:
        servings = int(data["servings"])

        deadline = datetime.fromisoformat(
            str(data["deadline"]).replace("Z", "+00:00")
        )

    except (ValueError, TypeError):
        return jsonify(error="Invalid servings or deadline."), 400

    if not 1 <= servings <= 100000:
        return jsonify(
            error="Servings must be between 1 and 100000."
        ), 400

    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

    if deadline <= datetime.utcnow():
        return jsonify(error="The safe-use deadline must be in the future."), 400

    allowed_categories = {
        "Cooked Meals",
        "Bakery",
        "Fruits & Vegetables",
        "Packaged Food",
        "Dairy",
        "Other"
    }

    if category not in allowed_categories:
        return jsonify(error="Invalid food category."), 400

    donation = Donation(
        donor_id=current_user.id,
        name=name,
        category=category,
        quantity=quantity,
        servings=servings,
        location=location,
        donor_name=current_user.name,
        contact=contact,
        deadline=deadline,
        notes=notes,
        status="available"
    )

    db.session.add(donation)
    db.session.commit()

    return jsonify(
        message="Donation published successfully.",
        donation=donation_json(donation)
    ), 201


# ==========================================================
# 11. VIEW MY DONATIONS
# ==========================================================

@app.get("/api/my/donations")
@roles_required("donor", "admin")
def api_my_donations():

    query = db.select(Donation)

    if current_user.role != "admin":
        query = query.where(Donation.donor_id == current_user.id)

    donations = db.session.scalars(
        query.order_by(Donation.created_at.desc())
    ).all()

    return jsonify([donation_json(item) for item in donations])


# ==========================================================
# 12. CANCEL DONATION
# ==========================================================

@app.post("/api/donations/<int:donation_id>/cancel")
@roles_required("donor", "admin")
def api_cancel_donation(donation_id):

    donation = db.session.get(Donation, donation_id)

    if donation is None:
        return jsonify(error="Donation not found."), 404

    if (
        current_user.role != "admin"
        and donation.donor_id != current_user.id
    ):
        return jsonify(
            error="You can only cancel your own donations."
        ), 403

    if donation.status not in ("available", "requested"):
        return jsonify(error="This donation cannot be cancelled now."), 400

    donation.status = "cancelled"

    pending_requests = db.session.scalars(
        db.select(PickupRequest).where(
            PickupRequest.donation_id == donation.id,
            PickupRequest.status == "pending"
        )
    ).all()

    for pickup in pending_requests:
        pickup.status = "cancelled"

    db.session.commit()

    return jsonify(message="Donation cancelled successfully.")


# ==========================================================
# 13. PICKUP REQUEST SERIALIZATION
# ==========================================================

def pickup_json(pickup):

    return {
        "id": pickup.id,
        "donationId": pickup.donation_id,
        "requesterId": pickup.requester_id,
        "receiver": pickup.requester.name,
        "status": pickup.status,
        "createdAt": pickup.requested_at.isoformat()
    }


# ==========================================================
# 14. REQUEST FOOD
# ==========================================================

@app.post("/api/donations/<int:donation_id>/requests")
@roles_required("ngo", "recipient", "volunteer", "admin")
def api_request_food(donation_id):

    donation = db.session.get(Donation, donation_id)

    if donation is None:
        return jsonify(error="Donation not found."), 404

    if donation.status not in ("available", "requested"):
        return jsonify(error="This food is no longer available."), 400

    if donation.deadline <= datetime.utcnow():
        return jsonify(error="The safe-use deadline has passed."), 400

    existing = db.session.scalar(
        db.select(PickupRequest).where(
            PickupRequest.donation_id == donation.id,
            PickupRequest.requester_id == current_user.id
        )
    )

    if existing:
        return jsonify(
            error="You have already requested this donation."
        ), 409

    pickup = PickupRequest(
        donation_id=donation.id,
        requester_id=current_user.id,
        status="pending"
    )

    donation.status = "requested"
    db.session.add(pickup)

    try:
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return jsonify(error="This request already exists."), 409

    return jsonify(
        message="Pickup request submitted successfully.",
        pickup=pickup_json(pickup)
    ), 201


# ==========================================================
# 15. VIEW MY PICKUP REQUESTS
# ==========================================================

@app.get("/api/my/requests")
@roles_required("ngo", "recipient", "volunteer", "admin")
def api_my_requests():

    query = db.select(PickupRequest)

    if current_user.role != "admin":
        query = query.where(
            PickupRequest.requester_id == current_user.id
        )

    requests_list = db.session.scalars(
        query.order_by(PickupRequest.requested_at.desc())
    ).all()

    return jsonify([pickup_json(item) for item in requests_list])


# ==========================================================
# 16. DONORS VIEW REQUESTS FOR THEIR DONATIONS
# ==========================================================

# ==========================================================
# 16. DONORS VIEW REQUESTS FOR THEIR DONATIONS
# ==========================================================

@app.get("/api/requests")
@roles_required("donor", "admin")
def api_donor_requests():

    query = db.select(PickupRequest).join(Donation)

    if current_user.role != "admin":
        query = query.where(
            Donation.donor_id == current_user.id
        )

    requests_list = db.session.scalars(
        query.order_by(PickupRequest.requested_at.desc())
    ).all()

    return jsonify([pickup_json(item) for item in requests_list])
# ==========================================================
# 17. ACCEPT OR REJECT PICKUP REQUEST
# ==========================================================

@app.post("/api/requests/<int:request_id>/decision")
@roles_required("donor", "admin")
def api_decide_request(request_id):

    pickup = db.session.get(PickupRequest, request_id)

    if pickup is None:
        return jsonify(error="Pickup request not found."), 404

    donation = pickup.donation

    if (
        current_user.role != "admin"
        and donation.donor_id != current_user.id
    ):
        return jsonify(error="You cannot manage this request."), 403

    data = request.get_json(silent=True) or {}
    decision = data.get("decision")

    if pickup.status != "pending":
        return jsonify(error="This request has already been processed."), 400

    if decision == "accept":

        if donation.status != "requested":
            return jsonify(error="This donation is not available."), 400

        pickup.status = "accepted"
        donation.status = "accepted"

        other_pending = db.session.scalars(
            db.select(PickupRequest).where(
                PickupRequest.donation_id == donation.id,
                PickupRequest.id != pickup.id,
                PickupRequest.status == "pending"
            )
        ).all()

        for other in other_pending:
            other.status = "rejected"

    elif decision == "reject":

        pickup.status = "rejected"

        remaining = db.session.scalar(
            db.select(db.func.count(PickupRequest.id)).where(
                PickupRequest.donation_id == donation.id,
                PickupRequest.status == "pending",
                PickupRequest.id != pickup.id
            )
        )

        if remaining == 0:
            donation.status = "available"

    else:
        return jsonify(error="Decision must be accept or reject."), 400

    db.session.commit()

    return jsonify(message=f"Pickup request {decision}ed successfully.")


# ==========================================================
# 18. MARK A PICKUP AS COMPLETED
# ==========================================================

@app.post("/api/requests/<int:request_id>/complete")
@roles_required("donor", "ngo", "recipient", "admin")
def api_complete_request(request_id):

    pickup = db.session.get(PickupRequest, request_id)

    if pickup is None:
        return jsonify(error="Pickup request not found."), 404

    donation = pickup.donation

    is_donor = (
        current_user.role == "donor"
        and donation.donor_id == current_user.id
    )

    is_receiver = (
        current_user.role in ("ngo", "recipient")
        and pickup.requester_id == current_user.id
    )

    is_admin = current_user.role == "admin"

    if not (is_donor or is_receiver or is_admin):
        return jsonify(error="You cannot complete this request."), 403

    if pickup.status != "accepted":
        return jsonify(error="Only accepted requests can be completed."), 400

    pickup.status = "completed"
    pickup.completed_at = datetime.utcnow()
    donation.status = "completed"

    db.session.commit()

    return jsonify(message="Pickup marked as completed.")


# ==========================================================
# 19. ADMIN: VIEW ALL USERS
# ==========================================================

@app.get("/api/admin/users")
@roles_required("admin")
def api_admin_users():

    users = db.session.scalars(
        db.select(User).order_by(User.created_at.desc())
    ).all()

    return jsonify([
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "account_status": user.account_status
        }
        for user in users
    ])


# ==========================================================
# 20. ADMIN: ACTIVATE OR SUSPEND USERS
# ==========================================================

@app.post("/api/admin/users/<int:user_id>/status")
@roles_required("admin")
def api_admin_user_status(user_id):

    user = db.session.get(User, user_id)

    if user is None:
        return jsonify(error="User not found."), 404

    if user.id == current_user.id:
        return jsonify(
            error="You cannot suspend your own account."
        ), 400

    data = request.get_json(silent=True) or {}
    status = data.get("status")

    if status not in ("active", "suspended"):
        return jsonify(
            error="Status must be active or suspended."
        ), 400

    user.account_status = status
    db.session.commit()

    return jsonify(message=f"User account is now {status}.")


# ==========================================================
# 21. ADMIN: VIEW PLATFORM STATISTICS
# ==========================================================

@app.get("/api/admin/summary")
@roles_required("admin")
def api_admin_summary():

    return jsonify(
        users=db.session.scalar(
            db.select(db.func.count(User.id))
        ),
        donations=db.session.scalar(
            db.select(db.func.count(Donation.id))
        ),
        requests=db.session.scalar(
            db.select(db.func.count(PickupRequest.id))
        ),
        completed=db.session.scalar(
            db.select(db.func.count(Donation.id)).where(
                Donation.status == "completed"
            )
        )
    )


# ==========================================================
# 22. DATABASE INITIALIZATION
# ==========================================================

with app.app_context():
    db.create_all()


# ==========================================================
# 23. START APPLICATION
# ==========================================================

if __name__ == "__main__":
    app.run(debug=True)