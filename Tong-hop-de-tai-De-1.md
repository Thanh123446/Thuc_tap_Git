# TỔNG HỢP CHI TIẾT ĐỀ TÀI – ĐỀ 1

## 1. Tên đề tài

**Xây dựng hệ thống Chat AI hỗ trợ quản lý nông nghiệp kết hợp bản đồ GIS.**

Tên gọi khác có thể sử dụng trong slide: **Ứng dụng Chat AI kết hợp GIS trong tra cứu và quản lý thửa đất nông nghiệp.**

## 2. Bối cảnh và lý do chọn đề tài

Trong quản lý nông nghiệp, thông tin về thửa đất, cây trồng, diện tích, độ ẩm và vị trí thường được lưu trữ riêng lẻ. Người dùng có thể gặp khó khăn khi phải tìm kiếm dữ liệu hoặc thực hiện các phép tính không gian bằng công cụ kỹ thuật.

Đề tài kết hợp hai công nghệ:

- **GIS:** Quản lý, hiển thị và phân tích dữ liệu theo vị trí địa lý.
- **Chat AI:** Cho phép người dùng đặt câu hỏi bằng ngôn ngữ tự nhiên.

Kết quả truy vấn được trả về dưới dạng văn bản và hiển thị trực quan trên bản đồ.

## 3. Mục tiêu đề tài

- Xây dựng hệ thống quản lý dữ liệu thửa đất nông nghiệp.
- Hiển thị thửa đất và các đối tượng liên quan trên bản đồ tương tác.
- Cho phép người dùng đặt câu hỏi bằng tiếng Việt.
- Tích hợp Google Gemini để phân tích yêu cầu.
- Kết nối Gemini với các công cụ xử lý GIS bằng Function Calling.
- Hỗ trợ tìm kiếm, lọc, tính diện tích và tính khoảng cách.
- Làm nổi bật kết quả truy vấn trực tiếp trên bản đồ.
- Xây dựng chức năng đăng nhập, phân quyền và quản trị dữ liệu.

## 4. Tổng quan và kiến trúc hệ thống

Hệ thống gồm frontend, backend, AI, GIS Engine và cơ sở dữ liệu.

```text
Người dùng
    ↓
Giao diện Web HTML/CSS/JavaScript
    ↓
FastAPI Backend
    ├── Xác thực và phân quyền
    ├── Dịch vụ xử lý GIS
    ├── Dịch vụ Chat Gemini
    └── Cơ sở dữ liệu SQL Server
```

## 5. Quy trình hoạt động của Chat AI

```text
Người dùng nhập câu hỏi
        ↓
Backend gửi câu hỏi cho Gemini
        ↓
Gemini phân tích ý định và chọn công cụ GIS
        ↓
Backend truy vấn dữ liệu thửa đất
        ↓
Kết quả trả về cho Gemini
        ↓
Gemini tạo câu trả lời bằng tiếng Việt
        ↓
Frontend hiển thị câu trả lời và highlight bản đồ
```

Ví dụ: người dùng hỏi **“Tìm các thửa trồng rau có độ ẩm dưới 30%.”** Gemini sẽ nhận diện yêu cầu lọc thửa, gọi công cụ GIS tương ứng và trả về danh sách thửa phù hợp.

## 6. Dữ liệu sử dụng

- **12 thửa đất dạng Polygon:** T1 đến T12.
- **2 đối tượng dạng Point:** nhà kho trung tâm và giếng tưới.
- Thông tin thửa gồm mã thửa, tên thửa, cây trồng, diện tích, độ ẩm, nhiệt độ và ranh giới GeoJSON.
- Dữ liệu được lưu trong `data.json`, `data.js` và có thể nạp vào SQL Server.

Dữ liệu hiện tại chủ yếu phục vụ mô phỏng, kiểm thử và trình diễn.

## 7. Các chức năng đã xây dựng

### Bản đồ GIS

- Hiển thị bản đồ bằng Leaflet.
- Hiển thị thửa đất dạng Polygon và đối tượng dạng Point.
- Hiển thị popup thông tin chi tiết.
- Tô màu hoặc làm nổi bật thửa đất theo kết quả truy vấn.
- Tự động tập trung bản đồ vào khu vực kết quả.

### Phân tích GIS

- Lọc theo loại cây trồng, độ ẩm và từ khóa.
- Tìm thửa trong bán kính từ một vị trí.
- Tìm thửa có diện tích, độ ẩm hoặc nhiệt độ lớn nhất/nhỏ nhất.
- Tính tổng diện tích các thửa phù hợp.
- Tính khoảng cách giữa hai thửa hoặc hai đối tượng.

### Chat AI

- Chat bằng tiếng Việt tự nhiên.
- Lưu lịch sử hội thoại.
- Gửi hình ảnh kèm câu hỏi.
- Sử dụng Gemini Function Calling.
- Trả về câu trả lời và mã thửa đất liên quan.
- Highlight kết quả trên bản đồ.

### Quản trị và báo cáo

- Xem thống kê tổng quan.
- Quản lý người dùng và cấp quyền Admin.
- Xem, tìm kiếm và xóa lịch sử chat.
- Thêm, sửa, xóa và tìm kiếm thửa đất.
- Thống kê diện tích, loại cây trồng và cảnh báo độ ẩm/nhiệt độ.
- Xuất dữ liệu CSV hoặc phục vụ in/lưu PDF.

## 8. Thuật toán và công nghệ GIS

- **GeoJSON:** Lưu trữ dữ liệu hình học.
- **Shapely:** Xử lý Polygon, Point, diện tích và khoảng cách.
- **GeoPandas:** Quản lý dữ liệu địa lý dạng bảng.
- **PyProj:** Chuyển đổi hệ tọa độ.
- **STRtree:** Spatial Index giúp tìm kiếm đối tượng không gian nhanh hơn.

Khi tính khoảng cách hoặc diện tích, dữ liệu có thể được chuyển từ WGS84 sang UTM để kết quả tính theo mét phù hợp hơn.

## 9. Cơ sở dữ liệu

Hệ thống sử dụng SQLAlchemy để kết nối SQL Server. Các nhóm dữ liệu chính gồm:

- **Người dùng:** tài khoản, mật khẩu mã hóa, họ tên, vai trò và trạng thái.
- **Thửa đất:** mã thửa, tên thửa, cây trồng, GeoJSON, diện tích, độ ẩm và nhiệt độ.
- **Lịch sử chat:** câu hỏi, câu trả lời AI, người dùng và thời gian.
- **Log lỗi AI:** model, loại lỗi, nội dung lỗi và thời gian phát sinh.

## 10. Bảo mật và phân quyền

- Đăng ký và đăng nhập tài khoản.
- Mã hóa mật khẩu bằng Bcrypt.
- Xác thực API bằng Bearer Token.
- Ký token bằng HMAC-SHA256.
- Phân quyền User và Admin.
- Giới hạn API quản trị cho Admin.
- Kiểm tra dữ liệu GeoJSON đầu vào.
- Kiểm soát CORS theo cấu hình.
- Hạn chế ghi API key hoặc thông tin nhạy cảm vào log.

## 11. Công nghệ sử dụng

- **Frontend:** HTML, CSS, JavaScript, Leaflet.
- **Backend:** Python, FastAPI, Pydantic.
- **AI:** Google Gemini API và Function Calling.
- **GIS:** GeoPandas, Shapely, PyProj, STRtree.
- **Cơ sở dữ liệu:** SQL Server, SQLAlchemy.
- **Bảo mật:** Bcrypt, Bearer Token, HMAC-SHA256.
- **Kiểm thử:** test xác thực, GIS, AI tools và cơ sở dữ liệu.

## 12. Đối chiếu với yêu cầu của Đề 1

| Yêu cầu | Kết quả thực hiện | Đánh giá |
|---|---|---|
| Xây dựng Chat AI trong nông nghiệp | Tích hợp Gemini và chat tiếng Việt | Đã hoàn thành |
| Kết hợp Chat AI với GIS | Gemini gọi các công cụ GIS | Đã hoàn thành |
| Hiển thị bản đồ | Leaflet và GeoJSON | Đã hoàn thành |
| Quản lý thửa đất | Có dữ liệu và chức năng quản lý | Đã hoàn thành, cần kiểm tra Admin |
| Tra cứu bằng ngôn ngữ tự nhiên | Hỏi trực tiếp bằng tiếng Việt | Đã hoàn thành |
| Lọc thửa đất | Lọc theo cây trồng, độ ẩm, từ khóa và vị trí | Đã hoàn thành |
| Tính diện tích | Tính diện tích và tổng diện tích | Đã hoàn thành |
| Tính khoảng cách | Tính giữa các đối tượng | Đã hoàn thành |
| Tìm thửa cực trị | Tìm lớn nhất/nhỏ nhất | Đã hoàn thành |
| Hiển thị kết quả trực quan | Highlight trên bản đồ | Đã hoàn thành |
| Đăng nhập và phân quyền | User/Admin và Bearer Token | Đã hoàn thành |
| Lưu lịch sử và quản trị | Có lịch sử chat và trang Admin | Hoàn thành một phần |
| Hỗ trợ hình ảnh | Có giao diện gửi ảnh cho Gemini | Cần kiểm thử thực tế |
| Dự báo thời tiết | Có khung tool, chưa có dữ liệu trực tuyến | Chưa hoàn thiện |
| Tra cứu giá nông sản | Có khung tool, chưa có nguồn giá thật | Chưa hoàn thiện |

## 13. Kết quả đạt được

Quy trình demo chính:

1. Người dùng đăng nhập.
2. Hệ thống hiển thị các thửa đất trên bản đồ.
3. Người dùng đặt câu hỏi bằng tiếng Việt.
4. Gemini phân tích câu hỏi và gọi công cụ GIS.
5. Backend xử lý dữ liệu thửa đất.
6. AI trả lời bằng ngôn ngữ tự nhiên.
7. Bản đồ highlight các thửa liên quan.
8. Kết quả được lưu lịch sử và có thể đưa vào báo cáo.

**Mức độ hoàn thành ước tính: khoảng 80–85% chức năng cốt lõi.**

## 14. Kịch bản demo đề xuất

- **Tìm theo cây trồng:** “Tìm các thửa đang trồng lúa.”
- **Kết hợp điều kiện:** “Tìm các thửa trồng rau có độ ẩm dưới 30%.”
- **Tổng diện tích:** “Tính tổng diện tích các thửa trồng lúa.”
- **Tìm cực trị:** “Thửa nào có diện tích lớn nhất?”
- **Tính khoảng cách:** “Khoảng cách từ giếng tưới đến thửa T1 là bao nhiêu?”
- **Admin:** xem thống kê, lịch sử chat, người dùng và quản lý thửa đất.

## 15. Hạn chế hiện tại

- Dữ liệu chủ yếu là dữ liệu mẫu và số lượng thửa còn ít.
- Chưa kết nối API thời tiết thực tế.
- Chưa kết nối nguồn giá nông sản trực tuyến.
- Phân tích hình ảnh phụ thuộc vào model và API key Gemini.
- Hệ thống phụ thuộc cấu hình SQL Server và môi trường chạy.
- Trang Admin cần kiểm tra thêm phạm vi một số hàm JavaScript.
- Chưa triển khai trên máy chủ hoặc môi trường cloud.

## 16. Hướng phát triển

- Kết nối API thời tiết theo vị trí thửa đất.
- Kết nối dữ liệu giá nông sản theo khu vực và thời gian.
- Bổ sung cảm biến IoT về độ ẩm đất, nhiệt độ và lượng mưa.
- Nhận diện sâu bệnh hoặc tình trạng cây trồng qua hình ảnh.
- Dự báo năng suất dựa trên lịch sử canh tác và thời tiết.
- Mở rộng số lượng thửa đất và cập nhật dữ liệu thực tế.
- Tối ưu tốc độ truy vấn và triển khai trên cloud.

## 17. Nội dung đề xuất cho slide

1. Tên đề tài và thành viên.
2. Bối cảnh và lý do chọn đề tài.
3. Mục tiêu.
4. Yêu cầu Đề 1.
5. Kiến trúc hệ thống.
6. Công nghệ sử dụng.
7. Dữ liệu và cơ sở dữ liệu.
8. Giao diện bản đồ GIS.
9. Cơ chế Chat AI và Function Calling.
10. Các chức năng demo.
11. Đăng nhập, phân quyền và Admin.
12. Kết quả, hạn chế và hướng phát triển.

## 18. Kết luận

Đề tài đã xây dựng được hệ thống Chat AI kết hợp GIS nhằm hỗ trợ tra cứu và quản lý thông tin nông nghiệp. Người dùng có thể đặt câu hỏi bằng ngôn ngữ tự nhiên; hệ thống phân tích yêu cầu, gọi công cụ GIS để xử lý dữ liệu thửa đất và trả về kết quả bằng văn bản kết hợp bản đồ trực quan.

Các chức năng cốt lõi như quản lý thửa đất, lọc dữ liệu, tính diện tích, tính khoảng cách, tìm kiếm không gian, đăng nhập, phân quyền và quản trị đã được triển khai. Một số chức năng mở rộng như dự báo thời tiết và tra cứu giá nông sản cần tiếp tục phát triển.

**Đánh giá chung:** Hệ thống đã hoàn thành phần lõi của Đề 1 và có thể sử dụng làm bản demo báo cáo.