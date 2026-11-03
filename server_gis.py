"""Compatibility GIS server built on the shared GIS service."""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from gis_service import (
    clean_text,
    load_data,
    load_geojson_features,
    loc_thua,
    thua_cuc_tri,
    tinh_tong_dien_tich,
    thua_gan,
    khoang_cach,
    tim_vi_tri_doi_tuong,
)

app = FastAPI(title="Mini GIS Backend", description="Compatibility server for shared GIS algorithms")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def startup_load_data():
    load_data()


@app.get("/api/loc-thua")
def api_loc_thua(
    dieu_kien: str | None = Query(default=None),
    cay_trong: str | None = Query(default=None),
    do_am_toi_thieu: float | None = Query(default=None),
    do_am_toi_da: float | None = Query(default=None),
    gan_doi_tuong: str | None = Query(default=None),
    ban_kinh_m: float | None = Query(default=None),
):
    return loc_thua(dieu_kien, cay_trong, do_am_toi_thieu, do_am_toi_da, gan_doi_tuong, ban_kinh_m)


@app.get("/api/thua-cuc-tri")
def api_thua_cuc_tri(truong: str = "dien_tich", loai: str = "max"):
    return thua_cuc_tri(truong, loai)


@app.get("/api/tong-dien-tich")
def api_tinh_tong_dien_tich(
    dieu_kien: str | None = Query(default=None),
    danh_sach_thua: list[str] | None = Query(default=None),
):
    return tinh_tong_dien_tich(dieu_kien, danh_sach_thua)


@app.get("/api/thua-gan")
def api_thua_gan(lat: float, lon: float, ban_kinh_m: float = 500.0):
    return thua_gan(lat, lon, ban_kinh_m)


@app.get("/api/khoang-cach")
def api_khoang_cach(dt1: str, dt2: str):
    return khoang_cach(dt1, dt2)


@app.get("/api/vi-tri-doi-tuong")
def api_tim_vi_tri_doi_tuong(tu_khoa: str):
    return tim_vi_tri_doi_tuong(tu_khoa)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server_gis:app", host="127.0.0.1", port=8001, reload=True)
