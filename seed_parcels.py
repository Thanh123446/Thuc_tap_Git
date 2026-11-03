"""Import polygon features from data.json into SQL Server and sync stored areas."""

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
    updated = 0
    try:
        for feature in collection.get("features", []):
            properties = feature.get("properties") or {}
            code = str(properties.get("id") or "").strip()
            if "codes_in_json" not in locals():
                codes_in_json = set()
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
                existing_parcel.name = str(properties.get("ten") or code)[:100]
                existing_parcel.crop_type = str(properties.get("cay_trong") or "Chưa xác định")[:100]
                existing_parcel.geometry_geojson = json.dumps(validated_geometry, ensure_ascii=False)
                existing_parcel.area_sqm = area_sqm
                existing_parcel.moisture = properties.get("do_am")
                existing_parcel.temperature = properties.get("nhiet_do")
                existing_parcel.notes = None
                updated += 1
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

        # Xóa các thửa trong DB mà không còn tồn tại trong data.json (purge stale)
        if codes_in_json:
            deleted_parcels = (
                db.query(models.Parcel)
                .filter(~models.Parcel.parcel_code.in_(codes_in_json))
                .delete(synchronize_session=False)
            )
        else:
            deleted_parcels = db.query(models.Parcel).delete(synchronize_session=False)

        db.commit()
    except (IntegrityError, ValueError, TypeError):
        db.rollback()
        raise
    finally:
        db.close()

    print(
        f"Đã nhập {inserted} thửa mới, cập nhật {updated} thửa, xóa {deleted_parcels} thửa cũ "
        f"(tổng {len(codes_in_json)} mã trong data.json)."
    )

    # --- Đồng bộ đối tượng bản đồ (giếng, nhà kho) từ data.json ---
    # Hỗ trợ: thêm mới, cập nhật (upsert), và xóa những record trong DB không còn có trong file JSON.
    db_objects = SessionLocal()
    inserted_objects = 0
    updated_objects = 0
    deleted_objects = 0
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
                existing_object.name = payload["name"]
                existing_object.object_type = payload["object_type"]
                existing_object.description = payload["description"]
                existing_object.geometry_geojson = payload["geometry_geojson"]
                updated_objects += 1
            else:
                db_objects.add(models.MapObject(
                    object_code=code,
                    **payload,
                ))
                inserted_objects += 1

        # Xóa các record trong DB mà không còn tồn tại trong data.json (purge stale)
        if codes_in_json:
            deleted_objects = (
                db_objects.query(models.MapObject)
                .filter(~models.MapObject.object_code.in_(codes_in_json))
                .delete(synchronize_session=False)
            )
        else:
            deleted_objects = db_objects.query(models.MapObject).delete(synchronize_session=False)

        db_objects.commit()
    except (IntegrityError, ValueError, TypeError):
        db_objects.rollback()
        raise
    finally:
        db_objects.close()

    print(
        f"Đồng bộ đối tượng bản đồ: thêm {inserted_objects}, cập nhật {updated_objects}, "
        f"xóa {deleted_objects} (tổng {len(codes_in_json)} mã trong data.json)."
    )


if __name__ == "__main__":
    seed_parcels()
