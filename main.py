# ==============================================================================
# FILE: main.py
# HOÀN CHỈNH - TÍCH HỢP ĐĂNG NHẬP, PHÂN QUYỀN ADMIN & BẢO MẬT BCRYPT 72-BYTE
# ==============================================================================

import os
import json
import logging
import base64
import asyncio
import time
import random
import hmac
import hashlib
import secrets
import re
import inspect
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Literal, Optional
from contextlib import asynccontextmanager

# Giữ log tiếng Việt hiển thị đúng trên Windows/PowerShell và các process UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass

# Thư viện Mã hóa Mật khẩu
from passlib.context import CryptContext

# Thư viện Web & API Framework
from fastapi import BackgroundTasks, FastAPI, Depends, HTTPException, APIRouter, Header, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
import math as _math


class SafeJSONResponse(JSONResponse):
    """JSON response that replaces inf/NaN with null instead of raising ValueError."""

    def render(self, content: any) -> bytes:
        return _json_dumps_safe(content).encode("utf-8")


def _json_dumps_safe(obj) -> str:
    def _default(o):
        if isinstance(o, float):
            if _math.isnan(o) or _math.isinf(o):
                return None
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    def _clean(value):
        if isinstance(value, float):
            if _math.isnan(value) or _math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {k: _clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_clean(v) for v in value)
        return value

    return json.dumps(_clean(obj), ensure_ascii=False, default=_default, allow_nan=False)

# Thư viện Cơ sở dữ liệu (SQLAlchemy)
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from database import (
    engine,
    Base,
    get_db,
    SessionLocal,
    migrate_chat_history_user_id,
    migrate_unicode_text_columns,
)
import models
import gis_service
from parcel_utils import parcel_area_sqm, validate_parcel_geometry
from seed_parcels import seed_parcels

# Thư viện Google AI (SDK google-genai)
from google import genai
from google.genai import types
import httpx

# ------------------------------------------------------------------------------
# 1. ĐỊNH NGHĨA ĐƯỜNG DẪN & CẤU HÌNH MÃ HÓA
# ------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
ADMIN_HTML_PATH = os.path.join(BASE_DIR, "admin.html")
LOGIN_HTML_PATH = os.path.join(BASE_DIR, "login.html")

# Nạp biến môi trường từ .env nếu có để IDE/terminal và service đều dùng cùng config
if os.path.exists(os.path.join(BASE_DIR, ".env")):
    try:
        with open(os.path.join(BASE_DIR, ".env"), "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass

# Bcrypt chỉ xử lý tối đa 72 byte; không cắt mật khẩu âm thầm.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 12
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_SECRET = os.environ.get("SESSION_SECRET") or os.environ.get("APP_SECRET") or secrets.token_urlsafe(32)
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "86400"))


def get_allowed_origins() -> list[str]:
    """Return explicitly configured browser origins; never use a wildcard."""
    configured = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]


def _health_database_status() -> dict:
    """Run a lightweight database probe without exposing connection details."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as error:
        logger.warning("Health check database failed: %s", type(error).__name__)
        return {"status": "error", "error": "database_unavailable"}


def _health_gis_status() -> dict:
    """Report whether the in-memory GIS data and parcel index are available."""
    try:
        feature_count = int(len(gis_service.GDF)) if gis_service.GDF is not None else 0
        parcel_count = int(len(gis_service.PARCEL_GDF)) if gis_service.PARCEL_GDF is not None else 0
        spatial_index_ready = gis_service.SPATIAL_TREE is not None
        is_ready = feature_count > 0 and parcel_count > 0
        return {
            "status": "ok" if is_ready else "error",
            "feature_count": feature_count,
            "parcel_count": parcel_count,
            "spatial_index_ready": spatial_index_ready,
            **({} if is_ready else {"error": "gis_data_not_loaded"}),
        }
    except Exception as error:
        logger.warning("Health check GIS failed: %s", type(error).__name__)
        return {
            "status": "error",
            "feature_count": 0,
            "parcel_count": 0,
            "spatial_index_ready": False,
            "error": "gis_unavailable",
        }


def get_health_status() -> dict:
    """Return non-sensitive readiness information for monitoring and diagnostics."""
    database_status = _health_database_status()
    gis_status = _health_gis_status()
    gemini_configured = client is not None and bool(api_key)
    gemini_status = {
        "status": "configured" if gemini_configured else "not_configured",
        "configured": gemini_configured,
        "model_count": len(GEMINI_MODELS),
        "models": GEMINI_MODELS,
        "tool_count": len(AI_TOOL_FUNCTIONS) if "AI_TOOL_FUNCTIONS" in globals() else 0,
    }
    overall_status = (
        "ok"
        if database_status["status"] == "ok" and gis_status["status"] == "ok"
        else "degraded"
    )
    return {
        "status": overall_status,
        "database": database_status,
        "gis": gis_status,
        "gemini": gemini_status,
    }

def _password_byte_length(password: str) -> int:
    return len(password.encode("utf-8"))


def validate_new_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
    if _password_byte_length(password) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Mật khẩu không được vượt quá {MAX_PASSWORD_BYTES} byte UTF-8.")
    return password


def hash_password(password: str) -> str:
    if _password_byte_length(password) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Mật khẩu không được vượt quá {MAX_PASSWORD_BYTES} byte UTF-8.")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Mật khẩu legacy ngắn hơn chính sách mới vẫn đăng nhập được, nhưng không
    # chấp nhận chuỗi vượt giới hạn bcrypt vì hậu tố sẽ không được xác thực.
    if _password_byte_length(plain_password) > MAX_PASSWORD_BYTES:
        return False
    return pwd_context.verify(plain_password, hashed_password)

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def create_access_token(user: models.User) -> str:
    payload = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_part = _b64url_encode(payload_bytes)
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64url_encode(signature)}"

def decode_access_token(token: str) -> dict:
    try:
        payload_part, signature_part = token.split(".", 1)
        expected_signature = hmac.new(
            SESSION_SECRET.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_encode(expected_signature), signature_part):
            raise ValueError("Invalid token signature")

        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("Token expired")
        return payload
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")

def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Thiếu token đăng nhập.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Header Authorization không hợp lệ.")
    return token

def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> models.User:
    payload = decode_access_token(_extract_bearer_token(authorization))
    user = db.query(models.User).filter(models.User.id == payload.get("user_id")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại hoặc đã bị khóa.")
    return user

def get_optional_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[models.User]:
    if not authorization:
        return None
    return get_current_user(authorization=authorization, db=db)

def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền quản trị.")
    return current_user

# Import các thuật toán GIS dùng chung; server_gis.py chỉ còn là compatibility wrapper.
from gis_service import (
    clean_text,
    load_data,
    load_geojson_features,
    loc_thua as gis_loc_thua, 
    thua_cuc_tri as gis_thua_cuc_tri, 
    tinh_tong_dien_tich as gis_tinh_tong_dien_tich,
    thua_gan as gis_thua_gan, 
    khoang_cach as gis_khoang_cach,
    tim_vi_tri_doi_tuong as gis_tim_vi_tri_doi_tuong,
)

logger = logging.getLogger("MAIN_LOGGER")
logger.setLevel(logging.INFO)

def parcel_to_feature(parcel: models.Parcel) -> dict:
    return {
        "type": "Feature",
        "geometry": json.loads(parcel.geometry_geojson),
        "properties": {
            "id": parcel.parcel_code,
            "ten": parcel.name,
            "cay_trong": parcel.crop_type,
            "dien_tich": parcel.area_sqm,
            "do_am": parcel.moisture,
            "nhiet_do": parcel.temperature,
            "ghi_chu": parcel.notes,
        },
    }


def refresh_gis_cache(db: Session) -> None:
    features = [
        parcel_to_feature(parcel)
        for parcel in db.query(models.Parcel).order_by(models.Parcel.id.asc()).all()
    ]
    # Thêm các đối tượng điểm (giếng, nhà kho) từ CSDL vào cache bản đồ
    features.extend(
        object_to_feature(obj)
        for obj in db.query(models.MapObject).order_by(models.MapObject.id.asc()).all()
    )
    load_geojson_features(features)


def parcel_feature_collection(db: Session) -> dict:
    parcels = db.query(models.Parcel).order_by(models.Parcel.id.asc()).all()
    if parcels:
        features = [parcel_to_feature(parcel) for parcel in parcels]
    else:
        data_path = os.path.join(BASE_DIR, "data.json")
        with open(data_path, "r", encoding="utf-8") as source:
            features = json.load(source).get("features", [])
    return {"type": "FeatureCollection", "features": features}


def object_to_feature(obj: models.MapObject) -> dict:
    return {
        "type": "Feature",
        "geometry": json.loads(obj.geometry_geojson),
        "properties": {
            "id": obj.object_code,
            "ten": obj.name,
            "loai": obj.object_type,
            "mo_ta": obj.description,
        },
    }


def object_feature_collection(db: Session) -> dict:
    objects = db.query(models.MapObject).order_by(models.MapObject.id.asc()).all()
    features = [object_to_feature(obj) for obj in objects]
    return {"type": "FeatureCollection", "features": features}


def parcel_summary_stats(db: Session) -> dict:
    parcels = db.query(models.Parcel).order_by(models.Parcel.id.asc()).all()
    total_parcels = len(parcels)
    total_area_sqm = sum(float(parcel.area_sqm or 0) for parcel in parcels)
    average_area_sqm = (total_area_sqm / total_parcels) if total_parcels else 0.0

    crop_counts = {}
    for parcel in parcels:
        crop_name = (parcel.crop_type or "").strip()
        if crop_name:
            crop_counts[crop_name] = crop_counts.get(crop_name, 0) + 1

    most_common_crop = None
    if crop_counts:
        crop_name, crop_count = max(crop_counts.items(), key=lambda item: (item[1], item[0]))
        most_common_crop = {"crop_type": crop_name, "count": crop_count}

    largest_parcel = max(parcels, key=lambda parcel: float(parcel.area_sqm or 0), default=None)
    newest_parcel = max(parcels, key=lambda parcel: parcel.created_at or parcel.id, default=None)

    return {
        "total_parcels": total_parcels,
        "total_area_sqm": round(total_area_sqm, 2),
        "average_area_sqm": round(average_area_sqm, 2),
        "most_common_crop": most_common_crop,
        "largest_parcel": {
            "parcel_code": largest_parcel.parcel_code,
            "name": largest_parcel.name,
            "area_sqm": round(float(largest_parcel.area_sqm or 0), 2),
        } if largest_parcel else None,
        "latest_parcel": {
            "parcel_code": newest_parcel.parcel_code,
            "name": newest_parcel.name,
            "created_at": newest_parcel.created_at.isoformat() if newest_parcel and newest_parcel.created_at else None,
        } if newest_parcel else None,
        "crop_breakdown": [
            {"crop_type": crop_name, "count": count}
            for crop_name, count in sorted(crop_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def persist_chat_result(
    *,
    user_id: Optional[int],
    user_message: str,
    response: str,
    intent: str,
    error: Optional[dict] = None,
) -> None:
    """Persist chat history after the HTTP response has been prepared."""
    db = SessionLocal()
    try:
        db.add(models.ChatHistory(
            user_id=user_id,
            user_message=user_message,
            bot_response=response,
            intent=intent,
        ))
        if error:
            safe_message = re.sub(
                r"(?i)(AIza[0-9A-Za-z_-]{20,}|Bearer\s+\S+|(?:api[_ -]?key|authorization)\s*[:=]\s*\S+)",
                "[REDACTED]",
                str(error.get("message", "")),
            )[:4000]
            db.add(models.AIErrorLog(
                user_id=user_id,
                model=(error.get("model") or "")[:100] or None,
                status_code=error.get("status_code"),
                error_type=str(error.get("type") or "GeminiRequestError")[:200],
                error_message=safe_message or "Không có nội dung lỗi từ Gemini.",
            ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Không thể ghi lịch sử chat hoặc log lỗi AI ở background.")
    finally:
        db.close()


# ------------------------------------------------------------------------------
# 2. LIFESPAN: NẠP MAP, TẠO BẢNG & TỰ ĐỘNG TẠO TÀI KHOẢN ADMIN MẶC ĐỊNH
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_data()  # NẠP DỮ LIỆU BẢN ĐỒ VÀO RAM
    
    try:
        Base.metadata.create_all(bind=engine)
        migrate_chat_history_user_id()
        migrated_columns = migrate_unicode_text_columns()
        print("[OK DATABASE] Đã kết nối CSDL và khởi tạo các bảng thành công!")
        if migrated_columns:
            print(f"[OK DATABASE] Đã chuyển {migrated_columns} cột văn bản sang Unicode NVARCHAR.")
        # Dong bo doi tuong ban do (gieng, nha kho) tu data.json vao CSDL
        try:
            seed_parcels()
        except Exception as seed_error:
            print(f"[CANH BAO] Khong the seed doi tuong ban do: {seed_error}")

        
        # Kiểm tra và tự động khởi tạo Admin mặc định nếu chưa tồn tại
        db = next(get_db())
        admin_user = db.query(models.User).filter(models.User.username == "admin").first()
        if not admin_user:
            default_admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
            if not default_admin_password:
                raise RuntimeError(
                    "Cần đặt DEFAULT_ADMIN_PASSWORD (ít nhất 12 ký tự, tối đa 72 byte UTF-8) "
                    "trước khi tạo tài khoản admin lần đầu."
                )
            validate_new_password(default_admin_password)
            default_admin = models.User(
                username="admin",
                password_hash=hash_password(default_admin_password),
                full_name="Quản Trị Viên Hệ Thống",
                role="admin",
                is_active=True
            )
            db.add(default_admin)
            db.commit()
            print("[OK AUTH] Đã tạo tài khoản admin mặc định; mật khẩu không được ghi vào log.")
        parcels = db.query(models.Parcel).count()
        if parcels:
            refresh_gis_cache(db)
        db.close()

    except Exception:
        logger.exception("Khởi tạo CSDL thất bại; dừng khởi động ứng dụng.")
        raise
        
    yield
    if client is not None:
        await client.aio.aclose()
        client.close()
    print("[INFO] Đang đóng ứng dụng...")


app = FastAPI(
    title="Hệ thống AI Bản đồ Nông nghiệp",
    lifespan=lifespan,
    default_response_class=SafeJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/api/health", summary="Kiểm tra trạng thái backend và các thành phần phụ thuộc")
def api_health():
    """Return a non-sensitive health snapshot without requiring authentication."""
    return get_health_status()


# ------------------------------------------------------------------------------
# 3. ROUTE PHỤC VỤ TRANG GIAO DIỆN WEB
# ------------------------------------------------------------------------------
@app.get("/")
async def serve_index_html():
    if os.path.exists(INDEX_HTML_PATH):
        return FileResponse(INDEX_HTML_PATH)
    return {"message": "Không tìm thấy file index.html"}

@app.get("/admin")
async def serve_admin_html():
    if os.path.exists(ADMIN_HTML_PATH):
        return FileResponse(ADMIN_HTML_PATH)
    return {"message": "Không tìm thấy file admin.html"}

@app.get("/login")
async def serve_login_html():
    if os.path.exists(LOGIN_HTML_PATH):
        return FileResponse(LOGIN_HTML_PATH)
    return {"message": "Không tìm thấy file login.html"}


# ------------------------------------------------------------------------------
# 4. API AUTHENTICATION (ĐĂNG KÝ & ĐĂNG NHẬP)
# ------------------------------------------------------------------------------
class RegisterSchema(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=72)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Họ và tên không được để trống.")
        if len(value.encode("utf-16-le")) // 2 > 100:
            raise ValueError("Họ và tên không được vượt quá 100 đơn vị UTF-16.")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", value):
            raise ValueError("Tên tài khoản chỉ được gồm chữ ASCII, số, dấu chấm, gạch dưới hoặc gạch ngang (3–50 ký tự).")
        return value

    @field_validator("password")
    @classmethod
    def enforce_password_byte_limit(cls, value: str) -> str:
        return validate_new_password(value)


class LoginSchema(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tên tài khoản không được để trống.")
        # Preserve exact legacy usernames; registration normalizes new names.
        return value


class ChangePasswordSchema(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    confirm_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)

    @field_validator("new_password", "confirm_password")
    @classmethod
    def enforce_password_policy(cls, value: str) -> str:
        return validate_new_password(value)


class DeleteAccountSchema(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)


class ParcelCreateSchema(BaseModel):
    parcel_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    crop_type: str = Field(min_length=1, max_length=100)
    geometry: dict
    moisture: Optional[float] = Field(default=None, ge=0, le=100)
    temperature: Optional[float] = Field(default=None, ge=-100, le=100)
    notes: Optional[str] = None


class ParcelUpdateSchema(BaseModel):
    parcel_code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    crop_type: Optional[str] = Field(default=None, min_length=1, max_length=100)
    geometry: Optional[dict] = None
    moisture: Optional[float] = Field(default=None, ge=0, le=100)
    temperature: Optional[float] = Field(default=None, ge=-100, le=100)
    notes: Optional[str] = None

@app.post("/api/register", summary="Đăng ký tài khoản mới")
def register_user(data: RegisterSchema, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.username == data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Tên tài khoản này đã tồn tại trên hệ thống!")
    
    new_user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role="user"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Đăng ký tài khoản thành công!", "username": new_user.username}

@app.post("/api/login", summary="Đăng nhập tài khoản")
def login_user(data: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Tên tài khoản hoặc mật khẩu không chính xác!")
    
    return {
        "message": "Đăng nhập thành công!",
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role
        }
    }


@app.post("/api/change-password", summary="Đổi mật khẩu tài khoản")
def change_password(
    data: ChangePasswordSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác.")
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Mật khẩu mới và phần xác nhận không khớp.")
    if verify_password(data.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải khác mật khẩu hiện tại.")

    current_user.password_hash = hash_password(data.new_password)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể cập nhật mật khẩu.")

    return {"message": "Đổi mật khẩu thành công. Vui lòng đăng nhập lại."}


@app.delete("/api/account", summary="Xóa tài khoản người dùng")
def delete_account(
    data: DeleteAccountSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác.")

    if current_user.role == "admin":
        active_admin_count = db.query(models.User).filter(
            models.User.role == "admin",
            models.User.is_active == True,
        ).count()
        if active_admin_count <= 1:
            raise HTTPException(status_code=400, detail="Không thể xóa Admin cuối cùng của hệ thống.")

    user_id = current_user.id
    try:
        db.query(models.ChatHistory).filter(models.ChatHistory.user_id == user_id).delete(synchronize_session=False)
        db.query(models.CropLog).filter(models.CropLog.user_id == user_id).delete(synchronize_session=False)
        db.query(models.AIErrorLog).filter(models.AIErrorLog.user_id == user_id).delete(synchronize_session=False)
        db.delete(current_user)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể xóa tài khoản và dữ liệu liên quan.")

    return {"message": "Tài khoản và dữ liệu liên quan đã được xóa thành công."}


# ------------------------------------------------------------------------------
# 5. CẤU HÌNH AI GEMINI CLIENT & TOOLS TRA CỨU GIS
# ------------------------------------------------------------------------------
def tool_loc_thua(
    dieu_kien: Optional[str] = None,
    cay_trong: Optional[str] = None,
    do_am_toi_thieu: Optional[float] = None,
    do_am_toi_da: Optional[float] = None,
    gan_doi_tuong: Optional[str] = None,
    ban_kinh_m: Optional[float] = None,
) -> str:
    """Lọc các thửa theo nhiều điều kiện kết hợp đồng thời (AND)."""
    return json.dumps(
        gis_loc_thua(
            dieu_kien=dieu_kien,
            cay_trong=cay_trong,
            do_am_toi_thieu=do_am_toi_thieu,
            do_am_toi_da=do_am_toi_da,
            gan_doi_tuong=gan_doi_tuong,
            ban_kinh_m=ban_kinh_m,
        ),
        ensure_ascii=False,
    )

def tool_thua_cuc_tri(truong: str = "dien_tich", loai: str = "max") -> str:
    return json.dumps(gis_thua_cuc_tri(truong=truong, loai=loai), ensure_ascii=False)

def tool_tinh_tong_dien_tich(
    dieu_kien: Optional[str] = None,
    danh_sach_thua: Optional[list[str]] = None,
) -> str:
    """Tính tổng diện tích các thửa đất theo điều kiện hoặc danh sách mã/tên chính xác."""
    return json.dumps(
        gis_tinh_tong_dien_tich(
            dieu_kien=dieu_kien,
            danh_sach_thua=danh_sach_thua,
        ),
        ensure_ascii=False,
    )

def tool_thua_gan(lat: float, lon: float, ban_kinh_m: float = 500.0) -> str:
    return json.dumps(gis_thua_gan(lat=lat, lon=lon, ban_kinh_m=ban_kinh_m), ensure_ascii=False)

def tool_khoang_cach(dt1: str, dt2: str) -> str:
    return json.dumps(gis_khoang_cach(dt1=dt1, dt2=dt2), ensure_ascii=False)

def tool_tim_vi_tri_doi_tuong(tu_khoa: str) -> str:
    """Tìm vị trí và tọa độ của giếng, nhà kho hoặc đối tượng bản đồ."""
    return json.dumps(gis_tim_vi_tri_doi_tuong(tu_khoa=tu_khoa), ensure_ascii=False)

def tool_du_bao_thoi_tiet(tinh_thanh: str) -> str:
    """Lấy dự báo thời tiết cho thành phố/cỉnh qua web search.

    Tuân theo WEB LOOKUP RULES từ SYSTEM_PROMPT:
    - Ưu tiên official sources đã cấu hình
    - Fallback về web search chuẩn
    - Bắt buộc kèm "Nguồn tham khảo": title, URL, access_time
    - Nếu không có source đáng tin cậy: nói rõ không thể xác minh
    """
    query = f"thời tiết {tinh_thanh} hôm nay dự báo"
    try:
        raw = tool_web_search(query)
        results = json.loads(raw)
    except Exception:
        return _weather_error(tinh_thanh, "Không thể tra cứu web")

    # 1. Tách official sources (được đánh tag official=True trong _perform_web_search)
    official_sources: list[dict] = []
    other_sources: list[dict] = []

    # results có thể là dict (từ _perform_web_search) hoặc list
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except Exception:
            results = {}

    # Trích xuất danh sách sources từ kết quả
    sources_list: list[dict] = []
    if isinstance(results, dict):
        sources_list = results.get("sources", []) or []
    elif isinstance(results, list):
        sources_list = results

    for r in sources_list:
        if isinstance(r, dict) and r.get("official"):
            official_sources.append(r)
        elif isinstance(r, dict):
            other_sources.append(r)

    # Ưu tiên official sources
    selected = official_sources if official_sources else other_sources

    if not selected:
        return _weather_error(tinh_thanh, "Không tìm thấy nguồn thời tiết đáng tin cậy")

    # Lấy snippet/title/URL phổ biến nhất
    best = selected[0]
    title = best.get("title") or best.get("Heading") or f"Thời tiết {tinh_thanh}"
    snippet = best.get("snippet") or best.get("AbstractText") or ""
    url = best.get("url") or best.get("AbstractURL") or ""

    # Format thời gian truy cập
    access_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Xây dựng câu trả lời có nguồn tham khảo
    response_parts: list[str] = []
    response_parts.append(f"**📍 Thời tiết {tinh_thanh}**")
    if snippet:
        response_parts.append(snippet)
    else:
        response_parts.append(f"*Thông tin thời tiết cho {tinh_thanh} (dữ liệu hiện tại)*")

    # Nguồn tham khảo - luôn包含 URL và access_time dù source có hay không
    response_parts.append(f"\n**Nguồn tham khảo:**")
    if url:
        response_parts.append(f"• Nguồn: {title}")
        response_parts.append(f"• URL: {url}")
    else:
        response_parts.append(f"• Nguồn: {title} (không có URL khả dụng)")
        response_parts.append(f"• URL: (không có URL khả dụng)")
    response_parts.append(f"• Truy cập: {access_time}")

    # Footer note about verification
    response_parts.append(f"\n*Lưu ý: Thời tiết thay đổi nhanh; vui lòng kiểm tra nguồn chính thức cập nhật thường.")

    return "\n".join(response_parts)


def _weather_error(tinh_thanh: str, reason: str) -> str:
    """Trả về message lỗi thời tiết có format đồng nhất."""
    access_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return (
        f"**📍 Thời tiết {tinh_thanh}**\n"
        f"❌ {reason}\n"
        f"\n**Nguồn tham khảo:**\n"
        f"• Không có nguồn dữ liệu thời tiết chính thức có thể truy cập.\n"
        f"• URL: (không có URL khả dụng)\n"
        f"• Truy cập: {access_time}\n"
        f"*Hệ thống hiện quản lý dữ liệu GIS/Nông trại; thông tin thời tiết cần tra cứu ngoài hệ thống.*"
    )

def tool_tra_cuu_gia_nong_san(san_pham: str, tinh_thanh: Optional[str] = None) -> str:
    dia_ban = f" tại {tinh_thanh}" if tinh_thanh else ""
    return f"Chưa có nguồn dữ liệu giá nông sản được tích hợp nên không thể cung cấp giá {san_pham}{dia_ban}."


WEB_SEARCH_TIMEOUT_SECONDS = max(1.0, float(os.environ.get("WEB_SEARCH_TIMEOUT_SECONDS", "6")))
WEB_SEARCH_MAX_RESULTS = max(1, min(8, int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "5"))))
WEB_SEARCH_CACHE_TTL_SECONDS = max(0, int(os.environ.get("WEB_SEARCH_CACHE_TTL_SECONDS", "300")))
WEB_SEARCH_CACHE_MAX_ENTRIES = max(10, min(500, int(os.environ.get("WEB_SEARCH_CACHE_MAX_ENTRIES", "100"))))
WEB_SEARCH_MAX_RESPONSE_BYTES = max(32_000, min(2_000_000, int(os.environ.get("WEB_SEARCH_MAX_RESPONSE_BYTES", "500000"))))
WEB_SEARCH_MAX_QUERY_LENGTH = 300
_web_search_cache: dict[str, tuple[float, str]] = {}


# Vietnam city coordinates for Open-Meteo geocoding
_VIETNAM_CITY_COORDS: dict[str, tuple[float, float]] | None = None

def _load_vietnam_coords() -> dict[str, tuple[float, float]]:
    """Load Vietnam city coordinates for Open-Meteo API geocoding."""
    if _VIETNAM_CITY_COORDS is not None:
        return _VIETNAM_CITY_COORDS
    # Major Vietnam cities approximate coordinates
    coords = {
        "Hà Nội": (21.0278, 105.8505),
        "Thành phố Hồ Chí Minh": (10.8246, 106.6297),
        "Đà Nẵng": (16.0544, 108.2022),
        "Cần Thơ": (10.0682, 105.8302),
        "Hải Phòng": (20.8387, 106.6860),
        "Thái Bình": (20.4567, 106.3313),
        "Thanh Hóa": (19.8074, 105.7311),
        "Huế": (16.4683, 107.5908),
        "Nghệ An": (18.7895, 105.2376),
        "Quảng Ninh": (20.9804, 107.4252),
        "Bắc Ninh": (21.1709, 106.0822),
        "Bắc Giang": (21.2732, 106.0152),
        "Lạng Sơn": (21.8626, 106.7891),
        "Lào Cai": (22.4911, 103.9450),
        "Yên Bái": (21.7203, 104.9354),
        "Hoà Bình": (20.8182, 105.3702),
        "Vinh": (18.8034, 105.6858),
        "Ninh Bình": (20.2510, 105.9573),
        "Bà Rịa - Vũng Tàu": (10.7398, 107.1265),
        "Kiên Giang": (10.3215, 105.0622),
        "Cà Mau": (9.1768, 105.1524),
        "Kon Tum": (14.3521, 108.0277),
        "Lâm Đồng": (11.9640, 108.4482),
        "Đắk Lắk": (12.2785, 108.0367),
        "All other": (16.0, 108.0),  # default fallback
    }
    _VIETNAM_CITY_COORDS = coords
    return coords


# Vietnam city coordinates for Open-Meteo geocoding


def _load_vietnam_coords() -> dict[str, tuple[float, float]]:
    """Load Vietnam city coordinates for Open-Meteo API geocoding."""
    # Major Vietnam cities approximate coordinates
    coords = {
        "Hà Nội": (21.0278, 105.8505),
        "Thành phố Hồ Chí Minh": (10.8246, 106.6297),
        "Đà Nẵng": (16.0544, 108.2022),
        "Cần Thơ": (10.0682, 105.8302),
        "Hải Phòng": (20.8387, 106.6860),
        "Thái Bình": (20.4567, 106.3313),
        "Thanh Hóa": (19.8074, 105.7311),
        "Huế": (16.4683, 107.5908),
        "Nghệ An": (18.7895, 105.2376),
        "Quảng Ninh": (20.9804, 107.4252),
        "Bắc Ninh": (21.1709, 106.0822),
        "Bắc Giang": (21.2732, 106.0152),
        "Lạng Sơn": (21.8626, 106.7891),
        "Lào Cai": (22.4911, 103.9450),
        "Yên Bái": (21.7203, 104.9354),
        "Hoà Bình": (20.8182, 105.3702),
        "Vinh": (18.8034, 105.6858),
        "Ninh Bình": (20.2510, 105.9573),
        "Bà Rịa - Vũng Tàu": (10.7398, 107.1265),
        "Kiên Giang": (10.3215, 105.0622),
        "Cà Mau": (9.1768, 105.1524),
        "Kon Tum": (14.3521, 108.0277),
        "Lâm Đồng": (11.9640, 108.4482),
        "Đắk Lắk": (12.2785, 108.0367),
        "All other": (16.0, 108.0),  # default fallback
    }
    return coords


def _official_web_sources() -> list[dict]:
    """Load official source endpoint templates from JSON configuration.
    
    Example: [{"url": "https://example.gov/search?q={query}", "title": "Example", "domain": "example.gov"}]
    The endpoint may return JSON with `results` or an RSS/Atom XML document.
    
    Built-in defaults (can be overridden by WEB_OFFICIAL_SOURCES_JSON env var):
    - Open-Meteo: free, no-auth weather API
    - WTTR.in: text-based weather fallback
    - OpenWeatherMap: requires OPENWEATHER_API_KEY env var
    """
    # Try env var override first
    env_raw = os.environ.get("WEB_OFFICIAL_SOURCES_JSON", "").strip()
    if env_raw:
        try:
            entries = json.loads(env_raw)
            if isinstance(entries, list):
                return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("url"), str)]
        except json.JSONDecodeError:
            logger.warning("WEB_OFFICIAL_SOURCES_JSON is not valid JSON, using defaults")
    
    # Built-in defaults
    return [
        # Open-Meteo: free, no-auth weather API with coordinates
        {
            "url": "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true",
            "title": "Open-Meteo Weather",
            "domain": "open-meteo.com",
            "requires_geocoding": True,
        },
        # WTTR.in: text-based weather, good fallback
        {
            "url": "https://wttr.in/{city}?format=j1",
            "title": "WTTR.in Weather",
            "domain": "wttr.in",
            "requires_geocoding": False,
        },
        # OpenWeatherMap: requires API key, good for Vietnam data
        {
            "url": "https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=vi",
            "title": "OpenWeatherMap Vietnam",
            "domain": "openweathermap.org",
            "requires_geocoding": False,
            "api_key": os.environ.get("OPENWEATHER_API_KEY", ""),
        },
    ]


def _safe_source_url(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    url = value.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url[:1000]


def _source_is_official(url: str, configured_domain: Optional[str] = None) -> bool:
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    domain = (configured_domain or "").lower().strip().lstrip(".")
    return bool(domain and (hostname == domain or hostname.endswith("." + domain)))


def _configured_source_domain(configured: dict) -> str:
    explicit = str(configured.get("domain") or "").strip()
    if explicit:
        return explicit
    parsed = urllib.parse.urlparse(str(configured.get("url") or ""))
    return parsed.hostname or ""


def _normalize_web_result(item: dict, *, official: bool, fallback_title: str = "") -> Optional[dict]:
    url = _safe_source_url(item.get("url") or item.get("link") or item.get("href"))
    if not url:
        return None
    title = str(item.get("title") or item.get("name") or fallback_title or url).strip()[:300]
    snippet = str(item.get("snippet") or item.get("description") or item.get("text") or "").strip()[:600]
    return {
        "title": title,
        "url": url,
        "publisher": str(item.get("publisher") or item.get("source") or "").strip()[:160],
        "snippet": snippet,
        "official": official,
    }


def _parse_official_payload(payload: object, *, configured: dict) -> list[dict]:
    domain = _configured_source_domain(configured)
    fallback_title = str(configured.get("title") or "Nguồn chính thức")

    # Xử lý payload dạng danh sách kết quả (API tìm kiếm)
    if isinstance(payload, dict):
        candidates = payload.get("results") or payload.get("items") or payload.get("data") or []
    elif isinstance(payload, list):
        candidates = payload
    else:
        candidates = []

    if isinstance(candidates, list) and candidates:
        output = []
        for item in candidates:
            if isinstance(item, dict):
                normalized = _normalize_web_result(
                    item,
                    official=True,
                    fallback_title=fallback_title,
                )
                if normalized and _source_is_official(normalized["url"], domain):
                    output.append(normalized)
        if output:
            return output

    # Xử lý phản hồi thời tiết từ Open-Meteo (current_weather)
    if isinstance(payload, dict) and "current_weather" in payload:
        cw = payload["current_weather"]
        lat = payload.get("latitude", "")
        lon = payload.get("longitude", "")
        temp = cw.get("temperature", "N/A")
        windspeed = cw.get("windspeed", "N/A")
        weathercode = cw.get("weathercode", "")
        snippet = f"Nhiệt độ: {temp}°C, gió: {windspeed} km/h (mã thời tiết: {weathercode})"
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        normalized = _normalize_web_result(
            {"title": f"{fallback_title} ({lat}, {lon})", "url": url, "snippet": snippet},
            official=True,
            fallback_title=fallback_title,
        )
        if normalized and _source_is_official(normalized["url"], domain):
            return [normalized]

    # Xử lý phản hồi thời tiết từ WTTR.in (current_condition)
    if isinstance(payload, dict) and "current_condition" in payload:
        conditions = payload.get("current_condition", [])
        if isinstance(conditions, list) and conditions:
            c = conditions[0]
            temp = c.get("temp_C", "N/A")
            humidity = c.get("humidity", "N/A")
            desc = c.get("weatherDesc", [{}])[0].get("value", "") if isinstance(c.get("weatherDesc"), list) else ""
            snippet = f"Nhiệt độ: {temp}°C, độ ẩm: {humidity}%{f', {desc}' if desc else ''}"
            # Lấy tên khu vực từ request
            area = ""
            request = payload.get("request", [])
            if isinstance(request, list) and request:
                area = request[0].get("query", "")
            url = f"https://wttr.in/{urllib.parse.quote_plus(area)}?format=j1" if area else "https://wttr.in/?format=j1"
            normalized = _normalize_web_result(
                {"title": f"{fallback_title} ({area})", "url": url, "snippet": snippet},
                official=True,
                fallback_title=fallback_title,
            )
            if normalized and _source_is_official(normalized["url"], domain):
                return [normalized]

    # Xử lý phản hồi thời tiết từ OpenWeatherMap (weather)
    if isinstance(payload, dict) and "weather" in payload and "main" in payload:
        weather_list = payload.get("weather", [])
        main = payload.get("main", {})
        desc = ""
        if isinstance(weather_list, list) and weather_list:
            desc = weather_list[0].get("description", "")
        temp = main.get("temp", "N/A")
        humidity = main.get("humidity", "N/A")
        city = payload.get("name", "")
        snippet = f"Nhiệt độ: {temp}°C, độ ẩm: {humidity}%{f', {desc}' if desc else ''}"
        url = f"https://api.openweathermap.org/data/2.5/weather?q={urllib.parse.quote_plus(city)}&units=metric&lang=vi"
        normalized = _normalize_web_result(
            {"title": f"{fallback_title} ({city})", "url": url, "snippet": snippet},
            official=True,
            fallback_title=fallback_title,
        )
        if normalized and _source_is_official(normalized["url"], domain):
            return [normalized]

    return []


def _parse_official_xml(payload: bytes, *, configured: dict) -> list[dict]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    output = []
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        values = {}
        for child in list(item):
            child_tag = child.tag.rsplit("}", 1)[-1].lower()
            text = (child.text or "").strip()
            if child_tag == "link" and not text:
                text = str(child.attrib.get("href") or "")
            values[child_tag] = text
        normalized = _normalize_web_result(
            {"title": values.get("title"), "url": values.get("link") or values.get("guid"), "snippet": values.get("description") or values.get("summary")},
            official=True,
            fallback_title=str(configured.get("title") or "Nguồn chính thức"),
        )
        if normalized and _source_is_official(normalized["url"], _configured_source_domain(configured)):
            output.append(normalized)
    return output


# Vietnam city coordinates for Open-Meteo geocoding

def _load_vietnam_coords() -> dict[str, tuple[float, float]]:
    """Load Vietnam city coordinates for Open-Meteo API geocoding."""
    # Major Vietnam cities approximate coordinates
    coords = {
        "Hà Nội": (21.0278, 105.8505),
        "Thành phố Hồ Chí Minh": (10.8246, 106.6297),
        "Đà Nẵng": (16.0544, 108.2022),
        "Cần Thơ": (10.0682, 105.8302),
        "Hải Phòng": (20.8387, 106.6860),
        "Thái Bình": (20.4567, 106.3313),
        "Thanh Hóa": (19.8074, 105.7311),
        "Huế": (16.4683, 107.5908),
        "Nghệ An": (18.7895, 105.2376),
        "Quảng Ninh": (20.9804, 107.4252),
        "Bắc Ninh": (21.1709, 106.0822),
        "Bắc Giang": (21.2732, 106.0152),
        "Lạng Sơn": (21.8626, 106.7891),
        "Lào Cai": (22.4911, 103.9450),
        "Yên Bái": (21.7203, 104.9354),
        "Hoà Bình": (20.8182, 105.3702),
        "Vinh": (18.8034, 105.6858),
        "Ninh Bình": (20.2510, 105.9573),
        "Bà Rịa - Vũng Tàu": (10.7398, 107.1265),
        "Kiên Giang": (10.3215, 105.0622),
        "Cà Mau": (9.1768, 105.1524),
        "Kon Tum": (14.3521, 108.0277),
        "Lâm Đồng": (11.9640, 108.4482),
        "Đắk Lắk": (12.2785, 108.0367),
        "All other": (16.0, 108.0),  # default fallback
    }
    return coords


def _extract_city_from_query(query: str, vietnam_coords: dict) -> str:
    """Trích xuất tên thành phố từ truy vấn tìm kiếm thời tiết.

    Loại bỏ các từ khóa phổ biến (thời tiết, hôm nay, dự báo...) và
    thử khớp với tên thành phố Việt Nam có sẵn trong vietnam_coords.
    """
    query_lower = query.lower().strip()

    # Thử khớp tên thành phố Việt Nam trong truy vấn
    for city_name in vietnam_coords:
        if city_name.lower() in query_lower:
            return city_name

    # Nếu không khớp, loại bỏ từ khóa thời tiết phổ biến
    words_to_remove = [
        "thời tiết", "hôm nay", "dự báo", "tỉnh", "thành phố", "tp",
        "hà", "phố", "hồ", "chí", "minh",
    ]
    cleaned = query_lower
    for word in words_to_remove:
        cleaned = cleaned.replace(word, "").strip()
    # Loại bỏ khoảng trắng dư
    cleaned = " ".join(cleaned.split())
    return cleaned if cleaned else query


def _perform_web_search(query: str) -> dict:
    normalized_query = " ".join(str(query or "").split())[:WEB_SEARCH_MAX_QUERY_LENGTH]
    if not normalized_query:
        return {"answer": "Không có truy vấn tìm kiếm.", "sources": [], "warning": "empty_query"}
    cache_key = normalized_query.casefold()
    now = time.monotonic()
    cached = _web_search_cache.get(cache_key)
    if cached and now - cached[0] <= WEB_SEARCH_CACHE_TTL_SECONDS:
        return json.loads(cached[1])

    sources: list[dict] = []
    official_configs = _official_web_sources()
    with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": "AgriMapAI/1.0"}) as http:
        for configured in official_configs[:3]:
            template = configured.get("url", "")
            requires_geocoding = configured.get("requires_geocoding", False)
            api_key = configured.get("api_key", "")

            # Skip OpenWeatherMap if no API key configured
            if "{api_key}" in template and not api_key:
                continue

            # Trích xuất tên thành phố từ query (loại bỏ từ khóa thời tiết)
            vietnam_coords = _load_vietnam_coords()
            city_name = _extract_city_from_query(normalized_query, vietnam_coords)

            # Build endpoint: for geocoding-required APIs, resolve city coords first
            if requires_geocoding:
                # Try Vietnam-specific lookup first
                if city_name in vietnam_coords:
                    lat, lon = vietnam_coords[city_name]
                    endpoint = template.format(lat=lat, lon=lon)
                else:
                    # Geocoding failed - skip this source, try next one
                    continue
            else:
                # For non-geocoding sources, use clean city name
                # Pass all possible placeholders so templates with {city}, {query}, {api_key}, etc. work
                endpoint = template.format(
                    city=urllib.parse.quote_plus(city_name),
                    query=urllib.parse.quote_plus(normalized_query),
                    api_key=api_key,
                )

            if not _safe_source_url(endpoint):
                continue
            try:
                response = http.get(endpoint)
                response.raise_for_status()
                if len(response.content) > WEB_SEARCH_MAX_RESPONSE_BYTES:
                    raise ValueError("Official web response exceeded the configured size limit")
                content_type = response.headers.get("content-type", "").lower()
                if "xml" in content_type or response.text.lstrip().startswith("<"):
                    sources.extend(_parse_official_xml(response.content, configured=configured))
                else:
                    sources.extend(_parse_official_payload(response.json(), configured=configured))
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
                logger.info("Official web source failed: %s - %s", configured.get("title") or configured.get("url"), str(e)[:80])
            if len(sources) >= WEB_SEARCH_MAX_RESULTS:
                break

        if not sources:
            try:
                response = http.get(
                    "https://api.duckduckgo.com/",
                    params={"q": normalized_query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                response.raise_for_status()
                if len(response.content) > WEB_SEARCH_MAX_RESPONSE_BYTES:
                    raise ValueError("Fallback web response exceeded the configured size limit")
                payload = response.json()
                abstract = _normalize_web_result(
                    {"url": payload.get("AbstractURL"), "title": payload.get("Heading"), "snippet": payload.get("AbstractText"), "publisher": "DuckDuckGo"},
                    official=False,
                )
                if abstract:
                    sources.append(abstract)
                for topic in payload.get("RelatedTopics", []) if isinstance(payload, dict) else []:
                    if not isinstance(topic, dict):
                        continue
                    item = _normalize_web_result(topic, official=False, fallback_title="Kết quả tìm kiếm web")
                    if item:
                        sources.append(item)
                    if len(sources) >= WEB_SEARCH_MAX_RESULTS:
                        break
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                logger.info("Fallback web search failed")

    unique = []
    seen_urls = set()
    for source in sources:
        if source["url"] in seen_urls:
            continue
        seen_urls.add(source["url"])
        source["accessed_at"] = datetime.now(timezone.utc).isoformat()
        unique.append(source)
    result = {
        "answer": f"Đã tìm thấy {len(unique)} nguồn phù hợp cho truy vấn: {normalized_query}.",
        "sources": unique[:WEB_SEARCH_MAX_RESULTS],
        "official_sources_used": any(source["official"] for source in unique),
        "warning": None if unique else "Không tìm thấy nguồn có URL hợp lệ để xác minh thông tin.",
    }
    if WEB_SEARCH_CACHE_TTL_SECONDS:
        if len(_web_search_cache) >= WEB_SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(_web_search_cache, key=lambda key: _web_search_cache[key][0])
            _web_search_cache.pop(oldest_key, None)
        _web_search_cache[cache_key] = (now, json.dumps(result, ensure_ascii=False))
    return result


def tool_web_search(query: str) -> str:
    """Tra cứu web, ưu tiên endpoint chính thức đã cấu hình rồi fallback sang tìm kiếm web."""
    return json.dumps(_perform_web_search(query), ensure_ascii=False)

GEMINI_REQUEST_TIMEOUT_SECONDS = 45
GEMINI_MODEL_REQUEST_TIMEOUT_SECONDS = max(
    1,
    int(os.environ.get(
        "GEMINI_MODEL_REQUEST_TIMEOUT_SECONDS",
        str(GEMINI_REQUEST_TIMEOUT_SECONDS),
    )),
)
GEMINI_HTTP_TIMEOUT_MILLISECONDS = 45_000
GEMINI_SDK_RETRY_ATTEMPTS = max(1, int(os.environ.get("GEMINI_SDK_RETRY_ATTEMPTS", "2")))
MAX_GEMINI_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_GEMINI_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
client = (
    genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=GEMINI_HTTP_TIMEOUT_MILLISECONDS,
            retry_options=types.HttpRetryOptions(attempts=GEMINI_SDK_RETRY_ATTEMPTS),
        ),
    )
    if api_key
    else None
)

# Ưu tiên model cấu hình, sau đó thử các model fallback đã được cấu hình mặc định.
def build_gemini_models() -> list[str]:
    preferred = os.environ.get("GEMINI_MODEL", "").strip()
    fallback_models = os.environ.get("GEMINI_FALLBACK_MODELS") or (
        "gemini-3.6-flash,gemini-3.8-flash"
    )
    candidates = [preferred] if preferred else []
    candidates.extend(model.strip() for model in fallback_models.split(","))
    unique = []
    seen = set()
    for model in candidates:
        model = model.replace("models/", "", 1).strip()
        if not model or model in seen:
            continue
        seen.add(model)
        unique.append(model)
    return unique

GEMINI_MODELS = build_gemini_models()


def _gemini_model_id(model) -> str:
    """Normalize a model resource/object to the short model ID used by this app."""
    value = getattr(model, "name", model)
    return str(value or "").replace("models/", "", 1).strip()


def _gemini_error_details(error: Exception) -> dict:
    """Extract safe diagnostic details without returning credentials or raw traces."""
    status_code = getattr(error, "code", None) or getattr(error, "status_code", None)
    try:
        status_code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status_code = None
    message = re.sub(
        r"(?i)(AIza[0-9A-Za-z_-]{20,}|(?:api[_ -]?key|authorization)\s*[:=]\s*(?:Bearer\s+)?\S+|Bearer\s+\S+)",
        "[REDACTED]",
        str(error),
    )[:500]
    return {
        "status_code": status_code,
        "error_type": type(error).__name__,
        "error": message or "Gemini request failed.",
    }


def _gemini_capabilities(model) -> dict:
    """Read capability metadata exposed by google-genai without making assumptions."""
    actions = getattr(model, "supported_actions", None) or []
    normalized_actions = [str(action) for action in actions]
    action_text = " ".join(normalized_actions).casefold()
    return {
        "supported_actions": normalized_actions,
        "generate_content": any(
            marker in action_text for marker in ("generatecontent", "generate_content")
        ),
        # The model list API does not expose reliable separate flags for these.
        # They are set by the optional live probes below.
        "function_calling": "not_verified",
        "vision": "not_verified",
    }


def _diagnostic_tool(value: str) -> str:
    """Small no-op tool used only for an optional function-calling probe."""
    return value


def _response_has_function_call(response) -> bool:
    return any(
        getattr(part, "function_call", None) is not None
        for part in _response_parts(response)
    )


def _probe_gemini_model(model_name: str) -> dict:
    """Run small live probes for text generation, function calling and vision."""
    if client is None:
        return {
            "function_calling": "not_configured",
            "vision": "not_configured",
        }

    result = {
        "function_calling": "error",
        "vision": "error",
    }
    try:
        function_declaration = types.FunctionDeclaration.from_callable(
            client=client,
            callable=_diagnostic_tool,
        )
        function_config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=[function_declaration])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        diagnostic_chat = client.chats.create(
            model=model_name,
            config=function_config,
        )
        response = diagnostic_chat.send_message(
            "Call diagnostic_tool with value 'ok'."
        )
        result["function_calling"] = "supported" if _response_has_function_call(response) else "request_succeeded_no_call"
    except Exception as error:
        result["function_calling_error"] = _gemini_error_details(error)

    try:
        # A valid 1x1 PNG. This checks that the model accepts image input without
        # uploading a user image or disclosing application data.
        tiny_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=tiny_png, mime_type="image/png"),
                "Describe this image briefly.",
            ],
        )
        result["vision"] = "supported" if getattr(response, "text", None) else "request_succeeded_no_text"
    except Exception as error:
        result["vision_error"] = _gemini_error_details(error)

    return result


def check_gemini_models(*, probe: bool = False) -> dict:
    """Discover configured Gemini models and optionally run live capability probes."""
    started = time.perf_counter()
    if client is None or not api_key:
        return {
            "status": "not_configured",
            "configured_models": GEMINI_MODELS,
            "models": [],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    try:
        available_models = list(client.models.list())
    except Exception as error:
        details = _gemini_error_details(error)
        logger.warning(
            "Gemini model discovery failed: status=%s error_type=%s",
            details["status_code"],
            details["error_type"],
        )
        return {
            "status": "error",
            "configured_models": GEMINI_MODELS,
            "models": [],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            **details,
        }

    available_by_id = {_gemini_model_id(model): model for model in available_models}
    results = []
    for model_name in GEMINI_MODELS:
        model = available_by_id.get(model_name)
        model_result = {
            "model": model_name,
            "configured": True,
            "available": model is not None,
        }
        if model is None:
            model_result.update({
                "status": "not_found",
                "function_calling": "not_verified",
                "vision": "not_verified",
            })
        else:
            model_result.update(_gemini_capabilities(model))
            model_result["status"] = "available"
            if probe:
                model_result.update(_probe_gemini_model(model_name))
        results.append(model_result)

    available_configured = [item for item in results if item["available"]]
    return {
        "status": "ok" if available_configured else "no_configured_models_available",
        "configured_models": GEMINI_MODELS,
        "models": results,
        "available_model_count": len(available_configured),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "probe": probe,
    }

SYSTEM_PROMPT = """Bạn là Trợ lý AI Bản đồ Nông nghiệp Thông minh chuyên nghiệp.
NHIỆM VỤ VÀ QUY TẮC CỐT LÕI:

WEB LOOKUP RULES: For current weather, crop prices, news, regulations, latest information, or facts outside the GIS dataset, call `tool_web_search`. It prioritizes configured official sources and falls back to web search. Use only returned source-backed facts. Every web-derived answer must include a "Nguồn tham khảo" section with source title, URL, and access time. Never invent URLs. If no valid source is returned, clearly say that reliable information could not be verified.

1. KHÔNG TỰ BỊA ĐẶT SỐ LIỆU: Mọi thông tin về tên thửa, độ ẩm, diện tích, nhiệt độ, cây trồng PHẢI được lấy từ các công cụ (tools) được cung cấp. Tuyệt đối không tự ước đoán số liệu.
2. KHÔNG TỰ TÍNH TOÁN TRONG ĐẦU: Nếu người dùng hỏi tổng diện tích, bạn BẮT BUỘC phải gọi hàm `tool_tinh_tong_dien_tich`. Hãy cộng theo diện tích đã lưu trong dữ liệu của từng thửa, không tính lại diện tích từ hình học. Nếu người dùng nêu rõ mã/tên các thửa (ví dụ T1 và T2 hoặc Thửa 1 và Thửa 2), truyền từng mã/tên vào `danh_sach_thua`. Nếu người dùng chỉ nêu số lượng (ví dụ "2 thửa") mà không xác định đó là thửa nào, hãy hỏi lại người dùng; không tự chọn thửa.
3. CÂU HỎI NGOÀI PHẠM VI HOẶC MƠ HỒ: Nếu người dùng hỏi các câu hỏi cảm tính, mơ hồ không có trong dữ liệu (ví dụ: "thửa nào đẹp nhất?", "giá lúa hôm nay?"), hãy lịch sự trả lời rằng: "Dữ liệu nông trại hiện tại chưa có thông tin về tiêu chí này. Hệ thống hiện chỉ quản lý các thông số kỹ thuật gồm loại cây trồng, diện tích, độ ẩm, nhiệt độ và khoảng cách vị trí."
4. PHONG CÁCH TRẢ LỜI: Ngắn gọn, thân thiện, chính xác, có định dạng rõ ràng (sử dụng icon phù hợp như 🌾, 💧, 📐, 🌡️, 🏠).
5. NHỚ NGỮ CẢNH: Khi có lịch sử hội thoại trong ngữ cảnh hiện tại, hãy dùng các kết quả đó để trả lời câu hỏi nối tiếp. Không suy đoán ngữ cảnh nếu lịch sử không được cung cấp.
6. Khi người dùng hỏi vị trí hoặc tọa độ của một đối tượng như giếng/nhà kho, bắt buộc gọi `tool_tim_vi_tri_doi_tuong`; không tự đoán vị trí.
7. Với câu hỏi có nhiều điều kiện (ví dụ cây trồng, ngưỡng độ ẩm và khoảng cách tới mốc), gọi `tool_loc_thua` một lần và truyền đủ điều kiện; các điều kiện được áp dụng đồng thời.
8. Khi công cụ trả về `parcel_ids`, hãy nêu đúng các thửa đó trong câu trả lời; API sẽ dùng các ID này để chọn thửa trên bản đồ.
9. Chỉ dùng dữ liệu do công cụ trả về; không hiển thị JSON thô. Nếu công cụ không có dữ liệu phù hợp, hãy nói rõ rằng chưa tìm thấy dữ liệu.
"""

def build_ai_tool_registry() -> list[types.FunctionDeclaration]:
    if client is None:
        return []

    return [
        types.FunctionDeclaration.from_callable(client=client, callable=fn)
        for fn in AI_TOOL_FUNCTIONS.values()
    ]


AI_TOOL_FUNCTIONS = {
    fn.__name__: fn
    for fn in (
        tool_loc_thua,
        tool_thua_cuc_tri,
        tool_tinh_tong_dien_tich,
        tool_thua_gan,
        tool_khoang_cach,
        tool_tim_vi_tri_doi_tuong,
        tool_du_bao_thoi_tiet,
        tool_tra_cuu_gia_nong_san,
        tool_web_search,
    )
}


AI_TOOL_REGISTRY = build_ai_tool_registry()
ai_config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=AI_TOOL_REGISTRY)] if AI_TOOL_REGISTRY else [],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(
        disable=True,
    ),
)


MAX_GEMINI_TOOL_ROUNDS = 2
MAX_GEMINI_TOOL_CALLS_PER_ROUND = 3
MAX_GEMINI_TOOL_RESULT_CHARS = 8_000
MAX_GEMINI_PARCEL_IDS = 20
MAX_WEB_SOURCES_IN_REPLY = 5


def _response_parts(response) -> list[types.Part]:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        if parts:
            return parts
    return []

def _tool_result_parcel_ids(tool_result: str) -> list[str]:
    try:
        result = json.loads(tool_result)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(result, dict):
        return []
    parcel_ids = result.get("parcel_ids")
    if not isinstance(parcel_ids, list):
        return []
    return [str(parcel_id) for parcel_id in parcel_ids if parcel_id is not None]


def _tool_call_signature(function_name: str, arguments) -> str:
    """Build a stable signature for preventing duplicate tool calls."""
    try:
        normalized_arguments = json.dumps(
            arguments if isinstance(arguments, dict) else {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        normalized_arguments = "{}"
    return f"{function_name}:{normalized_arguments}"


def _validate_tool_arguments(function, arguments) -> dict:
    """Validate Gemini arguments against the Python tool signature before execution."""
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    try:
        signature = inspect.signature(function)
        signature.bind(**arguments)
    except TypeError as error:
        raise ValueError(f"Invalid tool arguments: {error}") from error
    return arguments


def _compact_tool_result(result: str) -> str:
    """Keep tool responses bounded before sending them back to Gemini."""
    def compact_value(value, depth: int = 0):
        if depth > 4:
            return "...[truncated]"
        if isinstance(value, str):
            return value if len(value) <= 500 else value[:500] + "...[truncated]"
        if isinstance(value, list):
            compacted = [compact_value(item, depth + 1) for item in value[:20]]
            if len(value) > 20:
                compacted.append("...[truncated items]")
            return compacted
        if isinstance(value, dict):
            return {
                str(key): compact_value(item, depth + 1)
                for key, item in list(value.items())[:50]
            }
        return value

    if not isinstance(result, str):
        result = str(result)
    if len(result) <= MAX_GEMINI_TOOL_RESULT_CHARS:
        return result

    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            compact = compact_value(parsed)
            compact["_truncated"] = True
            compact["_original_chars"] = len(result)
            result = json.dumps(compact, ensure_ascii=False)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    if len(result) > MAX_GEMINI_TOOL_RESULT_CHARS:
        result = result[:MAX_GEMINI_TOOL_RESULT_CHARS] + "...[truncated]"
    return result


def _build_gemini_history(history: list["ChatTurn"]) -> list[types.Content]:
    contents = []
    for turn in history[-12:]:
        text = turn.content
        if turn.role == "assistant" and turn.parcel_ids:
            text += "\n[Các thửa đã được công cụ xác định: " + ", ".join(turn.parcel_ids) + "]"
        contents.append(
            types.Content(
                role="user" if turn.role == "user" else "model",
                parts=[types.Part.from_text(text=text)],
            )
        )
    return contents


async def _send_gemini_message(
    chat_session,
    contents,
    deadline: float,
) -> tuple[str, list[str]]:
    started = time.perf_counter()
    parcel_ids = []
    web_sources = []
    executed_tool_signatures = set()

    for _ in range(MAX_GEMINI_TOOL_ROUNDS + 1):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Gemini chat timed out while processing tool calls.")

        response = await asyncio.wait_for(
            chat_session.send_message(contents),
            timeout=min(remaining, GEMINI_MODEL_REQUEST_TIMEOUT_SECONDS),
        )
        parts = _response_parts(response)
        function_calls = [
            part.function_call
            for part in parts
            if getattr(part, "function_call", None)
            and getattr(part.function_call, "name", None)
        ]

        if not function_calls:
            text = "".join(
                part_text
                for part in parts
                if isinstance((part_text := getattr(part, "text", None)), str)
            ).strip()
            if not text:
                raise RuntimeError("Gemini returned neither text nor a function call.")
            if web_sources and "http" not in text.lower():
                text += "\n\nNguồn tham khảo:\n" + "\n".join(
                    f"- {source['title']} — {source['url']} (truy cập {source['accessed_at']})"
                    for source in web_sources[:MAX_WEB_SOURCES_IN_REPLY]
                )
            logger.info(
                "Gemini chat completed: elapsed_ms=%.2f tool_calls=%d web_sources=%d",
                (time.perf_counter() - started) * 1000,
                len(executed_tool_signatures),
                len(web_sources),
            )
            return text, list(dict.fromkeys(parcel_ids))

        if len(function_calls) > MAX_GEMINI_TOOL_CALLS_PER_ROUND:
            raise RuntimeError(
                "Gemini requested too many tool calls in one round."
            )

        function_responses = []
        for function_call in function_calls:
            function_name = function_call.name
            try:
                raw_arguments = function_call.args or {}
                if not isinstance(raw_arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                function_arguments = dict(raw_arguments)
            except (TypeError, ValueError) as error:
                tool_result = {"error": str(error)}
                function_responses.append(
                    types.Part.from_function_response(
                        name=function_name,
                        response=tool_result,
                    )
                )
                continue
            call_signature = _tool_call_signature(function_name, function_arguments)
            function = AI_TOOL_FUNCTIONS.get(function_name)
            if function is None:
                logger.warning("Gemini requested an unknown tool: %s", function_name)
                tool_result = {"error": f"Tool '{function_name}' is not available."}
            elif call_signature in executed_tool_signatures:
                logger.warning("Gemini repeated the same tool call: tool=%s", function_name)
                tool_result = {"error": "This tool call was already executed in this request."}
            else:
                try:
                    executed_tool_signatures.add(call_signature)
                    function_arguments = _validate_tool_arguments(function, function_arguments)
                    tool_started = time.perf_counter()
                    result = _compact_tool_result(
                        await asyncio.to_thread(function, **function_arguments)
                    )
                    logger.info(
                        "Gemini tool completed: tool=%s elapsed_ms=%.2f result_chars=%d",
                        function_name,
                        (time.perf_counter() - tool_started) * 1000,
                        len(result),
                    )
                    parcel_ids.extend(_tool_result_parcel_ids(result))
                    parcel_ids = list(dict.fromkeys(parcel_ids))[:MAX_GEMINI_PARCEL_IDS]
                    if function_name == "tool_web_search":
                        try:
                            parsed_result = json.loads(result)
                            sources = parsed_result.get("sources", [])
                            if isinstance(sources, list):
                                web_sources.extend(
                                    source for source in sources
                                    if isinstance(source, dict) and _safe_source_url(source.get("url"))
                                )
                        except (TypeError, json.JSONDecodeError):
                            pass
                    tool_result = {
                        "result": result
                    }
                except HTTPException as error:
                    tool_result = {"error": str(error.detail)}
                except (TypeError, ValueError) as error:
                    tool_result = {"error": str(error)}
                except Exception:
                    logger.exception("Gemini tool execution failed: tool=%s", function_name)
                    tool_result = {"error": "Tool execution failed."}

            function_responses.append(
                types.Part.from_function_response(
                    name=function_name,
                    response=tool_result,
                )
            )

        contents = function_responses

    raise RuntimeError("Gemini exceeded the maximum number of tool-call rounds.")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    parcel_ids: list[str] = Field(default_factory=list, max_length=20)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: Optional[int] = None
    image_base64: Optional[str] = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


def _format_direct_gis_result(result: dict, operation: str) -> tuple[str, list[str]]:
    parcel_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in result.get("parcel_ids", [])
            if item is not None and str(item).strip()
        )
    )[:MAX_GEMINI_PARCEL_IDS]
    if operation == "location":
        objects = result.get("doi_tuong", [])
        lines = []
        for item in objects:
            label = item.get("ten") or item.get("name") or item.get("id", "đối tượng")
            lines.append(
                f"📍 {label} (ID: {item.get('id', 'N/A')}) — "
                f"vĩ độ {item.get('latitude')}, kinh độ {item.get('longitude')}"
            )
        return "\n".join(lines), parcel_ids
    if operation == "distance":
        return (
            f"📐 Khoảng cách giữa {result.get('doi_tuong_1_tim_duoc')} và "
            f"{result.get('doi_tuong_2_tim_duoc')}: {result.get('khoang_cach_met')} mét.",
            parcel_ids,
        )
    if operation == "area":
        return (
            f"📐 Tổng diện tích {result.get('so_thua')} thửa là "
            f"{result.get('tong_dien_tich_m2')} m².",
            parcel_ids,
        )
    data = result.get("du_lieu", {})
    if not isinstance(data, dict):
        data = {}
    label = data.get("ten") or data.get("name") or data.get("id", "thửa đất")
    field_labels = {
        "dien_tich_m2": "diện tích",
        "do_am": "độ ẩm",
        "do_am_pct": "độ ẩm",
        "humidity": "độ ẩm",
        "nhiet_do": "nhiệt độ",
        "temperature": "nhiệt độ",
    }
    field_label = field_labels.get(result.get("truong"), result.get("truong", "giá trị"))
    extreme_label = "lớn nhất" if result.get("loai") == "MAX" else "nhỏ nhất"
    value = data.get(result.get("truong"))
    value_text = f" ({value})" if value not in (None, "") else ""
    return (
        f"🌾 Thửa có {field_label} {extreme_label}: {label}"
        f"{value_text} (ID: {parcel_ids[0] if parcel_ids else 'N/A'}).",
        parcel_ids,
    )


def _extract_reply_sources(reply: str) -> list[dict]:
    """Extract only explicit HTTP links emitted from the validated web tool."""
    sources = []
    seen = set()
    for line in str(reply or "").splitlines():
        match = re.search(r"(?:-\s*)?(?P<title>.*?)\s*[—-]\s*(?P<url>https?://\S+)", line)
        if not match:
            continue
        url = _safe_source_url(match.group("url").rstrip(").,;"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"title": match.group("title").strip() or url, "url": url})
    return sources[:MAX_WEB_SOURCES_IN_REPLY]


def _extract_direct_parcel_identifiers(message: str) -> list[str]:
    """Extract parcel codes and common Vietnamese ordinal forms in input order.

    Handles cases like "thua 2 và 3" or "thua 2, 3" where the second parcel
    number appears without the word "thua" in front of it.
    """
    normalized = clean_text(message)
    pattern = re.compile(
        r"\b(?:t\s*\d+|thua(?:\s+dat)?(?:\s+so)?\s*#?\s*\d+)\b",
        flags=re.IGNORECASE,
    )
    raw_matches = [match.group(0).strip() for match in pattern.finditer(normalized)]
    matches = list(dict.fromkeys(raw_matches))

    # Collect numbers already covered by "thua X" / "tX" matches to avoid duplicates.
    covered_numbers: set[str] = set()
    for m in matches:
        num_match = re.search(r"\d+$", m)
        if num_match:
            covered_numbers.add(num_match.group(0))

    # If the message asks about total area or mentions "thua", also extract
    # standalone 1-2 digit numbers that likely refer to additional parcels
    # (e.g. "thua 2 và 3" -> "3" should be included as parcel t3).
    if "thua" in normalized or "tong dien tich" in normalized:
        for num_match in re.finditer(r"\b(\d{1,2})\b", normalized):
            num_str = num_match.group(1)
            if num_str not in covered_numbers:
                matches.append(f"t{num_str}")
                covered_numbers.add(num_str)

    return matches


def _try_direct_gis_chat(message: str) -> Optional[tuple[str, list[str]]]:
    """Handle unambiguous GIS questions without an unnecessary Gemini round-trip."""
    normalized = clean_text(message)
    if not normalized:
        return None

    if any(marker in normalized for marker in ("o dau", "vi tri", "toa do")):
        keyword = None
        if any(item in normalized for item in ("gieng", "gieng tuoi")):
            keyword = "gieng"
        elif any(item in normalized for item in ("nha kho", "kho trung tam", "kho")):
            keyword = "nha kho"
        if keyword:
            return _format_direct_gis_result(gis_tim_vi_tri_doi_tuong(keyword), "location")

    distance_match = re.search(r"(?:tu|giua)\s+(.+?)\s+(?:den|va)\s+(.+?)(?:\?|$)", normalized)
    if "khoang cach" in normalized and distance_match:
        return _format_direct_gis_result(
            gis_khoang_cach(distance_match.group(1).strip(), distance_match.group(2).strip()),
            "distance",
        )

    if "tong dien tich" in normalized:
        identifiers = _extract_direct_parcel_identifiers(message)
        return _format_direct_gis_result(
            gis_tinh_tong_dien_tich(danh_sach_thua=identifiers or None),
            "area",
        )

    if any(item in normalized for item in ("lon nhat", "nho nhat")) and any(
        item in normalized for item in ("dien tich", "do am", "nhiet do")
    ):
        field = (
            "dien_tich"
            if "dien tich" in normalized
            else "do_am"
            if "do am" in normalized
            else "nhiet_do"
        )
        kind = "min" if "nho nhat" in normalized else "max"
        return _format_direct_gis_result(gis_thua_cuc_tri(field, kind), "extreme")
    return None

@app.post("/api/chat", summary="Chat AI Gemini có xử lý công cụ GIS")
async def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    user_id = current_user.id if current_user else None

    if not request.image_base64:
        try:
            direct_result = _try_direct_gis_chat(request.message)
        except HTTPException:
            direct_result = None
        if direct_result:
            reply_text, parcel_ids = direct_result
            background_tasks.add_task(
                persist_chat_result,
                user_id=user_id,
                user_message=request.message,
                response=reply_text,
                intent="DIRECT_GIS",
            )
            return {"reply": reply_text, "parcel_ids": parcel_ids}

    if client is None:
        detail = "Backend chưa nhận được cấu hình GEMINI_API_KEY. Hãy đặt biến môi trường rồi khởi động lại server."
        background_tasks.add_task(
            persist_chat_result,
            user_id=current_user.id if current_user else None,
            user_message=request.message,
            response=detail,
            intent="GEMINI_ERROR",
            error={"type": "GeminiConfigurationError", "message": detail},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    
    contents = []
    if request.image_base64:
        try:
            image_data = request.image_base64
            mime_type = "image/jpeg"
            if "," in image_data:
                header, image_data = image_data.split(",", 1)
                if header.startswith("data:") and ";base64" in header:
                    mime_type = header[5:header.index(";")]
            if mime_type not in ALLOWED_GEMINI_IMAGE_MIME_TYPES:
                raise ValueError("Loại ảnh không được hỗ trợ.")
            if len(image_data) > ((MAX_GEMINI_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError("Ảnh vượt quá dung lượng tối đa 5 MB.")
            decoded_image = base64.b64decode(image_data, validate=True)
            if len(decoded_image) > MAX_GEMINI_IMAGE_BYTES:
                raise ValueError("Ảnh vượt quá dung lượng tối đa 5 MB.")
            contents.append(types.Part.from_bytes(
                data=decoded_image,
                mime_type=mime_type,
            ))
        except (ValueError, base64.binascii.Error) as error:
            detail = "Ảnh không hợp lệ, không được hỗ trợ hoặc vượt quá dung lượng tối đa 5 MB."
            background_tasks.add_task(
                persist_chat_result,
                user_id=user_id,
                user_message=request.message,
                response=detail,
                intent="GEMINI_ERROR",
                error={"type": "InvalidImageError", "message": str(error)},
            )
            raise HTTPException(status_code=422, detail=detail) from error
    contents.append(request.message)

    reply_text = None
    selected_parcel_ids = []
    last_error_status = None
    last_error_type = None
    last_error_message = None
    last_error_model = None
    stop_fallback = False
    request_started = asyncio.get_running_loop().time()
    request_deadline = request_started + GEMINI_REQUEST_TIMEOUT_SECONDS
    for model_index, model_name in enumerate(GEMINI_MODELS):
        remaining = request_deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            last_error_type = "TimeoutError"
            last_error_message = "Gemini exceeded the chat request deadline."
            last_error_model = model_name
            stop_fallback = True
            break
        models_remaining = len(GEMINI_MODELS) - model_index
        model_deadline = min(
            request_deadline,
            asyncio.get_running_loop().time()
            + min(GEMINI_MODEL_REQUEST_TIMEOUT_SECONDS, remaining / models_remaining),
        )
        for attempt in range(2):
            remaining = model_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                last_error_type = "TimeoutError"
                last_error_message = "Gemini exceeded this model's request deadline."
                last_error_model = model_name
                break
            try:
                chat_session = client.aio.chats.create(
                    model=model_name,
                    config=ai_config,
                    history=_build_gemini_history(request.history),
                )
                reply_text, selected_parcel_ids = await _send_gemini_message(
                    chat_session,
                    contents,
                    model_deadline,
                )
                break
            except Exception as e:
                error_code = getattr(e, "code", None) or getattr(e, "status_code", None)
                try:
                    last_error_status = int(error_code)
                except (TypeError, ValueError):
                    last_error_status = None
                last_error_type = type(e).__name__
                last_error_message = str(e)
                last_error_model = model_name
                logger.warning(
                    "Gemini request failed: model=%s status=%s error_type=%s elapsed_seconds=%.1f",
                    model_name,
                    last_error_status or "unknown",
                    type(e).__name__,
                    asyncio.get_running_loop().time() - request_started,
                )
                if last_error_status in (401, 403):
                    detail = "Gemini từ chối API key hoặc quyền truy cập. Kiểm tra key, trạng thái key và quyền dùng Gemini API."
                    background_tasks.add_task(
                        persist_chat_result,
                        user_id=current_user.id if current_user else None,
                        user_message=request.message,
                        response=detail,
                        intent="GEMINI_ERROR",
                        error={
                            "model": model_name,
                            "status_code": last_error_status,
                            "type": last_error_type,
                            "message": last_error_message,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=detail,
                    ) from e
                if isinstance(e, TimeoutError):
                    last_error_type = "TimeoutError"
                    last_error_message = str(e) or "Gemini request timed out."
                    if request_deadline - asyncio.get_running_loop().time() <= 0:
                        stop_fallback = True
                    break
                if last_error_status not in (404, 429, 500, 502, 503, 504):
                    stop_fallback = True
                    break
                transient_error = (
                    last_error_status in (429, 500, 502, 503, 504)
                    or any(
                        marker in f"{type(e).__name__} {last_error_message}".upper()
                        for marker in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL")
                    )
                )
                if transient_error and attempt == 0:
                    remaining = model_deadline - asyncio.get_running_loop().time()
                    retry_delay = min(
                        8.0,
                        0.75 * (2 ** attempt) + random.uniform(0.0, 0.5),
                        max(0.0, remaining - 0.25),
                    )
                    if retry_delay > 0:
                        await asyncio.sleep(retry_delay)
                else:
                    break
        if reply_text:
            break
        if stop_fallback:
            break

    if not reply_text:
        if last_error_status == 404:
            detail = "Model Gemini không tồn tại hoặc không được bật cho key này. Kiểm tra GEMINI_MODEL và quyền truy cập model."
        elif last_error_status == 429:
            detail = "Gemini đã vượt hạn mức hoặc giới hạn tốc độ của API key."
        elif last_error_status in (500, 502, 503, 504):
            detail = "Dịch vụ Gemini đang tạm thời gặp sự cố. Hãy thử lại sau."
        elif last_error_type == "TimeoutError":
            detail = (
                f"Gemini chưa phản hồi trong {GEMINI_REQUEST_TIMEOUT_SECONDS} giây. "
                "Yêu cầu đã được dừng; hãy thử lại sau."
            )
        else:
            detail = "Không gọi được Gemini. Kiểm tra log backend để xem model và mã lỗi; API key không được ghi vào log."
        background_tasks.add_task(
            persist_chat_result,
            user_id=user_id,
            user_message=request.message,
            response=detail,
            intent="GEMINI_ERROR",
            error={
                "model": last_error_model,
                "status_code": last_error_status,
                "type": last_error_type or "GeminiRequestError",
                "message": last_error_message or "Gemini không trả về phản hồi.",
            },
        )
        response_status = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if last_error_type == "TimeoutError"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=response_status, detail=detail)

    background_tasks.add_task(
        persist_chat_result,
        user_id=user_id,
        user_message=request.message,
        response=reply_text,
        intent="GEMINI_GIS_CHAT",
    )

    return {
        "reply": reply_text,
        "parcel_ids": selected_parcel_ids,
        "sources": _extract_reply_sources(reply_text),
    }


# Dữ liệu thửa đất dùng cho bản đồ
@app.get("/api/parcels/geojson", summary="Lấy ranh giới thửa đất để hiển thị bản đồ")
def get_parcels_geojson(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return parcel_feature_collection(db)


@app.get("/api/objects/geojson", summary="Lấy đối tượng điểm (giếng, nhà kho) để hiển thị bản đồ")
def get_objects_geojson(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return object_feature_collection(db)


# Các API GIS trực tiếp
@app.get("/api/loc-thua")
def api_loc_thua(
    dieu_kien: Optional[str] = Query(default=None),
    cay_trong: Optional[str] = Query(default=None),
    do_am_toi_thieu: Optional[float] = Query(default=None, ge=0, le=100),
    do_am_toi_da: Optional[float] = Query(default=None, ge=0, le=100),
    gan_doi_tuong: Optional[str] = Query(default=None),
    ban_kinh_m: Optional[float] = Query(default=None, ge=0),
    current_user: models.User = Depends(get_current_user),
):
    return gis_loc_thua(
        dieu_kien=dieu_kien,
        cay_trong=cay_trong,
        do_am_toi_thieu=do_am_toi_thieu,
        do_am_toi_da=do_am_toi_da,
        gan_doi_tuong=gan_doi_tuong,
        ban_kinh_m=ban_kinh_m,
    )

@app.get("/api/thua-cuc-tri")
def api_thua_cuc_tri(
    truong: str = "dien_tich",
    loai: str = "max",
    current_user: models.User = Depends(get_current_user),
):
    return gis_thua_cuc_tri(truong, loai)

@app.get("/api/tong-dien-tich", summary="Tính tổng diện tích các thửa đất")
def api_tinh_tong_dien_tich(
    dieu_kien: Optional[str] = Query(default=None, max_length=100),
    danh_sach_thua: Optional[list[str]] = Query(default=None),
    current_user: models.User = Depends(get_current_user),
):
    return gis_tinh_tong_dien_tich(
        dieu_kien=dieu_kien,
        danh_sach_thua=danh_sach_thua,
    )

@app.get("/api/thua-gan")
def api_thua_gan(
    lat: float,
    lon: float,
    ban_kinh_m: float = 500.0,
    current_user: models.User = Depends(get_current_user),
):
    return gis_thua_gan(lat, lon, ban_kinh_m)

@app.get("/api/khoang-cach")
def api_khoang_cach(
    dt1: str,
    dt2: str,
    current_user: models.User = Depends(get_current_user),
):
    return gis_khoang_cach(dt1, dt2)

@app.get("/api/vi-tri-doi-tuong")
def api_tim_vi_tri_doi_tuong(
    tu_khoa: str = Query(..., min_length=1, max_length=100),
    current_user: models.User = Depends(get_current_user),
):
    return gis_tim_vi_tri_doi_tuong(tu_khoa)


# ------------------------------------------------------------------------------
# 6. ROUTER DÀNH RIÊNG CHO ADMIN
# ------------------------------------------------------------------------------
admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])


@admin_router.get("/gemini-models", summary="Kiểm tra model Gemini và capability tùy chọn")
def get_admin_gemini_models(
    probe: bool = Query(default=False),
    current_admin: models.User = Depends(get_current_admin),
):
    """Discover configured models; live probes are opt-in because they use quota."""
    return check_gemini_models(probe=probe)

@admin_router.get("/parcels")
def get_admin_parcels(
    q: Optional[str] = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    query = db.query(models.Parcel)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            (models.Parcel.parcel_code.ilike(term))
            | (models.Parcel.name.ilike(term))
            | (models.Parcel.crop_type.ilike(term))
        )
    parcels = query.order_by(models.Parcel.id.asc()).all()
    return {"total": len(parcels), "data": [parcel_to_feature(parcel) | {"db_id": parcel.id} for parcel in parcels]}


@admin_router.post("/parcels", status_code=status.HTTP_201_CREATED)
def create_parcel(
    data: ParcelCreateSchema,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    try:
        geometry = validate_parcel_geometry(data.geometry)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    code = data.parcel_code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="Mã thửa không được để trống.")
    if db.query(models.Parcel).filter(models.Parcel.parcel_code == code).first():
        raise HTTPException(status_code=409, detail="Mã thửa đã tồn tại.")

    parcel = models.Parcel(
        parcel_code=code,
        name=data.name.strip(),
        crop_type=data.crop_type.strip(),
        geometry_geojson=json.dumps(geometry, ensure_ascii=False),
        area_sqm=parcel_area_sqm(geometry),
        moisture=data.moisture,
        temperature=data.temperature,
        notes=data.notes.strip() if data.notes else None,
    )
    db.add(parcel)
    try:
        db.commit()
        db.refresh(parcel)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã thửa đã tồn tại.") from error
    refresh_gis_cache(db)
    return parcel_to_feature(parcel) | {"db_id": parcel.id}


@admin_router.put("/parcels/{parcel_id}")
def update_parcel(
    parcel_id: int,
    data: ParcelUpdateSchema,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Không tìm thấy thửa đất.")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào được gửi để cập nhật.")

    if "parcel_code" in updates:
        if updates["parcel_code"] is None:
            raise HTTPException(status_code=422, detail="Mã thửa không được để trống.")
        code = updates["parcel_code"].strip()
        if not code:
            raise HTTPException(status_code=422, detail="Mã thửa không được để trống.")
        duplicate = db.query(models.Parcel).filter(
            models.Parcel.parcel_code == code,
            models.Parcel.id != parcel_id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Mã thửa đã tồn tại.")
        parcel.parcel_code = code

    for field in ("name", "crop_type"):
        if field in updates:
            if updates[field] is None or not updates[field].strip():
                raise HTTPException(status_code=422, detail=f"{field} không được để trống.")
            setattr(parcel, field, updates[field].strip())

    if "geometry" in updates:
        if updates["geometry"] is None:
            raise HTTPException(status_code=422, detail="Ranh giới không được để trống.")
        try:
            geometry = validate_parcel_geometry(updates["geometry"])
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        parcel.geometry_geojson = json.dumps(geometry, ensure_ascii=False)
        parcel.area_sqm = parcel_area_sqm(geometry)

    for field in ("moisture", "temperature", "notes"):
        if field in updates:
            value = updates[field]
            setattr(parcel, field, value.strip() if field == "notes" and value else value)

    try:
        db.commit()
        db.refresh(parcel)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã thửa đã tồn tại.") from error
    refresh_gis_cache(db)
    return parcel_to_feature(parcel) | {"db_id": parcel.id}


@admin_router.delete("/parcels/{parcel_id}")
def delete_parcel(
    parcel_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Không tìm thấy thửa đất.")
    db.delete(parcel)
    db.commit()
    refresh_gis_cache(db)
    return {"message": "Đã xóa thửa đất."}


@admin_router.get("/history")
def get_all_admin_chat_history(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    chats = db.query(models.ChatHistory).order_by(models.ChatHistory.id.desc()).all()
    return {"total": len(chats), "data": chats}

@admin_router.get("/summary")
def get_admin_summary(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    parcels = db.query(models.Parcel).order_by(models.Parcel.id.asc()).all()
    total_parcels = len(parcels)
    total_area_sqm = round(sum(float(parcel.area_sqm or 0) for parcel in parcels), 2)
    # SQL Server không hỗ trợ biểu thức `IS 1`; dùng phép so sánh để SQLAlchemy
    # sinh `users.is_active = 1` thay vì `users.is_active IS 1`.
    active_users = db.query(models.User).filter(models.User.is_active == True).count()
    recent_chats = db.query(models.ChatHistory).count()
    latest_error = db.query(models.AIErrorLog).order_by(models.AIErrorLog.created_at.desc()).first()

    summary = {
        "total_parcels": total_parcels,
        "total_area_sqm": total_area_sqm,
        "active_users": active_users,
        "chat_count": recent_chats,
        "latest_error": {
            "error_type": latest_error.error_type,
            "error_message": latest_error.error_message,
            "created_at": latest_error.created_at.isoformat() if latest_error and latest_error.created_at else None,
        } if latest_error else None,
        "stats": parcel_summary_stats(db),
    }
    return summary

@admin_router.delete("/history/{chat_id}")
def delete_admin_chat_history(
    chat_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    chat = db.query(models.ChatHistory).filter(models.ChatHistory.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi chat.")
    db.delete(chat)
    db.commit()
    return {"message": "Xóa bản ghi lịch sử chat thành công"}

@admin_router.get("/users")
def get_all_users(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    users = db.query(models.User).order_by(models.User.id.asc()).all()
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "created_at": u.created_at} for u in users]

@admin_router.put("/users/{user_id}/grant-admin")
def grant_admin_role(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng này!")
    
    user.role = "admin"
    db.commit()
    return {"message": f"Đã nâng cấp quyền Admin cho tài khoản {user.username}!"}

app.include_router(admin_router)

# Mount các file giao diện tĩnh (HTML, CSS, JS)
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")


# ------------------------------------------------------------------------------
# 7. KHỞI CHẠY APPLICATION SERVER
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
