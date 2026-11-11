# Hệ thống AI bản đồ nông nghiệp

Ứng dụng web bản đồ GIS cho dữ liệu thửa đất nông nghiệp, có đăng nhập và trợ lý chat
hỗ trợ tra cứu dữ liệu GIS bằng Gemini Function Calling. Nếu Gemini không khả dụng,
hệ thống có thể trả lời một số yêu cầu GIS bằng bộ xử lý nội bộ.

## Yêu cầu

- Windows với Python 3.11 (phiên bản đã dùng để kiểm tra dự án).
- SQL Server và ODBC Driver 17 for SQL Server; tài khoản Windows chạy ứng dụng cần
  quyền truy cập cơ sở dữ liệu.
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

   Cần đổi `SESSION_SECRET` và `DEFAULT_ADMIN_PASSWORD`, cấu hình SQL Server,
   và đặt `GEMINI_API_KEY` nếu dùng Gemini. Không chia sẻ hoặc commit `.env`.

3. Khởi chạy:

   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

   Mở `http://127.0.0.1:8000`. Khi khởi động, ứng dụng tạo bảng còn thiếu, chạy các
   bước nâng cấp schema hiện có và tạo tài khoản `admin` nếu chưa có. Mật khẩu ban đầu
   được lấy từ `DEFAULT_ADMIN_PASSWORD`.

   Dữ liệu mẫu trong `data.json` chỉ được thêm nếu mã thửa/đối tượng chưa có trong
   database. Các bản ghi hiện có không bị cập nhật hoặc xóa bởi bước seed này.

## Kiểm thử

Chạy bộ kiểm thử hồi quy được duy trì trong repository:

```powershell
python -m unittest discover -s tests -v
```

Một số kiểm thử cũ ở thư mục gốc là script cục bộ và không thuộc bộ kiểm thử duy trì.

## Chẩn đoán Gemini

Làm theo [Hướng dẫn chẩn đoán Gemini trong 5 phút](./HUONG_DAN_CHAN_DOAN_AI.md) để lưu
kết quả health, probe live model, xác minh tool GIS thực tế và kiểm tra highlight thửa đất.