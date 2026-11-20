# Hệ thống AI bản đồ nông nghiệp

Ứng dụng web bản đồ GIS cho dữ liệu thửa đất nông nghiệp, có đăng nhập, phân quyền theo tài khoản, quản lý thửa đất, và trợ lý chat hỗ trợ tra cứu dữ liệu GIS bằng Gemini Function Calling. Nếu Gemini không khả dụng, hệ thống có thể trả lời một số yêu cầu GIS bằng bộ xử lý nội bộ.

## Tính năng chính

- **Bản đồ GIS**: Hiển thị thửa đất (polygon) và đối tượng bản đồ (giếng, nhà kho) bằng Leaflet.
- **Phân quyền**: Tài khoản `admin` và `user`. User thường chỉ xem/tra cứu thửa của chính mình; admin thấy tất cả và quản lý đối tượng hệ thống.
- **Quản lý thửa đất**: Thêm, sửa, xóa thửa; vẽ ranh giới polygon trên bản đồ; lưu thuộc tính (mã thửa, tên, loại cây trồng, độ ẩm, nhiệt độ, ghi chú).
- **Chat AI GIS**: Gemini Function Calling tra cứu dữ liệu GIS (thông tin thửa, lọc theo điều kiện, tổng diện tích, cực trị, khoảng cách, vị trí, thửa gần nhất). Khi Gemini không khả dụng, fallback GIS nội bộ trả lời các truy vấn phổ biến.
- **Tổng quan nông trại**: Thống kê số thửa, tổng diện tích, số loại cây trồng; biểu đồ nông sản (pie chart + bar chart) theo loại cây trồng.
- **Vị trí GPS**: Lưu và hiển thị vị trí GPS của người dùng.
- **Weather**: Tra cứu thời tiết qua OpenWeatherMap/Open-Meteo/WTTR.in.

## Kiến trúc

- **Backend**: FastAPI (`main.py`) + SQL Server qua SQLAlchemy/pyodbc (`database.py`, `models.py`).
- **GIS Engine**: Thuần Python (`gis_service.py`, `server_gis.py` wrapper) dùng GeoPandas/Shapely/STRtree.
- **Frontend**: HTML + JavaScript thuần (`index.html`, `script.js`, `auth.js`) với Leaflet.
- **AI**: Google Gemini API (Function Calling) với fallback GIS nội bộ.

## Yêu cầu

- Windows với Python 3.11.
- SQL Server và ODBC Driver 17 for SQL Server; tài khoản Windows chạy ứng dụng cần quyền truy cập cơ sở dữ liệu.
- Gemini API key nếu muốn sử dụng Gemini. Khóa thời tiết OpenWeatherMap là tùy chọn.

## Cài đặt và chạy local

1. Tạo môi trường Python và cài dependencies:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Tạo `.env` từ mẫu rồi chỉnh các giá trị phù hợp với máy:

   ```powershell
   Copy-Item .env.example .env
   ```

   Cần đổi `SESSION_SECRET` và `DEFAULT_ADMIN_PASSWORD`, cấu hình SQL Server, và đặt `GEMINI_API_KEY` nếu dùng Gemini. Không chia sẻ hoặc commit `.env`.

3. Khởi chạy:

   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

   Mở `http://127.0.0.1:8000`. Khi khởi động, ứng dụng tạo bảng còn thiếu, chạy các bước nâng cấp schema hiện có và tạo tài khoản `admin` nếu chưa có. Mật khẩu ban đầu được lấy từ `DEFAULT_ADMIN_PASSWORD`.

   Dữ liệu mẫu trong `data.json` chỉ được thêm nếu mã thửa/đối tượng chưa có trong database. Các bản ghi hiện có không bị cập nhật hoặc xóa bởi bước seed này.

## Kiểm thử

Chạy bộ kiểm thử hồi quy được duy trì trong repository:

```powershell
python -m unittest discover -s tests -v
```

Một số kiểm thử cũ ở thư mục gốc là script cục bộ và không thuộc bộ kiểm thử duy trì.

## Chẩn đoán Gemini

Làm theo [Hướng dẫn chẩn đoán Gemini trong 5 phút](./HUONG_DAN_CHAN_DOAN_AI.md) để lưu kết quả health, probe live model, xác minh tool GIS thực tế và kiểm tra highlight thửa đất.

## Cấu trúc thư mục chính

- `main.py`: FastAPI app, endpoints, AI pipeline, GIS tools.
- `gis_service.py`: Engine GIS thuần (lọc, cực trị, tổng diện tích, khoảng cách, thửa gần nhất, thời tiết).
- `models.py`: SQLAlchemy models (`User`, `Parcel`, `MapObject`, `ChatHistory`, ...).
- `database.py`: Kết nối SQL Server, migrations.
- `parcel_utils.py`: Validate geometry, tính diện tích.
- `index.html`, `script.js`, `auth.js`: Frontend bản đồ + chat.
- `admin.html`: Trang quản trị.
- `login.html`: Trang đăng nhập.
- `tests/`: Bộ kiểm thử hồi quy.
- `data.json`: Dữ liệu mẫu thửa đất và đối tượng.

## API chính

- `GET /api/parcels/geojson`: Lấy ranh giới thửa đất (user chỉ thấy thửa của mình).
- `GET /api/objects/geojson`: Lấy đối tượng điểm (chỉ admin).
- `GET /api/loc-thua`: Lọc thửa theo điều kiện/cây trồng/độ ẩm.
- `GET /api/thua-cuc-tri`: Thửa có diện tích/độ ẩm/nhiệt độ cao nhất/thấp nhất.
- `GET /api/tong-dien-tich`: Tính tổng diện tích.
- `GET /api/thua-gan`: Thửa gần tọa độ.
- `GET /api/khoang-cach`: Khoảng cách giữa hai đối tượng/thửa.
- `POST /api/chat`: Chat AI Gemini có Function Calling.
- `GET /api/health`: Kiểm tra trạng thái hệ thống.
- `POST /api/parcels`, `PUT /api/parcels/{id}`, `DELETE /api/parcels/{id}`: Quản lý thửa đất.
- `POST /api/user/location`, `GET /api/user/location`: Vị trí GPS người dùng.

## Biến môi trường

Xem `.env.example` để biết các biến cấu hình. Quan trọng nhất:

- `SESSION_SECRET`: Khóa bí mật cho session (bắt buộc đổi).
- `DEFAULT_ADMIN_PASSWORD`: Mật khẩu admin ban đầu.
- `SQLSERVER_HOST`, `SQLSERVER_DATABASE`: Kết nối SQL Server.
- `GEMINI_API_KEY`: API key Gemini (tùy chọn).
- `CORS_ALLOWED_ORIGINS`: Các origin được phép CORS.

## Lưu ý bảo mật

- Không commit file `.env` (đã có trong `.gitignore`).
- Mật khẩu admin mặc định cần đổi ngay sau khi triển khai.
- Các truy vấn GIS của user thường được lọc theo `user_id` để bảo vệ dữ liệu. Geometry của thửa đất và thông tin chủ thửa chỉ hiển thị cho admin.
- API key Gemini cần được bảo vệ, không chia sẻ.

## Tác giả

Hệ thống AI bản đồ nông nghiệp — Đồ án thực tập.
