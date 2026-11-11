// --- 0. LẤY THÔNG TIN NGƯỜI DÙNG ĐĂNG NHẬP ---
// currentUser và authToken đã được khai báo trong auth guard của index.html

// --- 1. KHỞI TẠO BẢN ĐỒ ---
// `map` được khởi tạo trong index.html (initMap), script.js chỉ sử dụng biến toàn cục đó
let geojsonLayer = null;
let selectedParcelIds = [];

// --- 2. BẢNG MÀU PHÂN LOẠI CÂY TRỒNG ---
function getColorByCrop(type) {
    if (!type) return '#9ca3af'; 
    const cropType = type.toString().trim().toUpperCase();

    if (cropType.includes('LÚA') || cropType === 'LUC') return '#10b981'; // Xanh lá
    if (cropType.includes('RAU') || cropType.includes('HOA MÀU') || cropType === 'BHK') return '#84cc16'; // Đọt chuối
    if (cropType.includes('QUẢ') || cropType.includes('CAM') || cropType.includes('XOÀI')) return '#f97316'; // Cam
    if (cropType.includes('CÀ PHÊ') || cropType === 'CLN') return '#8b5cf6'; // Tím
    if (cropType.includes('TÔM') || cropType.includes('CÁ') || cropType === 'NTS') return '#06b6d4'; // Xanh dương
    if (cropType.includes('Ở') || cropType === 'ONT') return '#ef4444'; // Đỏ

    return '#6b7280'; 
}


function highlightParcels(parcelIds) {
    selectedParcelIds = Array.isArray(parcelIds) ? parcelIds : [];
    if (!geojsonLayer) return;

    geojsonLayer.resetStyle();

    const selectedIds = new Set(
        selectedParcelIds
            .map(id => String(id).trim().toUpperCase())
            .filter(Boolean)
    );
    if (selectedIds.size === 0) return;

    const bounds = L.latLngBounds([]);
    geojsonLayer.eachLayer(layer => {
        const properties = layer.feature && layer.feature.properties;
        const parcelId = String(
            properties && (properties.id || properties.parcel_code) || ''
        ).trim().toUpperCase();
        if (!selectedIds.has(parcelId)) return;

        layer.setStyle({
            color: '#b91c1c',
            weight: 5,
            fillColor: '#facc15',
            fillOpacity: 0.75
        });
        layer.bringToFront();
        bounds.extend(layer.getBounds());
    });

    if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 17 });
    }
}

// --- 3b. NẠP ĐỐI TƯỢNG ĐIỂM (GIẾNG, NHÀ KHO) TỪ BACKEND ---
let objectsLayer = null;

const OBJECT_ICONS = {
    gieng: {
        color: '#06b6d4',
        emoji: '💧',
        label: 'Giếng tưới',
    },
    nha_kho: {
        color: '#d97706',
        emoji: '🏭',
        label: 'Nhà kho',
    },
};

function getObjectIcon(objectType) {
    const cfg = OBJECT_ICONS[objectType] || OBJECT_ICONS.nha_kho;
    return L.divIcon({
        className: 'custom-object-marker',
        html: `<div style="
            background:${cfg.color};
            color:#fff;
            border-radius:50%;
            width:28px;
            height:28px;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:18px;
            border:2px solid #fff;
            box-shadow:0 2px 4px rgba(0,0,0,0.3);
        ">${cfg.emoji}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14],
    });
}

async function loadObjectsToMap() {
    try {
        const response = await apiFetch('/api/objects/geojson');
        if (!response.ok) {
            const detail = await response.json().catch(() => ({}));
            console.error("Lỗi tải đối tượng bản đồ:", response.status, detail.detail || detail);
            alert("Không thể tải dữ liệu giếng và nhà kho (mã lỗi " + response.status + "). Vui lòng đăng nhập lại và thử lại.");
            return;
        }

        const geojsonData = await response.json();
        console.log("Đã tải", (geojsonData.features || []).length, "đối tượng bản đồ từ /api/objects/geojson");
        if (objectsLayer) map.removeLayer(objectsLayer);

        objectsLayer = L.geoJSON(geojsonData, {
            pointToLayer: function(feature, latlng) {
                const objectType = feature.properties ? feature.properties.loai : null;
                return L.marker(latlng, { icon: getObjectIcon(objectType) });
            },
            onEachFeature: function(feature, layer) {
                if (feature.properties) {
                    const props = feature.properties;
                    const coords = feature.geometry ? feature.geometry.coordinates : null;
                    const objectType = props.loai || '';
                    const cfg = OBJECT_ICONS[objectType] || OBJECT_ICONS.nha_kho;
                    let popupContent = `<div style="font-size: 13px;"><b>${cfg.label.toUpperCase()}</b><hr style="margin: 4px 0;">`;
                    popupContent += `<b>Tên:</b> ${props.ten || props.id}<br>`;
                    if (props.mo_ta) {
                        popupContent += `<b>Mô tả:</b> ${props.mo_ta}<br>`;
                    }
                    if (coords) {
                        popupContent += `<b>Vĩ độ:</b> ${coords[1].toFixed(6)}<br>`;
                        popupContent += `<b>Kinh độ:</b> ${coords[0].toFixed(6)}<br>`;
                    }
                    popupContent += `</div>`;
                    layer.bindPopup(popupContent);
                }
            }
        }).addTo(map);
    } catch (error) {
        console.error("Lỗi nạp đối tượng bản đồ:", error);
    }
}

// --- 4. QUẢN LÝ CHAT & LỊCH SỬ ---
let selectedBase64Image = null;
let currentSessionId = null;
const MAX_CHAT_IMAGE_BYTES = 5 * 1024 * 1024;

function handleImageSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
        alert('Vui lòng chọn tệp hình ảnh hợp lệ.');
        event.target.value = '';
        return;
    }
    if (file.size > MAX_CHAT_IMAGE_BYTES) {
        alert('Ảnh không được vượt quá 5 MB.');
        event.target.value = '';
        return;
    }

    const reader = new FileReader();
    reader.onload = function(e) {
        selectedBase64Image = e.target.result;
        document.getElementById('imagePreview').src = selectedBase64Image;
        document.getElementById('imagePreviewContainer').style.display = 'flex';
    };
    reader.readAsDataURL(file);
}

function removeSelectedImage() {
    selectedBase64Image = null;
    const imgInput = document.getElementById('imageInput');
    if (imgInput) imgInput.value = '';
    const previewContainer = document.getElementById('imagePreviewContainer');
    if (previewContainer) previewContainer.style.display = 'none';
}

// Tự động nạp thông tin khi load trang
window.onload = function() {
    // Hiển thị tên người dùng đăng nhập
    const userDisplayEl = document.getElementById('displayUsername');
    if (userDisplayEl && currentUser) {
        userDisplayEl.innerText = currentUser.full_name || currentUser.username;
    }

    // Hiển thị nút trang Admin nếu người dùng có quyền Admin
    const adminBtnEl = document.getElementById('btnAdminPage');
    if (adminBtnEl && currentUser && currentUser.role === 'admin') {
        adminBtnEl.style.display = 'inline-flex';
    }

    loadGeoJSONToMap();
    loadObjectsToMap();
    renderHistorySidebar();
    startNewChat();
};

// Hàm xử lý Đăng xuất
function handleLogout() {
    if (confirm("Bạn có chắc chắn muốn đăng xuất khỏi hệ thống?")) {
        localStorage.removeItem('user');
        localStorage.removeItem('auth_token');
        window.location.href = '/login';
    }
}

function startNewChat() {
    currentSessionId = Date.now().toString();
    const chatBox = document.getElementById('chatMessages');
    if (!chatBox) return;
    chatBox.innerHTML = `
        <div class="message bot-message">Xin chào! Tôi có thể giúp bạn tra cứu thửa đất, thời tiết, giá nông sản hoặc phân tích ảnh cây trồng.</div>
    `;
    removeSelectedImage();
    renderHistorySidebar();
}

function getSessions() {
    return JSON.parse(localStorage.getItem('chat_sessions') || '{}');
}

function saveMessageToSession(role, text, imgBase64 = null) {
    let sessions = getSessions();
    if (!sessions[currentSessionId]) {
        sessions[currentSessionId] = {
            title: text.substring(0, 22) + (text.length > 22 ? "..." : ""),
            messages: []
        };
    }
    sessions[currentSessionId].messages.push({ role, text, imgBase64 });
    localStorage.setItem('chat_sessions', JSON.stringify(sessions));
    renderHistorySidebar();
}

function renderHistorySidebar() {
    const historyListEl = document.getElementById('history-list');
    if (!historyListEl) return;
    
    const sessions = getSessions();
    historyListEl.innerHTML = '';

    Object.keys(sessions).reverse().forEach(id => {
        const item = document.createElement('div');
        item.className = `history-item ${id === currentSessionId ? 'active' : ''}`;
        item.innerText = sessions[id].title || "Cuộc trò chuyện mới";
        item.onclick = () => loadSession(id);
        historyListEl.appendChild(item);
    });
}

function loadSession(sessionId) {
    currentSessionId = sessionId;
    const sessions = getSessions();
    const session = sessions[sessionId];
    if (!session) return;

    const chatBox = document.getElementById('chatMessages');
    if (!chatBox) return;
    chatBox.innerHTML = '';
    session.messages.forEach(msg => appendMessageUI(msg.role, msg.text, msg.imgBase64));
    renderHistorySidebar();
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

// Gửi tin nhắn và ảnh đính kèm lên API chat.
async function sendMessage() {
    const inputEl = document.getElementById('chatInput');
    if (!inputEl) return;
    const text = inputEl.value.trim();
    if (!text && !selectedBase64Image) return;

    const currentImg = selectedBase64Image;
    inputEl.value = '';
    removeSelectedImage();

    appendMessageUI('user', text, currentImg);
    saveMessageToSession('user', text || "Đã gửi ảnh", currentImg);

    const loadingDiv = appendMessageUI('bot', 'Đang suy nghĩ...');

    try {
        const response = await apiFetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: text || "Phân tích ảnh này giúp tôi.",
                image_base64: currentImg
            })
        });

        const data = await response.json();
        loadingDiv.innerText = data.reply;
        saveMessageToSession('bot', data.reply);
        highlightParcels(data.parcel_ids);
    } catch (error) {
        loadingDiv.innerText = "Lỗi kết nối máy chủ Backend.";
        saveMessageToSession('bot', "Lỗi kết nối máy chủ Backend.");
    }
}

function appendMessageUI(role, text, imgBase64 = null) {
    const chatBox = document.getElementById('chatMessages');
    if (!chatBox) return null;
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}-message`;

    if (imgBase64) {
        const img = document.createElement('img');
        img.src = imgBase64;
        img.className = 'chat-img-attached';
        msgDiv.appendChild(img);
    }

    const textNode = document.createElement('span');
    textNode.innerText = text;
    msgDiv.appendChild(textNode);

    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    return textNode;
}



// --- 4. MARKER CLUSTERING & DRAW CONTROL ---
let markerClusterLayer = null;
let gpsMarker = null;
let hasUserNavigatedMap = false;
let isDrawMode = false;
let drawPoints = [];
let drawPreviewLine = null;
let drawVertexMarkers = [];
let originalDoubleClickZoom = true;
let pendingParcelGeometry = null;
let pendingParcelLayer = null;
let editingParcelId = null;

function initMarkerCluster() {
    if (markerClusterLayer) return;
    markerClusterLayer = typeof L.markerClusterGroup === 'function'
        ? L.markerClusterGroup({
            showCoverageOnHover: true,
            zoomToBoundsOnClick: true,
            spiderfyOnMaxZoom: true,
            removeOutsideVisibleBounds: true,
            maxClusterRadius: 50,
        })
        : L.layerGroup();
    map.addLayer(markerClusterLayer);
}

function clearMapLayers() {
    if (geojsonLayer) {
        map.removeLayer(geojsonLayer);
        geojsonLayer = null;
    }
    if (markerClusterLayer) {
        map.removeLayer(markerClusterLayer);
        markerClusterLayer = null;
    }
    if (gpsMarker) {
        map.removeLayer(gpsMarker);
        gpsMarker = null;
    }
}


async function loadGeoJSONToMap() {
    try {
        clearMapLayers();
        initMarkerCluster();
        const response = await apiFetch('/api/parcels/geojson');
        if (!response.ok) return;
        const geojsonData = await response.json();
        const parcelFeatures = geojsonData.features || [];
        const markers = [];
        parcelFeatures.forEach(feature => {
            if (!feature.geometry || !feature.properties) return;
            const coords = feature.geometry.coordinates;
            if (!coords || !coords[0]) return;
            const ring = coords[0];
            let latSum = 0, lonSum = 0, count = 0;
            ring.forEach(c => {
                lonSum += c[0];
                latSum += c[1];
                count++;
            });
            const centerLat = latSum / count;
            const centerLon = lonSum / count;
            const props = feature.properties;
            const popupContent = '<div style="font-size: 13px; min-width: 200px;">' +
                '<b>THUA DAT</b><hr style="margin: 4px 0;">' +
                '<b>Ma:</b> ' + (props.id || props.parcel_code || '') + '<br>' +
                '<b>Ten:</b> ' + (props.ten || props.name || '') + '<br>' +
                '<b>Cay trong:</b> ' + (props.cay_trong || props.crop_type || '') + '<br>' +
                '<b>Dien tich:</b> ' + (props.dien_tich || props.area_sqm || '') + ' m2<br>' +
                (props.user_full_name ? '<b>Chu so huu:</b> ' + props.user_full_name + ' (' + props.user_username + ')<br>' : '') +
                (props.ghi_chu || props.notes ? '<b>Ghi chu:</b> ' + (props.ghi_chu || props.notes) + '<br>' : '') +
                '</div>';
            const marker = L.marker([centerLat, centerLon]);
            marker.bindPopup(popupContent);
            markers.push(marker);
        });
        markers.forEach(m => markerClusterLayer.addLayer(m));
        geojsonLayer = L.geoJSON(geojsonData, {
            style: function(feature) {
                const cropType = feature.properties ?
                    (feature.properties.loai_nong_san || feature.properties.crop_type || feature.properties.loai_dat) : null;
                const fillColor = getColorByCrop(cropType);
                return {
                    color: fillColor,
                    weight: 2,
                    fillColor: fillColor,
                    fillOpacity: 0.35
                };
            },
            onEachFeature: function(feature, layer) {
                if (feature.properties) {
                    const props = feature.properties;
                    const popupContent = '<div style="font-size: 13px; min-width: 200px;">' +
                        '<b>THUA DAT</b><hr style="margin: 4px 0;">' +
                        '<b>Ma:</b> ' + (props.id || props.parcel_code || '') + '<br>' +
                        '<b>Ten:</b> ' + (props.ten || props.name || '') + '<br>' +
                        '<b>Cay trong:</b> ' + (props.cay_trong || props.crop_type || '') + '<br>' +
                        '<b>Dien tich:</b> ' + (props.dien_tich || props.area_sqm || '') + ' m2<br>' +
                        (props.user_full_name ? '<b>Chu so huu:</b> ' + props.user_full_name + ' (' + props.user_username + ')<br>' : '') +
                        (props.ghi_chu || props.notes ? '<b>Ghi chu:</b> ' + (props.ghi_chu || props.notes) + '<br>' : '') +
                        '</div>';
                    layer.bindPopup(popupContent);
                }
            }
        }).addTo(map);
        if (!hasUserNavigatedMap && geojsonLayer.getBounds().isValid()) {
            map.fitBounds(geojsonLayer.getBounds());
        }
        if (selectedParcelIds.length > 0) {
            highlightParcels(selectedParcelIds);
        }
    } catch (error) {
        console.error("Loi nap ban do:", error);
    }
}


async function loadAdminUsers() {
    const select = document.getElementById('adminUserSelect');
    if (!select) return;
    select.innerHTML = '<option value="">-- Chon user de xem thua --</option>';
    try {
        const response = await apiFetch('/api/admin/users-with-location');
        if (!response.ok) return;
        const users = await response.json();
        users.forEach(u => {
            const option = document.createElement('option');
            option.value = u.id;
            let text = (u.full_name || u.username) + ' (' + u.username + ')';
            if (u.parcel_count > 0) text += ' - ' + u.parcel_count + ' thua';
            option.textContent = text;
            select.appendChild(option);
        });
    } catch (error) {
        console.error("Loi tai danh sach user:", error);
    }
}

async function adminFilterParcelsByUser() {
    const select = document.getElementById('adminUserSelect');
    if (!select) return;
    const userId = select.value;
    if (userId) {
        window.location.href = '/api/parcels?user_id=' + userId;
    } else {
        window.location.href = '/api/parcels/geojson';
    }
}


async function goToMyLocation() {
    if (!window.isSecureContext || !navigator.geolocation) {
        const message = "Trình duyệt chỉ cho phép lấy GPS trên HTTPS hoặc localhost. Hãy mở ứng dụng bằng địa chỉ bảo mật.";
        alert(message);
        throw new Error(message);
    }

    try {
        const position = await new Promise((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0,
            });
        });

        const { latitude, longitude } = position.coords;

        hasUserNavigatedMap = true;
        if (gpsMarker) map.removeLayer(gpsMarker);
        gpsMarker = L.marker([latitude, longitude], {
            icon: L.divIcon({
                className: 'gps-marker',
                html: '<i class="fa-solid fa-location-dot" style="color: #1e90ff; font-size: 24px; text-shadow: 0 0 3px rgba(0,0,0,0.5);"></i>',
                iconSize: [30, 30],
                iconAnchor: [15, 15],
            })
        }).addTo(map);

        map.invalidateSize();
        map.flyTo([latitude, longitude], 17, { animate: true, duration: 0.8 });
        gpsMarker.bindPopup("<b>Vị trí hiện tại của bạn</b>").openPopup();

        try {
            const response = await apiFetch('/api/user/location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ latitude, longitude }),
            });
            if (!response.ok) {
                console.error("Không thể lưu vị trí GPS lên máy chủ:", response.status);
            }
        } catch (error) {
            console.error("Không thể lưu vị trí GPS lên máy chủ:", error);
        }

        return { latitude, longitude };
    } catch (error) {
        console.error("Lỗi lấy vị trí GPS:", error);
        const errorMessage = error.code === 1
            ? "Bạn chưa cấp quyền vị trí cho trang web. Hãy bật quyền Vị trí trong cài đặt trình duyệt."
            : error.code === 2
                ? "Không xác định được vị trí hiện tại. Hãy bật GPS hoặc kiểm tra kết nối."
                : error.code === 3
                    ? "Lấy vị trí quá thời gian chờ. Hãy thử lại ở nơi có tín hiệu GPS tốt hơn."
                    : "Không thể lấy vị trí GPS. Vui lòng kiểm tra quyền truy cập vị trí.";
        alert(errorMessage);
        throw error;
    }
}

function toggleDrawMode() {
    const button = document.getElementById('parcelDrawToggle');

    if (isDrawMode) {
        if (drawPoints.length >= 3) {
            finishParcelDrawing();
        } else {
            cancelParcelDrawing();
            alert("Đã hủy vẽ. Hãy chọn tối thiểu 3 điểm trên bản đồ để tạo thửa.");
        }
        return;
    }

    isDrawMode = true;
    hasUserNavigatedMap = true;
    drawPoints = [];
    drawVertexMarkers = [];
    if (pendingParcelLayer) map.removeLayer(pendingParcelLayer);
    pendingParcelLayer = null;
    pendingParcelGeometry = null;
    drawPreviewLine = L.polyline([], {
        color: '#1b5e20',
        weight: 3,
        dashArray: '6 6',
    }).addTo(map);
    originalDoubleClickZoom = map.doubleClickZoom.enabled();
    map.doubleClickZoom.disable();
    map.on('click', addParcelDrawingPoint);

    if (button) {
        button.classList.add('is-active');
        button.innerHTML = '<i class="fa-solid fa-draw-polygon" aria-hidden="true"></i><span>Hoàn tất vẽ (0/3)</span>';
        button.setAttribute('aria-pressed', 'true');
        button.title = "Chọn ít nhất 3 điểm trên bản đồ rồi bấm để hoàn tất; nhấn Esc để hủy.";
    }

    document.addEventListener('keydown', handleParcelDrawingKey);
    const status = document.getElementById('drawStatus');
    if (status) status.textContent = 'Chọn ít nhất 3 điểm trên bản đồ. Nhấn Enter hoặc bấm “Hoàn tất vẽ” để kết thúc; Esc để hủy.';
}

function addParcelDrawingPoint(event) {
    drawPoints.push(event.latlng);
    drawVertexMarkers.push(L.circleMarker(event.latlng, {
        radius: 5,
        color: '#fff',
        weight: 2,
        fillColor: '#1b5e20',
        fillOpacity: 1,
    }).addTo(map));
    drawPreviewLine.setLatLngs(drawPoints);

    const button = document.getElementById('parcelDrawToggle');
    if (button) {
        button.innerHTML = `<i class="fa-solid fa-draw-polygon" aria-hidden="true"></i><span>Hoàn tất vẽ (${drawPoints.length}/3)</span>`;
    }
    const status = document.getElementById('drawStatus');
    if (status) status.textContent = `${drawPoints.length} điểm đã chọn. Chọn thêm điểm rồi bấm “Hoàn tất vẽ”; nhấn Esc để hủy.`;
}

function handleParcelDrawingKey(event) {
    if (event.key === 'Escape') {
        cancelParcelDrawing();
    } else if (event.key === 'Enter' && drawPoints.length >= 3) {
        finishParcelDrawing();
    }
}

function stopParcelDrawing() {
    map.off('click', addParcelDrawingPoint);
    document.removeEventListener('keydown', handleParcelDrawingKey);
    if (drawPreviewLine) map.removeLayer(drawPreviewLine);
    drawPreviewLine = null;
    drawVertexMarkers.forEach(marker => map.removeLayer(marker));
    drawVertexMarkers = [];
    map.doubleClickZoom[originalDoubleClickZoom ? 'enable' : 'disable']();
    isDrawMode = false;

    const button = document.getElementById('parcelDrawToggle');
    if (button) {
        button.classList.remove('is-active');
        button.innerHTML = '<i class="fa-solid fa-draw-polygon" aria-hidden="true"></i><span>Thêm / vẽ thửa</span>';
        button.setAttribute('aria-pressed', 'false');
        button.title = '';
    }
    const status = document.getElementById('drawStatus');
    if (status) status.textContent = '';
}

function finishParcelDrawing() {
    if (drawPoints.length < 3) {
        alert("Cần chọn ít nhất 3 điểm trên bản đồ trước khi hoàn tất.");
        return;
    }

    const layer = L.polygon(drawPoints, {
        color: '#1b5e20',
        weight: 3,
        fillColor: '#22c55e',
        fillOpacity: 0.2,
    });
    pendingParcelGeometry = layer.toGeoJSON().geometry;
    if (pendingParcelLayer) map.removeLayer(pendingParcelLayer);
    pendingParcelLayer = layer.addTo(map);
    stopParcelDrawing();

    const modal = document.getElementById('modalOverlay');
    if (modal) modal.classList.add('active');
    if (!editingParcelId) document.getElementById('parcelCode').focus();
    else {
        document.getElementById('parcelGeometryHint').textContent =
            'Thông tin sẽ được lưu ngay. Ranh giới chỉ thay đổi nếu bạn chọn “Vẽ lại ranh giới”.';
    }
}

function cancelParcelDrawing() {
    stopParcelDrawing();
    drawPoints = [];
    if (editingParcelId) {
        document.getElementById('modalOverlay').classList.add('active');
    }
}

async function onParcelFormSubmit(event) {
    event.preventDefault();
    if (!editingParcelId && !pendingParcelGeometry) {
        alert("Hãy vẽ ranh giới thửa đất trên bản đồ trước khi lưu.");
        return;
    }

    const submitButton = document.querySelector('#parcelForm button[type="submit"]');
    if (submitButton) submitButton.disabled = true;
    const payload = {
        parcel_code: document.getElementById('parcelCode').value.trim(),
        name: document.getElementById('parcelName').value.trim(),
        crop_type: document.getElementById('cropType').value,
        notes: document.getElementById('parcelNotes').value.trim() || null,
    };
    if (pendingParcelGeometry) payload.geometry = pendingParcelGeometry;
    const isEditing = editingParcelId !== null;

    try {
        const response = await apiFetch(
            editingParcelId ? `/api/parcels/${editingParcelId}` : '/api/parcels',
            {
            method: editingParcelId ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            }
        );
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || `Không thể lưu thửa (mã lỗi ${response.status}).`);
        }
        closeParcelModal();
        await loadGeoJSONToMap();
        alert(isEditing ? "Đã cập nhật thửa đất vào cơ sở dữ liệu." : "Đã tạo thửa đất thành công!");
    } catch (error) {
        console.error("Lỗi lưu thửa:", error);
        alert(error.message || "Lỗi kết nối máy chủ.");
    } finally {
        if (submitButton) submitButton.disabled = false;
    }
}


// ============== CURRENT LOCATION ==============
document.addEventListener('DOMContentLoaded', function() {
    const positionSpot = document.getElementById('positionSpot');
    const positionText = document.getElementById('positionText');

    if (positionSpot) {
        positionSpot.addEventListener('click', async function() {
            positionSpot.disabled = true;
            positionText.textContent = 'Đang lấy vị trí...';
            try {
                const location = await goToMyLocation();
                positionText.textContent = `${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)}`;
                positionSpot.querySelector('.pin-icon').style.color = '#10b981';
            } catch (error) {
                positionText.textContent = 'Không lấy được vị trí';
            } finally {
                positionSpot.disabled = false;
            }
        });

        // Initialize with saved location from backend
        async function loadSavedLocation() {
            try {
                const response = await apiFetch('/api/user/location');
                if (response.ok) {
                    const data = await response.json();
                    const lat = data.latitude;
                    const lng = data.longitude;
                    if (Number.isFinite(lat) && Number.isFinite(lng)) {
                        positionText.textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
                        positionSpot.querySelector('.pin-icon').style.color = '#10b981';
                    }
                }
            } catch (e) {
                console.error('Failed to load saved location:', e);
            }
        }
        loadSavedLocation();
    }
});


// ============== THÊM THỬA FUNCTIONS ==============
function addNewParcel() {
    if (!isDrawMode) {
        editingParcelId = null;
        pendingParcelGeometry = null;
        if (pendingParcelLayer) {
            map.removeLayer(pendingParcelLayer);
            pendingParcelLayer = null;
        }
        document.getElementById('parcelForm').reset();
        document.getElementById('parcelModalTitle').textContent = "Thông tin thửa mới";
        document.getElementById('parcelGeometryHint').textContent =
            'Hoàn tất vẽ ranh giới trên bản đồ trước khi nhập thông tin thửa.';
        document.getElementById('redrawParcelButton').hidden = true;
    }
    toggleDrawMode();
}

function editParcel(feature) {
    const properties = feature && feature.properties;
    const databaseId = Number(properties && properties.db_id);
    if (!Number.isInteger(databaseId) || databaseId <= 0) {
        alert("Không xác định được thửa để sửa. Hãy tải lại bản đồ.");
        return;
    }

    editingParcelId = databaseId;
    pendingParcelGeometry = null;
    if (pendingParcelLayer) {
        map.removeLayer(pendingParcelLayer);
        pendingParcelLayer = null;
    }
    document.getElementById('parcelCode').value = properties.id || properties.parcel_code || '';
    document.getElementById('parcelName').value = properties.ten || properties.name || '';
    const cropType = properties.cay_trong || properties.crop_type || '';
    const cropSelect = document.getElementById('cropType');
    cropSelect.value = cropType;
    if (cropType && cropSelect.value !== cropType) {
        const customOption = document.createElement('option');
        customOption.value = cropType;
        customOption.textContent = cropType;
        cropSelect.appendChild(customOption);
        cropSelect.value = cropType;
    }
    document.getElementById('parcelNotes').value = properties.ghi_chu || properties.notes || '';
    document.getElementById('parcelModalTitle').textContent = `Sửa thửa ${properties.id || ''}`;
    document.getElementById('parcelGeometryHint').textContent =
        'Bạn có thể sửa thông tin rồi lưu ngay, hoặc chọn “Vẽ lại ranh giới” để thay đổi hình dạng thửa.';
    document.getElementById('redrawParcelButton').hidden = false;
    document.getElementById('modalOverlay').classList.add('active');
}

function redrawEditedParcel() {
    document.getElementById('modalOverlay').classList.remove('active');
    toggleDrawMode();
}

function closeParcelModal() {
    const modal = document.getElementById('modalOverlay');
    if (modal) {
        modal.classList.remove('active');
    }
    if (pendingParcelLayer) {
        map.removeLayer(pendingParcelLayer);
        pendingParcelLayer = null;
    }
    pendingParcelGeometry = null;
    editingParcelId = null;
    const redrawButton = document.getElementById('redrawParcelButton');
    if (redrawButton) redrawButton.hidden = true;
}

document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('parcelForm');
    if (form) form.addEventListener('submit', onParcelFormSubmit);
});

// ============== XOA TAI KHOAN (ADMIN ONLY) ==============
function handleDeleteAccount() {
    if (!confirm('Ban chac chan muon xoa tai khoan nay? Hanh dong khong the hoan tac!')) {
        return;
    }
    if (currentUser && currentUser.id) {
        fetch('/api/admin/delete-user/' + currentUser.id, {
            method: 'DELETE',
            headers: {
                'Authorization': 'Bearer ' + localStorage.getItem('auth_token'),
                'Content-Type': 'application/json'
            }
        }).then(async response => {
            if (response.ok) {
                alert('Da xoa tai khoan thanh cong!');
                localStorage.removeItem('user');
                localStorage.removeItem('auth_token');
                window.location.href = '/login';
            } else {
                const error = await response.json();
                alert('Loi: ' + (error.detail || 'Khong the xoa tai khoan'));
            }
        }).catch(err => {
            console.error('Loi xoa tai khoan:', err);
            alert('Loi ket noi may chu!');
        });
    }
}