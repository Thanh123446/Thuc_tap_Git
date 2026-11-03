# BÁO CÁO: FUNCTION CALLING (GỌI HÀM) TRONG LLM

**Môn học:** Công nghệ Trí Tuệ Nhân Tạo  
**Đề tài:** Function Calling trong Large Language Model (LLM)  
**Ngày báo cáo:** 28/10/2026  
**Ngôn ngữ:** Tiếng Việt  

---

## MỤC LỤC

1. Giới thiệu
2. Function Calling là gì?
3. Tại sao LLM cần Function Calling?
4. Cơ chế hoạt động của Function Calling
5. So sánh: LLM không có Function Calling và có Function Calling
6. Ứ dụng thực tế trong dự án
7. Kết luận
8. Tài liệu tham khảo

---

## 1. GIỚI THIỆU

Large Language Model (LLM) là mô hình AI được huấn luyện trên khối lượng lớn dữ liệu văn bản, có khả năng hiểu và tạo ra ngôn ngữ tự nhiên. Tuy nhiên, LLM có một số hạn chế:
- Dữ liệu huấn luyện bị giới hạn theo thời gian (cũ)
- Không thể truy cập thông tin thời gian thực (thời tiết, giá vàng, giá cổ phiếu...)
- Không thể thực hiện hành động ngoài vòng tròn chat (đặt vé, cập nhật database, gửi email...)

Function Calling ra đời để khắc phục những hạn chế này, giúp LLM kết nối với thế giới thực thông qua các hàm/công cụ đã được định nghĩa sẵn.

---

## 2. FUNCTION CALLING LÀ GÌ?

**Định nghĩa:**
Function Calling (gọi hàm) là khả năng của mô hình LLM hiểu ý định của người dùng, chọn một hàm/công cụ đã được định nghĩa sẵn, và xuất ra các tham số cần gọi để thực hiện tác vụ đó.

**Khái niệm cốt lõi:**
- LLM **không tự chạy hàm**, mà chỉ ra "bạn nên gọi hàm A với tham số B"
- Hệ thống ngoài (code Python/Backend) thực sự gọi hàm và trả kết quả về cho LLM
- LLM tiếp tục xử lý kết quả và trả lời người dùng bằng ngôn ngữ tự nhiên

**Ví dụ minh họa:**
Người dùng hỏi: "Thời tiết Hà Nội hôm nay thế nào?"

1. LLM phân tích và nhận ra cần gọi hàm `get_weather()` với tham số `{thanh_pho: "Hà Nội"}`
2. Backend gọi API thời tiết (Open-Meteo, OpenWeatherMap...) và nhận kết quả: 27°C, mưa rào
3. LLM tổng hợp kết quả và trả lời: "Hà Nội hôm nay 27°C, có mưa rào, bạn nên mang theo ô"

---

## 3. TẠI SAO LLM CẦN FUNCTION CALLING?

### 3.1 Kết nối LLM với thế giới thực
LLM chỉ được huấn luyện trên dữ liệu đến một thời điểm nhất định, không biết thông tin mới nhất. Function Calling cho phép LLM gọi API để lấy dữ liệu real-time.

### 3.2 Thực hiện hành động thay vì chỉ trả lời
Thay vì chỉ gợi ý "Bạn có thể đặt vé tại trang web X", LLM có thể gọi hàm `dat_ve()` và thực sự hỗ trợ thực hiện hành động.

### 3.3 Tính chính xác cao
Thay vì LLM bịa ra số liệu (hallucination), Function Calling gọi hàm thực sự trả về giá trị chính xác từ database hoặc API.

### 3.4 Tự động hóa quy trình
Kết hợp nhiều hàm để xử lý quy trình phức tạp: kiểm tra thời tiết → nếu mưa thì gợi ý hoãn giao hàng → cập nhật trạng thái đơn hàng.

---

## 4. CƠ CHẾ HOẠT ĐỘNG CỦA FUNCTION CALLING

Quy trình xử lý gồm 3 bước chính:

### Bước 1: LLM phân tích ý định
Người dùng gửi câu hỏi → LLM nhận diện cần gọi hàm nào và tham số gì.

### Bước 2: Backend thực thi hàm
Hệ thống gọi hàm/API thực tế và nhận kết quả.

### Bước 3: LLM tổng hợp và trả lời
LLM nhận kết quả từ hàm, xử lý và trả lời người dùng bằng ngôn ngữ tự nhiên.

**Các thành phần chính:**
- **Function Schema:** Mô tả tên hàm, mục đích, tham số (theo JSON Schema)
- **LLM Response:** Trả về tên hàm + tham số (thường là định dạng JSON)
- **Executor:** Code thực tế gọi hàm và lấy kết quả

---

## 5. SO SÁNH: LLM KHÔNG CÓ FUNCTION CALLING VÀ CÓ FUNCTION CALLING

| Tiêu chí | LLM không Function Calling | LLM có Function Calling |
|----------|---------------------------|-------------------------|
| Nguồn dữ liệu | Chỉ dữ liệu huấn luyện (cũ) | Lấy dữ liệu real-time từ API/DB |
| Chính xác성 | Có thể bịa (hallucination) | Lấy từ nguồn thực sự |
| Khả năng hành động | Chỉ trả lời văn bản | Gọi hàm, thực hiện tác vụ |
| Tự động hóa | Thủ công, copy-paste | Tự động luồng công việc |
| Ví dụ trả lời | "Bạn có thể xem thời tiết ở trang web X" | "Hà Nội 27°C, có mưa, mang theo ô" |

**Ví dụ cụ thể:** Người dùng hỏi "Thời tiết Hồ Chí Minh hôm nay?"

**Không có Function Calling:**
LLM trả lời dựa trên dữ liệu cũ, có thể bịa ra nhiệt độ sai, không thể lấy dữ liệu thực tế.

**Có Function Calling:**
LLM gọi hàm `get_weather("Hồ Chí Minh")`, nhận kết quả 27°C mưa rào từ API, rồi trả lời chính xác và hữu ích.

---

## 6. ỨNG DỤNG THỰC TẾ TRONG DỰ ÁN

Trong dự án "Hệ thống Thời tiết & Vận chuyển hàng hóa", Function Calling được áp dụng như sau:

### 6.1 Công cụ du báo thời tiết (`tool_du_bao_thoi_tiet` trong `main.py`)
- LLM nhận dạng thành phố từ câu hỏi của người dùng
- Gọi API Open-Meteo / WTTR.in / OpenWeatherMap
- Trả về nhiệt độ, độ ẩm, gió, mã thời tiết kèm nguồn tham khảo

### 6.2 Hệ thống vận chuyển hàng hóa
- Kiểm tra địa chỉ giao hàng (GIS)
- Cập nhật trạng thái đơn hàng trong database
- Tính khoảng cách và ước lượng thời gian giao

**Lợi ích trong dự án:**
- Người dùng chat bằng tiếng Việt tự nhiên
- Hệ thống tự động lấy dữ liệu thời tiết chính xác
- Giảm thiểu sai sót do nhập liệu thủ công

---

## 7. KẾT LUẬN

Function Calling biến LLM từ "trò chuyện" thành "làm việc". Đây là công nghệ quan trọng giúp:

- ✅ Kết nối LLM với API, database, công cụ ngoài
- ✅ Trả lời chính xác, cập nhật real-time
- ✅ Thực hiện hành động thay vì chỉ gợi ý
- ✅ Dễ tích hợp vào ứng dụng thực tế (thời tiết, vận chuyển, hỗ trợ khách hàng, v.v.)

Với Function Calling, LLM không còn chỉ là một công cụ trả lời câu hỏi, mà trở thành một trợ lý thông minh có khả năng tương tác với thế giới thực.

---

## 8. TÀI LIỆU THAM KHẢO

1. OpenAI Function Calling Documentation - https://platform.openai.com/docs/guides/function-calling
2. Anthropic Tool Use Documentation - https://docs.anthropic.com/claude/docs/tool-use
3. Gemini Function Calling Documentation - https://ai.google.dev/gemini-api/docs/function-calling
4. Dự án Thời tiết & Vận chuyển hàng hóa (mã nguồn tại `D:\DuAnThucTap-main\DuAnThucTap-main\main.py`)

---

**Kết thúc báo cáo**

---
**File:** `BaoCao_Function_Calling.md`  
**Vị trí:** `D:\DuAnThucTap-main\DuAnThucTap-main\BaoCao_Function_Calling.md`
