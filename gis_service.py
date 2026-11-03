import os
import re
import sys
import time
import unicodedata
import math
from numbers import Integral
from typing import Optional

from fastapi import HTTPException
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree
import pyproj
import json as _json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json") if os.path.exists(os.path.join(BASE_DIR, "data.json")) else os.path.join(BASE_DIR, "data_2.json")


def _safe_float(value, default: float = 0.0) -> float:
    """Trả về giá trị float an toàn (không inf, -inf, NaN) để tránh lỗi JSON serialization."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v

GDF: Optional[gpd.GeoDataFrame] = None
PARCEL_GDF: Optional[gpd.GeoDataFrame] = None
SPATIAL_TREE: Optional[STRtree] = None
SPATIAL_GEOMETRY_POSITIONS: dict[bytes, list[int]] = {}
transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True)
inverse_transformer = pyproj.Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def clean_text(text: str) -> str:
    if text is None or pd.isna(text):
        return ""
    normalized = unicodedata.normalize("NFKD", str(text).casefold())
    return "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    ).replace("đ", "d").strip()


def _index_geodataframe(gdf: gpd.GeoDataFrame) -> None:
    global GDF, PARCEL_GDF, SPATIAL_TREE, SPATIAL_GEOMETRY_POSITIONS

    if gdf.empty:
        if "geometry" not in gdf.columns:
            gdf = gpd.GeoDataFrame(
                {"geometry": gpd.GeoSeries([], crs="EPSG:4326")},
                crs="EPSG:4326",
            )
        gdf["dien_tich_m2"] = pd.Series(dtype="float64")
        gdf["_search_text"] = pd.Series(dtype="object")
        GDF = gdf
        PARCEL_GDF = gdf.copy()
        SPATIAL_TREE = None
        SPATIAL_GEOMETRY_POSITIONS = {}
        return

    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    if gdf.crs.to_string() != "EPSG:32648":
        gdf = gdf.to_crs(epsg=32648)

    geometry_areas = gdf.geometry.area.round(2)
    stored_area_column = next(
        (column for column in ("dien_tich", "area_sqm", "area") if column in gdf.columns),
        None,
    )
    if stored_area_column is None:
        gdf["dien_tich_m2"] = geometry_areas
    else:
        stored_areas = pd.to_numeric(gdf[stored_area_column], errors="coerce")
        gdf["dien_tich_m2"] = stored_areas.where(stored_areas.notna(), geometry_areas).round(2)
    cols = [column for column in gdf.columns if column != "geometry"]
    search_series = pd.Series("", index=gdf.index, dtype="object")
    for column in cols:
        search_series += gdf[column].apply(clean_text) + " "
    gdf["_search_text"] = search_series

    GDF = gdf
    PARCEL_GDF = GDF[GDF.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    geometries = list(PARCEL_GDF.geometry.values)
    SPATIAL_TREE = STRtree(geometries) if geometries else None
    SPATIAL_GEOMETRY_POSITIONS = {}
    for position, geometry in enumerate(geometries):
        SPATIAL_GEOMETRY_POSITIONS.setdefault(geometry.wkb, []).append(position)


def _parcel_ids(frame: gpd.GeoDataFrame) -> list[str]:
    ids = []
    for index, row in frame.iterrows():
        value = row.get("id", row.get("parcel_code", row.get("ten", index)))
        if pd.isna(value):
            continue
        ids.append(str(value))
    return ids


def _tree_query_positions(query_geometry) -> list[int]:
    if SPATIAL_TREE is None:
        return []

    positions = []
    for item in SPATIAL_TREE.query(query_geometry):
        if isinstance(item, Integral):
            positions.append(int(item))
        else:
            positions.extend(SPATIAL_GEOMETRY_POSITIONS.get(item.wkb, []))
    return list(dict.fromkeys(positions))


def _require_gis_data() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if GDF is None or GDF.empty or PARCEL_GDF is None:
        raise HTTPException(status_code=500, detail="Dữ liệu bản đồ chưa được nạp.")
    return GDF, PARCEL_GDF


def _find_parcel_indices_by_identifier(
    parcels: gpd.GeoDataFrame,
    identifier: str,
    identifier_columns: list[str],
):
    exact_matches = parcels.index[
        parcels[identifier_columns].apply(
            lambda row: any(clean_text(value) == identifier for value in row),
            axis=1,
        )
    ]
    ordinal_pattern = (
        r"(?:(?:thua(?:\s+(?:dat|so|thu))?(?:\s+(?:so|thu))?|parcel)"
        r"\s*#?\s*)?0*(\d+)"
    )
    if len(exact_matches) or not (number_match := re.fullmatch(ordinal_pattern, identifier)):
        return exact_matches

    parcel_number = str(int(number_match.group(1)))
    aliases = []
    if "id" in parcels.columns:
        aliases.append(
            parcels["id"].apply(
                lambda value: bool(
                    re.fullmatch(r"t0*" + re.escape(parcel_number), clean_text(value))
                )
            )
        )
    if "ten" in parcels.columns:
        name_pattern = re.compile(
            r"(?:^|\s)thua\s*0*" + re.escape(parcel_number) + r"\b"
        )
        aliases.append(
            parcels["ten"].apply(
                lambda value: bool(name_pattern.search(clean_text(value)))
            )
        )
    if not aliases:
        return parcels.index[:0]
    matches = aliases[0]
    for alias in aliases[1:]:
        matches |= alias
    return parcels.index[matches]


def _find_object_matches(objects: gpd.GeoDataFrame, keyword: str) -> gpd.GeoDataFrame:
    """Match object identity fields before falling back to descriptions."""
    identity_columns = [
        column for column in ("id", "ten", "name", "loai", "type")
        if column in objects.columns
    ]
    if identity_columns:
        identity_matches = objects[
            objects[identity_columns].apply(
                lambda row: any(keyword in clean_text(value) for value in row),
                axis=1,
            )
        ]
        if not identity_matches.empty:
            return identity_matches
    return objects[objects["_search_text"].str.contains(keyword, regex=False, na=False)]


def load_geojson_features(features: list[dict]) -> None:
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    _index_geodataframe(gdf)


def load_data():
    if not os.path.exists(DATA_FILE):
        print(f"[LỖI CRITICAL] Không tìm thấy file dữ liệu tại: {BASE_DIR}")
        return

    try:
        t0 = time.time()
        gdf = gpd.read_file(DATA_FILE)
        _index_geodataframe(gdf)
        print(f"[OK SUCCESS] Đã nạp thành công {len(GDF)} đối tượng ({round((time.time() - t0)*1000, 2)} ms)")
    except Exception as e:
        print(f"[LỖI CRITICAL] Nạp data thất bại: {str(e)}")


def tim_vi_tri_doi_tuong(tu_khoa: str):
    """Return location and metadata for map objects matching a keyword."""
    objects, _ = _require_gis_data()
    keyword = clean_text(tu_khoa or "")
    if not keyword:
        raise HTTPException(status_code=422, detail="Cần nhập từ khóa đối tượng cần tìm.")

    matches = _find_object_matches(objects, keyword)
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đối tượng '{tu_khoa}'.")

    records = []
    for index, row in matches.iterrows():
        geometry = row.geometry
        point = geometry.centroid if geometry.geom_type != "Point" else geometry
        lon, lat = inverse_transformer.transform(point.x, point.y)
        record = {}
        for column in row.index:
            if column in {"geometry", "_search_text", "dien_tich_m2"}:
                continue
            val = row[column]
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                val = None
            record[column] = val
        record["id"] = str(row.get("id", index))
        record["latitude"] = round(_safe_float(lat), 8)
        record["longitude"] = round(_safe_float(lon), 8)
        record["geometry_type"] = geometry.geom_type
        records.append(record)

    return {
        "tu_khoa": tu_khoa,
        "tong_so": len(records),
        "doi_tuong": records,
        "parcel_ids": [],
    }
# Shared GIS algorithms
# ------------------------------------------------------------------------------

def loc_thua(
    dieu_kien: Optional[str] = None,
    cay_trong: Optional[str] = None,
    do_am_toi_thieu: Optional[float] = None,
    do_am_toi_da: Optional[float] = None,
    gan_doi_tuong: Optional[str] = None,
    ban_kinh_m: Optional[float] = None,
):
    _, parcels = _require_gis_data()
    t0 = time.perf_counter()
    res = parcels.copy()

    if dieu_kien and dieu_kien.strip():
        keyword = clean_text(dieu_kien)
        res = res[res["_search_text"].str.contains(keyword, regex=False, na=False)]

    if cay_trong and cay_trong.strip():
        crop_column = next(
            (column for column in ("cay_trong", "loai_nong_san", "loai_dat") if column in res.columns),
            None,
        )
        if crop_column is None:
            raise HTTPException(status_code=422, detail="Dữ liệu thửa đất không có thuộc tính cây trồng.")
        crop_values = res[crop_column].apply(clean_text)
        res = res[crop_values.str.contains(clean_text(cay_trong), regex=False, na=False)]

    if do_am_toi_thieu is not None or do_am_toi_da is not None:
        humidity_limits = [
            value for value in (do_am_toi_thieu, do_am_toi_da)
            if value is not None
        ]
        if any(not math.isfinite(value) or not 0 <= value <= 100 for value in humidity_limits):
            raise HTTPException(status_code=422, detail="Ngưỡng độ ẩm phải nằm trong khoảng 0 đến 100%.")
        if (
            do_am_toi_thieu is not None
            and do_am_toi_da is not None
            and do_am_toi_thieu > do_am_toi_da
        ):
            raise HTTPException(status_code=422, detail="Độ ẩm tối thiểu không được lớn hơn độ ẩm tối đa.")
        humidity_column = next(
            (column for column in ("do_am", "do_am_pct", "humidity") if column in res.columns),
            None,
        )
        if humidity_column is None:
            raise HTTPException(status_code=422, detail="Dữ liệu thửa đất không có thuộc tính độ ẩm.")
        humidity = pd.to_numeric(res[humidity_column], errors="coerce")
        valid_humidity = humidity.notna()
        if do_am_toi_thieu is not None:
            valid_humidity &= humidity >= do_am_toi_thieu
        if do_am_toi_da is not None:
            valid_humidity &= humidity <= do_am_toi_da
        res = res[valid_humidity]

    if (gan_doi_tuong is None) != (ban_kinh_m is None):
        raise HTTPException(
            status_code=422,
            detail="Lọc theo khoảng cách cần có cả đối tượng mốc và bán kính mét.",
        )
    if ban_kinh_m is not None:
        if not math.isfinite(ban_kinh_m) or ban_kinh_m < 0:
            raise HTTPException(status_code=422, detail="Bán kính phải là số hữu hạn không âm.")
        all_objects, _ = _require_gis_data()
        anchor_keyword = clean_text(gan_doi_tuong or "")
        anchors = all_objects[
            all_objects["_search_text"].str.contains(anchor_keyword, regex=False, na=False)
        ]
        if anchors.empty:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy đối tượng mốc '{gan_doi_tuong}'.",
            )
        distances = res.geometry.apply(lambda geometry: anchors.geometry.distance(geometry).min())
        res = res[distances <= ban_kinh_m].copy()
        res["khoang_cach_m"] = distances.loc[res.index].round(2)

    cols = [column for column in res.columns if column not in ["geometry", "_search_text"]]
    records = res[cols].fillna("").head(20).to_dict(orient="records")
    return {
        "thoi_gian_ms": round((time.perf_counter() - t0) * 1000, 3),
        "tong_so": len(res),
        "parcel_ids": _parcel_ids(res),
        "du_lieu": records,
    }


def thua_cuc_tri(
    truong: str = "dien_tich",
    loai: str = "max"
):
    _, parcels = _require_gis_data()
    normalized_type = clean_text(loai)
    if normalized_type not in {"max", "min", "lon_nhat", "nho_nhat"}:
        raise HTTPException(status_code=422, detail="Loại cực trị chỉ nhận 'max' hoặc 'min'.")

    field_aliases = {
        "dien_tich": "dien_tich_m2",
        "dien_tich_m2": "dien_tich_m2",
        "area_sqm": "dien_tich_m2",
        "area": "dien_tich_m2",
        "do_am": "do_am",
        "do_am_pct": "do_am_pct",
        "humidity": "humidity",
        "nhiet_do": "nhiet_do",
        "temperature": "temperature",
    }
    normalized_field = clean_text(truong)
    col = field_aliases.get(normalized_field, normalized_field)
    allowed_columns = {"dien_tich_m2", "do_am", "do_am_pct", "humidity", "nhiet_do", "temperature"}
    if col not in allowed_columns or col not in parcels.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Trường cực trị '{truong}' không hợp lệ hoặc không có trong dữ liệu thửa đất.",
        )

    numeric_values = pd.to_numeric(parcels[col], errors="coerce")
    valid_values = numeric_values.dropna()
    if valid_values.empty:
        raise HTTPException(status_code=422, detail=f"Cột '{col}' không chứa dữ liệu số hợp lệ.")

    index = valid_values.idxmax() if normalized_type in {"max", "lon_nhat"} else valid_values.idxmin()
    result = parcels.loc[index]
    cols = [column for column in parcels.columns if column not in ["geometry", "_search_text"]]
    result_data = result[cols].fillna("").to_dict()
    return {
        "loai": "MAX" if normalized_type in {"max", "lon_nhat"} else "MIN",
        "truong": col,
        "parcel_ids": _parcel_ids(parcels.loc[[index]]),
        "du_lieu": result_data,
    }


def tinh_tong_dien_tich(
    dieu_kien: Optional[str] = None,
    danh_sach_thua: Optional[list[str]] = None,
):
    _, parcelas = _require_gis_data()
    if danh_sach_thua is not None:
        identifiers = [clean_text(item) for item in danh_sach_thua if clean_text(item)]
        if not identifiers:
            raise HTTPException(status_code=422, detail="Danh sách thửa đất không được để trống.")

        identifier_columns = [
            column for column in ("id", "ten", "parcel_code", "name")
            if column in parcelas.columns
        ]
        if not identifier_columns:
            raise HTTPException(
                status_code=422,
                detail="Dữ liệu thửa đất chưa có mã hoặc tên để chọn thửa cụ thể.",
            )

        selected_indices = []
        for identifier in identifiers:
            matches = _find_parcel_indices_by_identifier(
                parcelas,
                identifier,
                identifier_columns,
            )
            if len(matches) == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy thửa đất '{identifier}'.",
                )
            if len(matches) > 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Mã hoặc tên thửa '{identifier}' không duy nhất; hãy dùng mã thửa.",
                )
            if matches[0] not in selected_indices:
                selected_indices.append(matches[0])

        parcelas = parcelas.loc[selected_indices]

    if dieu_kien and dieu_kien.strip():
        keyword = clean_text(dieu_kien)
        parcelas = parcelas[parcelas["_search_text"].str.contains(keyword, regex=False, na=False)]

    selected_parcels = [
        {
            "id": str(row.get("id", row.get("parcel_code", row.name))),
            "ten": str(row.get("ten", "")),
            "dien_tich_m2": round(float(row["dien_tich_m2"]), 2),
        }
        for _, row in parcelas.iterrows()
    ]
    return {
        "dieu_kien": dieu_kien or (
            "Danh sách thửa cụ thể" if danh_sach_thua is not None else "Tất cả thửa đất"
        ),
        "so_thua": int(len(parcelas)),
        "tong_dien_tich_m2": round(float(parcelas["dien_tich_m2"].sum()), 2),
        "parcel_ids": _parcel_ids(parcelas),
        "cac_thua_da_tinh": selected_parcels,
    }

def thua_gan(
    lat: float,
    lon: float,
    ban_kinh_m: float = 500.0
):
    _, parcels = _require_gis_data()
    if SPATIAL_TREE is None:
        raise HTTPException(status_code=404, detail="Không có polygon thửa đất trong dữ liệu bản đồ.")
    if not all(math.isfinite(value) for value in (lat, lon, ban_kinh_m)):
        raise HTTPException(status_code=422, detail="Tọa độ và bán kính phải là số hữu hạn.")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise HTTPException(status_code=422, detail="Tọa độ vĩ độ/kinh độ nằm ngoài phạm vi hợp lệ.")
    if ban_kinh_m < 0:
        raise HTTPException(status_code=422, detail="Bán kính phải là số không âm.")

    t0 = time.perf_counter()
    x, y = transformer.transform(lon, lat)
    pt = Point(x, y)
    positions = _tree_query_positions(pt.buffer(ban_kinh_m))
    if not positions:
        return {
            "thoi_gian_ms": round((time.perf_counter() - t0) * 1000, 3),
            "tong_so": 0,
            "parcel_ids": [],
            "du_lieu": [],
        }

    sub = parcels.iloc[positions].copy()
    sub["khoang_cach_m"] = sub.geometry.distance(pt).round(2)
    res = sub[sub["khoang_cach_m"] <= ban_kinh_m].sort_values("khoang_cach_m")

    cols = [c for c in res.columns if c not in ["geometry", "_search_text"]]
    records = res[cols].fillna("").head(10).to_dict(orient="records")
    return {
        "thoi_gian_ms": round((time.perf_counter() - t0) * 1000, 3),
        "tong_so": len(res),
        "parcel_ids": _parcel_ids(res.head(10)),
        "du_lieu": records
    }


def khoang_cach(dt1: str, dt2: str):
    objects, parcels = _require_gis_data()

    k1, k2 = clean_text(dt1), clean_text(dt2)
    if not k1 or not k2:
        raise HTTPException(status_code=422, detail="Cần nhập từ khóa cho cả hai đối tượng.")

    parcel_identifier_columns = [
        column for column in ("id", "ten", "parcel_code", "name")
        if column in parcels.columns
    ]

    def matching_objects(keyword):
        if keyword.startswith(("thua", "parcel")) and not re.fullmatch(
            r"(?:thua|parcel)\s*#?\s*0*\d+",
            keyword,
        ):
            return parcels
        parcel_matches = _find_parcel_indices_by_identifier(
            parcels,
            keyword,
            parcel_identifier_columns,
        )
        if len(parcel_matches):
            return parcels.loc[parcel_matches]
        return _find_object_matches(objects, keyword)

    g1 = matching_objects(k1)
    g2 = matching_objects(k2)

    if g1.empty:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đối tượng 1 với từ khóa '{dt1}'")
    if g2.empty:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đối tượng 2 với từ khóa '{dt2}'")

    nearest = None
    for index_1, object_1 in g1.iterrows():
        for index_2, object_2 in g2.iterrows():
            if index_1 == index_2:
                continue
            distance = float(object_1.geometry.distance(object_2.geometry))
            if nearest is None or distance < nearest[0]:
                nearest = (distance, index_1, object_1, index_2, object_2)
    if nearest is None:
        raise HTTPException(status_code=422, detail="Cần chọn hai đối tượng khác nhau để tính khoảng cách.")

    distance, index_1, object_1, index_2, object_2 = nearest

    def object_label(row, index):
        for column in ("ten", "name", "parcel_code", "id"):
            value = row.get(column)
            if value is not None and not pd.isna(value) and str(value).strip():
                return str(value)
        return str(index)

    parcel_indices = [
        index for index, row in ((index_1, object_1), (index_2, object_2))
        if row.geometry.geom_type in {"Polygon", "MultiPolygon"}
    ]
    parcel_ids = _parcel_ids(parcels.loc[parcel_indices]) if parcel_indices else []
    return {
        "doi_tuong_1": dt1,
        "doi_tuong_2": dt2,
        "doi_tuong_1_tim_duoc": object_label(object_1, index_1),
        "doi_tuong_2_tim_duoc": object_label(object_2, index_2),
        "id_1": str(object_1.get("id", index_1)),
        "id_2": str(object_2.get("id", index_2)),
        "khoang_cach_met": round(distance, 2),
        "parcel_ids": parcel_ids,
    }


