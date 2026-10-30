"""routes/student_routes.py - registration, face enrollment, biometric deletion."""
import base64
import binascii

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from database.db import get_db
from models.face_recognition_model import decode_image
from services import enrollment_service as es
from services import folder_sync_service
from services import security
from services.security import current_admin, login_required
from services.settings_service import get_setting
from services.validators import ValidationError, validate_student_form

bp = Blueprint("students", __name__)


@bp.route("/students")
@login_required
def students():
    db = get_db()
    q = (request.args.get("q") or "").strip()[:60]
    dep = request.args.get("department") or None
    cls = request.args.get("class_name") or None
    return render_template("students.html", rows=es.list_students(db, q, dep, cls), q=q, department=dep or "",
                           class_name=cls or "", groups=es.distinct_groups(db))


@bp.route("/students/register", methods=["GET", "POST"])
@login_required
def register():
    form = {}
    if request.method == "POST":
        form = request.form
        try:
            data = validate_student_form(request.form)
            sid = es.create_student(get_db(), data, current_admin(), security.client_ip())
            flash("Person registered. Now capture face images.", "success")
            return redirect(url_for("students.enroll", student_id=sid))
        except (ValidationError, es.EnrollmentError) as exc:
            flash(str(exc), "danger")
    return render_template("register_student.html", form=form, groups=es.distinct_groups(get_db()))


@bp.route("/students/<int:student_id>/enroll")
@login_required
def enroll(student_id):
    db = get_db()
    s = es.get_student(db, student_id)
    if s is None:
        flash("Person not found.", "danger")
        return redirect(url_for("students.students"))
    return render_template("enroll_face.html", s=s, min_images=int(get_setting(db, "min_enroll_images")),
                           max_images=current_app.config["MAX_ENROLL_IMAGES"])


def _read_images() -> list:
    """Accepts JSON {images:[dataURL,...]} (webcam) or multipart files (upload). Photos stay in memory only."""
    limit = current_app.config["MAX_ENROLL_IMAGES"]
    side = current_app.config["MAX_IMAGE_SIDE"]
    images = []
    if request.is_json:
        raw = (request.get_json(silent=True) or {}).get("images") or []
        if not isinstance(raw, list):
            raise es.EnrollmentError("Invalid image data.")
        if len(raw) > limit:
            raise es.EnrollmentError(f"Too many images (maximum {limit}).")
        for item in raw:
            try:
                b64 = item.split(",", 1)[1] if isinstance(item, str) and "," in item else item
                images.append(decode_image(base64.b64decode(b64, validate=False), side))
            except (binascii.Error, ValueError, AttributeError, TypeError):
                images.append(None)
    else:
        files = request.files.getlist("images")
        if len(files) > limit:
            raise es.EnrollmentError(f"Too many images (maximum {limit}).")
        for f in files:
            images.append(decode_image(f.read(), side))
    return images


@bp.route("/api/students/<int:student_id>/enroll", methods=["POST"])
@login_required
def api_enroll(student_id):
    try:
        images = _read_images()
        result = es.enroll_images(get_db(), student_id, images, current_admin(), security.client_ip())
        return jsonify({"ok": True, **result, "redirect": url_for("students.students")})
    except es.EnrollmentError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        current_app.logger.error("Face model problem: %s", exc)
        return jsonify({"ok": False, "error": "The face model is not available. Check the internet connection for the first-time model download."}), 503
    except Exception:
        current_app.logger.exception("Enrollment failed")
        return jsonify({"ok": False, "error": "Unexpected server error during enrollment."}), 500


@bp.route("/students/<int:student_id>/delete-biometrics", methods=["POST"])
@login_required
def delete_biometrics(student_id):
    try:
        es.delete_biometrics(get_db(), student_id, current_admin(), security.client_ip())
        flash("All face data for this person was deleted and consent marked as withdrawn.", "success")
    except es.EnrollmentError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("students.students"))


@bp.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    try:
        es.delete_student(get_db(), student_id, current_admin(), security.client_ip())
        flash("Person, face data and attendance records were permanently deleted.", "success")
    except es.EnrollmentError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("students.students"))


@bp.route("/students/sync-folder", methods=["POST"])
@login_required
def sync_folder():
    """Enroll everybody whose photos are in the known_faces folder."""
    try:
        rep = folder_sync_service.sync(get_db(), current_app.config["KNOWN_FACES_DIR"],
                                       admin=current_admin(), ip=security.client_ip())
    except RuntimeError as exc:
        current_app.logger.error("Face model problem: %s", exc)
        flash("The face model is not available yet. Wait a minute (first-run download) and try again.", "danger")
        return redirect(url_for("students.students"))
    if not rep["results"]:
        flash("The known_faces folder has no photos yet. Add photos (see known_faces/README.txt) and try again.", "warning")
    else:
        flash(f"Folder sync finished: {rep['enrolled']} enrolled, {rep['skipped']} already done, {rep['failed']} failed.",
              "success" if not rep["failed"] else "warning")
        for r in rep["results"]:
            if r["status"] == "failed":
                flash(f"{r['label']}: {r['message']}", "danger")
    return redirect(url_for("students.students"))
