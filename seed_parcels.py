"""Insert missing sample map features without overwriting user-managed records."""

import json
import math
import os

from sqlalchemy.exc import IntegrityError

import models
from database import Base, SessionLocal, engine
from parcel_utils import parcel_area_sqm, validate_parcel_geometry


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")


def seed_parcels() -> None:
    Base.metadata.create_all(bind=engine)
    with open(DATA_FILE, "r", encoding="utf-8") as source:
        collection = json.load(source)

    db = SessionLocal()
    inserted = 0
    codes_in_json = set()
    try:
        for feature in collection.get("features", []):
            properties = feature.get("properties") or {}
            code = str(properties.get("id") or "").strip()
            if not code:
                continue
            codes_in_json.add(code)
            geometry = feature.get("geometry")
            if not code or not geometry or geometry.get("type") != "Polygon":
                continue

            validated_geometry = validate_parcel_geometry(geometry)
            stored_area = properties.get("dien_tich")
            if stored_area is None:
                area_sqm = parcel_area_sqm(validated_geometry)
            else:
                try:
                    area_sqm = float(stored_area)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"Diện tích đã lưu của thửa '{code}' không hợp lệ.") from error
                if not math.isfinite(area_sqm) or area_sqm <= 0:
                    raise ValueError(f"Diện tích đã lưu của thửa '{code}' phải lớn hơn 0.")

            existing_parcel = (
                db.query(models.Parcel)
                .filter(models.Parcel.parcel_code == code)
                .first()
            )
            if existing_parcel:
                continue

            db.add(models.Parcel(
                parcel_code=code,
                name=str(properties.get("ten") or code)[:100],
                crop_type=str(properties.get("cay_trong") or "Chưa xác định")[:100],
                geometry_geojson=json.dumps(validated_geometry, ensure_ascii=False),
                area_sqm=area_sqm,
                moisture=properties.get("do_am"),
                temperature=properties.get("nhiet_do"),
                notes=None,
            ))
            inserted += 1

        db.commit()
    except (IntegrityError, ValueError, TypeError):
        db.rollback()
        raise
    finally:
        db.close()

    print(
        f"Đã thêm {inserted} thửa mẫu còn thiếu; giữ nguyên dữ liệu thửa đã có "
        f"(data.json chứa {len(codes_in_json)} mã)."
    )

    # Add sample objects that do not yet exist; preserve existing database records.
    db_objects = SessionLocal()
    inserted_objects = 0
    codes_in_json = set()

    try:
        for feature in collection.get("features", []):
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry")
            if not geometry or geometry.get("type") != "Point":
                continue

            code = str(properties.get("id") or "").strip()
            if not code:
                continue

            obj_type = str(properties.get("loai") or "").strip()
            if obj_type not in ("gieng", "nha_kho"):
                continue

            codes_in_json.add(code)

            existing_object = (
                db_objects.query(models.MapObject)
                .filter(models.MapObject.object_code == code)
                .first()
            )

            payload = {
                "name": str(properties.get("ten") or code)[:100],
                "object_type": obj_type,
                "description": str(properties.get("mo_ta") or "") or None,
                "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
            }

            if existing_object:
                continue
            db_objects.add(models.MapObject(
                object_code=code,
                **payload,
            ))
            inserted_objects += 1

        db_objects.commit()
    except (IntegrityError, ValueError, TypeError):
        db_objects.rollback()
        raise
    finally:
        db_objects.close()

    print(
        f"Đã thêm {inserted_objects} đối tượng mẫu còn thiếu; giữ nguyên đối tượng đã có "
        f"(data.json chứa {len(codes_in_json)} mã)."
    )


if __name__ == "__main__":
    seed_parcels()
