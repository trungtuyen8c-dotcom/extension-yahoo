/**
 * Content script (mục 5.1, 15): CHỈ trích ID listing gợi ý từ trang đang
 * mở. Không đọc/gửi cookie, không tự mở giao dịch, không lắng nghe
 * `window.postMessage` từ trang. File này không được khai báo tĩnh trong
 * manifest — popup.js chỉ inject nó theo yêu cầu (activeTab) khi người
 * dùng chủ động mở popup, và chỉ đọc giá trị trả về của IIFE bên dưới.
 *
 * CHƯA XÁC MINH với URL/DOM thật của auctions.yahoo.co.jp (mục 17: cần một
 * URL listing mẫu). Nếu không khớp mẫu nào, trả `auctionId: null` — popup
 * luôn cho nhập tay, và VPS luôn tự tra cứu lại (mục 4 bước 4: "dữ liệu DOM
 * local chỉ là gợi ý").
 */
(function detectListingId() {
  const CANDIDATE_PATTERNS = [/\/auction\/([a-zA-Z0-9]+)(?:[/?#]|$)/];

  let auctionId = null;
  for (const pattern of CANDIDATE_PATTERNS) {
    const match = location.href.match(pattern);
    if (match) {
      auctionId = match[1];
      break;
    }
  }

  return { auctionId, pageUrl: location.href };
})();
