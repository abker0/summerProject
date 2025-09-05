from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, abort, current_app, make_response
from datetime import datetime
from io import BytesIO
import segno
from config import db
from models import Learner, Coach, CoachInvite
from datetime import date
from scheduler import integrate_new_coach
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

auth_bp = Blueprint('auth', __name__)


# --- Helpers ---
def _get_user(role: str, user_id: int):
    if role == 'learner':
        return Learner.query.get(user_id)
    if role == 'coach':
        return Coach.query.get(user_id)
    return None


def current_user():
    role = session.get('role')
    uid = session.get('user_id')
    if not role or not uid:
        return None, None
    return _get_user(role, uid), role


def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user, _ = current_user()
        if not user:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))
        return view_func(*args, **kwargs)

    return wrapper


# --- Remember-me and trusted-device cookies ---
REMEMBER_COOKIE = 'remember_me'
TRUST_COOKIE = 'trusted_device'
THIRTY_DAYS = 60 * 60 * 24 * 30


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


def _set_cookie(resp, name: str, payload: dict, max_age: int):
    token = _serializer(name).dumps(payload)
    resp.set_cookie(name, token, max_age=max_age, httponly=True, samesite='Lax')


def _clear_cookie(resp, name: str):
    resp.delete_cookie(name)


# --- Validation helpers ---
def _valid_email(email: str) -> bool:
    # Simple, pragmatic email check (avoid heavy dependencies)
    import re
    if not email:
        return False
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def _password_errors(pw: str) -> list[str]:
    errs: list[str] = []
    if not pw or len(pw) < 8:
        errs.append("be at least 8 characters")
    if not any(c.islower() for c in pw):
        errs.append("contain a lowercase letter")
    if not any(c.isupper() for c in pw):
        errs.append("contain an uppercase letter")
    if not any(c.isdigit() for c in pw):
        errs.append("contain a number")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:'\",.<>/?" for c in pw):
        errs.append("contain a special character")
    return errs


def _valid_gender(g: str) -> bool:
    return g in {"Male", "Female", "Other", "Rather not say"}


def _valid_age(n: int) -> bool:
    return 4 <= n <= 11


def _valid_grade(n: int) -> bool:
    return 0 <= n <= 5


def _valid_phone(s: str) -> bool:
    # Optional field; when provided allow digits, space, +, -, () and length 7-20
    import re
    if not s:
        return True
    return re.match(r"^[0-9 +()\-]{7,20}$", s) is not None


def _valid_emergency_contact(s: str) -> bool:
    # 7-15 chars, digits and basic separators allowed to fit DB length
    import re
    return bool(s) and len(s) <= 15 and re.match(r"^[0-9 +()\-]{7,15}$", s) is not None


# --- Register (separate pages) ---
@auth_bp.route('/register')
def register_root():
    # Redirect to learner register by default
    return redirect(url_for('auth.register_learner'))


@auth_bp.route('/register/learner', methods=['GET', 'POST'])
def register_learner():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        try:
            gender = request.form.get('gender', '')
            age = int(request.form.get('age', '0'))
            emergency_contact = request.form.get('emergency_contact', '')
            current_grade = int(request.form.get('current_grade', '0'))
        except ValueError:
            flash('Invalid learner details.', 'danger')
            return render_template('register_learner.html')

        # Basic presence
        if not first_name or not last_name or not email or not password:
            flash('Name, email, and password are required.', 'danger')
            return render_template('register_learner.html')
        # Email format
        if not _valid_email(email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('register_learner.html')
        # Password confirmation and strength
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('register_learner.html')
        pw_errs = _password_errors(password)
        if pw_errs:
            flash('Password must ' + ', '.join(pw_errs) + '.', 'danger')
            return render_template('register_learner.html')
        # Structured fields
        if not _valid_gender(gender):
            flash('Please select a valid gender option.', 'danger')
            return render_template('register_learner.html')
        if not _valid_age(age):
            flash('Age must be between 4 and 11.', 'danger')
            return render_template('register_learner.html')
        if not _valid_grade(current_grade):
            flash('Current grade must be between 0 and 5.', 'danger')
            return render_template('register_learner.html')
        if not _valid_emergency_contact(emergency_contact):
            flash('Emergency contact must be 7-15 digits (you can include spaces or -).', 'danger')
            return render_template('register_learner.html')
        if (Learner.query.filter_by(email=email).first() or
                Coach.query.filter_by(email=email).first()):
            flash('Email already in use.', 'danger')
            return render_template('register_learner.html')

        user = Learner(
            first_name=first_name,
            last_name=last_name,
            email=email,
            gender=gender,
            age=age,
            emergency_contact=emergency_contact,
            current_grade=current_grade,
        )
        user.set_password(password)
        user.ensure_2fa_secret()
        db.session.add(user)
        db.session.commit()

        session['setup_2fa_role'] = 'learner'
        session['setup_2fa_user_id'] = user.id
        flash('Learner account created. Set up your 2FA.', 'success')
        return redirect(url_for('auth.setup_2fa'))

    return render_template('register_learner.html')


@auth_bp.route('/register/coach', methods=['GET', 'POST'])
def register_coach():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        phone = request.form.get('phone', '')
        token_value = request.form.get('invite_token', '').strip()

        # Invite required
        invite = CoachInvite.query.filter_by(token=token_value).first() if token_value else None
        if not invite or not invite.is_valid():
            flash('A valid invite token is required to register as coach.', 'danger')
            return render_template('register_coach.html', token=token_value)

        if not first_name or not last_name or not email or not password:
            flash('Name, email, and password are required.', 'danger')
            return render_template('register_coach.html', token=token_value)
        if not _valid_email(email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('register_coach.html', token=token_value)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('register_coach.html', token=token_value)
        pw_errs = _password_errors(password)
        if pw_errs:
            flash('Password must ' + ', '.join(pw_errs) + '.', 'danger')
            return render_template('register_coach.html', token=token_value)
        if not _valid_phone(phone):
            flash('Please enter a valid phone number (digits, spaces, +, -, () only).', 'danger')
            return render_template('register_coach.html', token=token_value)
        if (Learner.query.filter_by(email=email).first() or
                Coach.query.filter_by(email=email).first()):
                flash('Email already in use.', 'danger')
                return render_template('register_coach.html', token=token_value)

        user = Coach(
            title=title or None,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
        )
        user.set_password(password)
        user.ensure_2fa_secret()
        db.session.add(user)
        db.session.commit()

        # Mark invite as used
        invite.used = True
        invite.used_at = datetime.utcnow()
        invite.used_by_coach_id = user.id
        db.session.commit()

        # Evenly integrate the new coach into upcoming schedule (next 4 weeks)
        try:
            integrate_new_coach(coach_id=user.id, start=date.today(), weeks=4)
        except Exception as e:
            # Non-fatal: keep registration flow working even if scheduling fails
            pass

        session['setup_2fa_role'] = 'coach'
        session['setup_2fa_user_id'] = user.id
        flash('Coach account created. Set up your 2FA.', 'success')
        return redirect(url_for('auth.setup_2fa'))

    # GET
    return render_template('register_coach.html', token=request.args.get('token', ''))


@auth_bp.route('/setup-2fa', methods=['GET', 'POST'])
def setup_2fa():
    role = session.get('setup_2fa_role')
    uid = session.get('setup_2fa_user_id')
    if not role or not uid:
        flash('No 2FA setup in progress.', 'warning')
        return redirect(url_for('auth.login'))

    user = _get_user(role, uid)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        trust_device = request.form.get('trust_device') == 'on'
        if user.verify_totp(code):
            user.two_factor_enabled = True
            db.session.commit()
            # Log them in
            session.pop('setup_2fa_role', None)
            session.pop('setup_2fa_user_id', None)
            session['role'] = role
            session['user_id'] = user.id
            resp = make_response(redirect(url_for('auth.account')))
            if trust_device:
                _set_cookie(resp, TRUST_COOKIE, {'role': role, 'user_id': user.id}, THIRTY_DAYS)
            flash('Two-factor authentication enabled.', 'success')
            return resp
        else:
            flash('Invalid 2FA code. Try again.', 'danger')

    # Ensure secret exists and show QR and manual code
    user.ensure_2fa_secret()
    db.session.commit()
    return render_template('setup_2fa.html', user=user, role=role)


@auth_bp.route('/2fa/qr')
def twofa_qr():
    role = session.get('setup_2fa_role')
    uid = session.get('setup_2fa_user_id')
    # Also allow from account enable flow
    if not role or not uid:
        role = session.get('role')
        uid = session.get('user_id')
    if not role or not uid:
        abort(404)

    user = _get_user(role, uid)
    if not user:
        abort(404)

    uri = user.provisioning_uri(issuer='HJSS')
    qr = segno.make(uri)
    buf = BytesIO()
    qr.save(buf, kind='png', scale=5)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


# Login
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role', 'learner')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me') == 'on'

        user = (Learner.query.filter_by(email=email).first() if role == 'learner'
                else Coach.query.filter_by(email=email).first())
        if not user or not user.check_password(password):
            flash('Invalid credentials.', 'danger')
            return render_template('login.html')

        # Skip 2FA if trusted device cookie matches this user and role
        token = request.cookies.get(TRUST_COOKIE)
        if token:
            try:
                data = _serializer(TRUST_COOKIE).loads(token, max_age=THIRTY_DAYS)
                if data.get('role') == role and data.get('user_id') == user.id:
                    session['role'] = role
                    session['user_id'] = user.id
                    resp = make_response(redirect(url_for('auth.account')))
                    if remember_me:
                        _set_cookie(resp, REMEMBER_COOKIE, {'role': role, 'user_id': user.id}, THIRTY_DAYS)
                    else:
                        _clear_cookie(resp, REMEMBER_COOKIE)
                    flash('Logged in on trusted device.', 'success')
                    return resp
            except (BadSignature, SignatureExpired):
                pass

        if user.two_factor_enabled:
            session['pending_2fa_role'] = role
            session['pending_2fa_user_id'] = user.id
            session['pending_remember_me'] = remember_me
            return redirect(url_for('auth.enter_2fa'))
        else:
            session['role'] = role
            session['user_id'] = user.id
            resp = make_response(redirect(url_for('auth.account')))
            if remember_me:
                _set_cookie(resp, REMEMBER_COOKIE, {'role': role, 'user_id': user.id}, THIRTY_DAYS)
            else:
                _clear_cookie(resp, REMEMBER_COOKIE)
            flash('Logged in.', 'success')
            return resp

    return render_template('login.html')


@auth_bp.route('/enter-2fa', methods=['GET', 'POST'])
def enter_2fa():
    role = session.get('pending_2fa_role')
    uid = session.get('pending_2fa_user_id')
    if not role or not uid:
        flash('No 2FA verification pending.', 'warning')
        return redirect(url_for('auth.login'))

    user = _get_user(role, uid)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        trust_device = request.form.get('trust_device') == 'on'
        if user.verify_totp(code):
            session.pop('pending_2fa_role', None)
            session.pop('pending_2fa_user_id', None)
            session['role'] = role
            session['user_id'] = user.id
            resp = make_response(redirect(url_for('auth.account')))
            if session.pop('pending_remember_me', False):
                _set_cookie(resp, REMEMBER_COOKIE, {'role': role, 'user_id': user.id}, THIRTY_DAYS)
            if trust_device:
                _set_cookie(resp, TRUST_COOKIE, {'role': role, 'user_id': user.id}, THIRTY_DAYS)
            flash('2FA verified. Logged in.', 'success')
            return resp
        else:
            flash('Invalid 2FA code.', 'danger')

    return render_template('enter_2fa.html')


# Account management
@auth_bp.route('/account', methods=['GET'])
@login_required
def account():
    user, role = current_user()
    return render_template('account.html', user=user, role=role)


@auth_bp.route('/account/enable-2fa', methods=['POST'])
@login_required
def account_enable_2fa():
    user, role = current_user()
    user.ensure_2fa_secret()
    db.session.commit()
    session['setup_2fa_role'] = role
    session['setup_2fa_user_id'] = user.id
    return redirect(url_for('auth.setup_2fa'))


@auth_bp.route('/account/disable-2fa', methods=['POST'])
@login_required
def account_disable_2fa():
    user, _ = current_user()
    user.two_factor_enabled = False
    db.session.commit()
    flash('Two-factor disabled.', 'info')
    return redirect(url_for('auth.account'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        role = request.form.get('role', 'learner')
        email = request.form.get('email', '').strip().lower()
        user = (Learner.query.filter_by(email=email).first() if role == 'learner'
                else Coach.query.filter_by(email=email).first())
        if not user:
            flash('If the account exists, continue to verification.', 'info')
            return redirect(url_for('auth.reset_password', role=role, email=email))
        if not user.two_factor_secret:
            flash('2FA is not set up for this account. Please contact an administrator.', 'warning')
            return redirect(url_for('auth.login'))
        return redirect(url_for('auth.reset_password', role=role, email=email))
    return render_template('forgot_password.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    role = request.args.get('role', 'learner')
    email = request.args.get('email', '').strip().lower()
    user = (Learner.query.filter_by(email=email).first() if role == 'learner'
            else Coach.query.filter_by(email=email).first()) if email else None

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not user:
            flash('Account not found.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        if not user.two_factor_secret:
            flash('2FA not set for this account.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        if not user.verify_totp(code):
            flash('Invalid code.', 'danger')
            return render_template('reset_password.html', role=role, email=email)
        if not new or new != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', role=role, email=email)
        pw_errs = _password_errors(new)
        if pw_errs:
            flash('Password must ' + ', '.join(pw_errs) + '.', 'danger')
            return render_template('reset_password.html', role=role, email=email)
        user.set_password(new)
        db.session.commit()
        flash('Password reset successful. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', role=role, email=email)


@auth_bp.route('/account/change-password', methods=['POST'])
@login_required
def change_password():
    user, _ = current_user()
    old = request.form.get('old_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not user.check_password(old):
        flash('Old password incorrect.', 'danger')
        return redirect(url_for('auth.account'))
    if not new or new != confirm:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('auth.account'))
    pw_errs = _password_errors(new)
    if pw_errs:
        flash('Password must ' + ', '.join(pw_errs) + '.', 'danger')
        return redirect(url_for('auth.account'))
    user.set_password(new)
    db.session.commit()
    flash('Password updated.', 'success')
    return redirect(url_for('auth.account'))


@auth_bp.route('/logout')
def logout():
    session.clear()
    resp = make_response(redirect(url_for('auth.login')))
    _clear_cookie(resp, REMEMBER_COOKIE)
    _clear_cookie(resp, TRUST_COOKIE)
    flash('Logged out.', 'info')
    return resp
