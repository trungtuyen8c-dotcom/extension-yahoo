/**
 * Popup/trang extension (mục 4, 5): NƠI DUY NHẤT người dùng xác nhận lệnh
 * giao dịch. Không có cơ chế nào ở đây tự gửi lệnh mà thiếu bấm nút xác
 * nhận của người dùng trên chính trang này.
 */

const TRACKED_STORAGE_KEY = "trackedCommands";
const POLL_INTERVAL_MS = 2000;

let currentPreview = null;
let activePollTimers = new Map();

function sendMessage(type, payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, payload }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response || !response.ok) {
        const err = new Error((response && response.error && response.error.message) || "Lỗi không rõ");
        err.code = response && response.error && response.error.code;
        reject(err);
        return;
      }
      resolve(response.result);
    });
  });
}

async function getTracked() {
  const state = await chrome.storage.local.get([TRACKED_STORAGE_KEY]);
  return state[TRACKED_STORAGE_KEY] || {};
}

async function saveTrackedEntry(entry) {
  const tracked = await getTracked();
  tracked[entry.intentId] = entry;
  await chrome.storage.local.set({ [TRACKED_STORAGE_KEY]: tracked });
}

function $(id) {
  return document.getElementById(id);
}

function setBadge(text, kind) {
  const el = $("connectionBadge");
  el.textContent = text;
  el.className = `badge ${kind || ""}`;
}

async function detectAuctionIdFromActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return null;
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"],
    });
    return result || null;
  } catch (_err) {
    // Trang không cho inject (chrome://, store nội bộ...) — bỏ qua, người
    // dùng nhập tay ID listing.
    return null;
  }
}

function currentAmounts() {
  const action = $("actionSelect").value;
  const maxTotal = Number($("maxTotalInput").value || 0);
  if (action === "PLACE_BID") {
    return { action, maxBid: Number($("maxBidInput").value || 0), maxTotal };
  }
  return { action, maxItemPrice: Number($("maxItemPriceInput").value || 0), maxTotal };
}

function updateConfirmButtonLabel() {
  const dryRun = $("dryRunCheckbox").checked;
  const { action, maxBid, maxTotal } = currentAmounts();
  const prefix = dryRun ? "[DRY-RUN] " : "";
  let label;
  if (action === "PLACE_BID") {
    label = `${prefix}Đặt giá tối đa ${maxBid || "?"} JPY qua VPS`;
  } else {
    label = `${prefix}Mua và thanh toán tối đa ${maxTotal || "?"} JPY qua VPS`;
  }
  $("confirmButton").textContent = label;
}

function renderPreview(preview) {
  currentPreview = preview;
  const snap = preview.listing_snapshot || {};
  $("previewTitle").textContent = snap.title || "(không có tiêu đề)";
  $("previewSeller").textContent = snap.seller || "?";
  $("previewListingType").textContent = snap.listing_type || "?";
  $("previewPrice").textContent = snap.current_price_jpy != null ? `${snap.current_price_jpy} JPY` : "?";
  $("previewFees").textContent = snap.fees_fully_known
    ? `${snap.known_fees_jpy || 0} JPY (đã xác định đủ)`
    : "CHƯA XÁC ĐỊNH ĐỦ — lệnh sẽ bị chặn nếu unknown_cost_policy=BLOCK";
  $("previewFetchedAt").textContent = preview.fetched_at;
  $("previewExpiresAt").textContent = preview.expires_at;
  $("previewBox").hidden = false;

  const isBid = preview.action === "PLACE_BID";
  $("bidFields").hidden = !isBid;
  $("buyNowFields").hidden = isBid;
  updateConfirmButtonLabel();
}

async function refreshTrackedList() {
  const tracked = await getTracked();
  const listEl = $("trackedList");
  listEl.innerHTML = "";

  const entries = Object.values(tracked).sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
  for (const entry of entries.slice(0, 10)) {
    const li = document.createElement("li");
    li.textContent = `${entry.action} ${entry.auctionId} — ${entry.lastStatus || "?"} `;

    if (entry.commandId && !isTerminalStatus(entry.lastStatus)) {
      const cancelBtn = document.createElement("button");
      cancelBtn.textContent = "Hủy (chỉ khi còn QUEUED)";
      cancelBtn.style.width = "auto";
      cancelBtn.style.marginLeft = "6px";
      cancelBtn.onclick = async () => {
        try {
          const result = await sendMessage("CANCEL_COMMAND", { commandId: entry.commandId });
          entry.lastStatus = result.command_status;
          await saveTrackedEntry(entry);
          refreshTrackedList();
        } catch (err) {
          alert(`Không hủy được: ${err.message}`);
        }
      };
      li.appendChild(cancelBtn);
    }
    listEl.appendChild(li);
  }
}

function isTerminalStatus(status) {
  return ["SUCCEEDED", "DRY_RUN_SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(status);
}

function pollCommand(entry) {
  if (activePollTimers.has(entry.intentId)) return;
  const timer = setInterval(async () => {
    try {
      const status = await sendMessage("GET_COMMAND_STATUS", { commandId: entry.commandId });
      entry.lastStatus = status.command_status;
      entry.auctionStatus = status.auction_status;
      entry.paymentStatus = status.payment_status;
      await saveTrackedEntry(entry);
      refreshTrackedList();
      if (isTerminalStatus(status.command_status)) {
        clearInterval(timer);
        activePollTimers.delete(entry.intentId);
      }
    } catch (_err) {
      // Mất mạng/tunnel tạm thời — vòng lặp thử lại ở lần poll kế tiếp,
      // không tự tạo ý định mới (mục 5.3, 9).
    }
  }, POLL_INTERVAL_MS);
  activePollTimers.set(entry.intentId, timer);
}

async function resumeTrackingOnOpen() {
  const tracked = await getTracked();
  for (const entry of Object.values(tracked)) {
    if (!entry.commandId) continue;
    if (isTerminalStatus(entry.lastStatus)) continue;
    pollCommand(entry);
  }
  refreshTrackedList();
}

async function handlePair() {
  const pairingCode = $("pairingCodeInput").value.trim();
  $("pairingError").hidden = true;
  if (!pairingCode) return;
  try {
    await sendMessage("PAIR", { pairingCode });
    await showMainPanel();
  } catch (err) {
    $("pairingError").textContent = err.message;
    $("pairingError").hidden = false;
  }
}

async function handlePreview() {
  $("previewError").hidden = true;
  $("previewBox").hidden = true;
  const state = await sendMessage("GET_STATE", {});
  const auctionId = $("auctionIdInput").value.trim();
  const action = $("actionSelect").value;
  if (!auctionId) {
    $("previewError").textContent = "Nhập ID listing trước";
    $("previewError").hidden = false;
    return;
  }
  try {
    const preview = await sendMessage("FETCH_PREVIEW", { accountId: state.accountId, auctionId, action });
    renderPreview(preview);
  } catch (err) {
    $("previewError").textContent = `${err.code || "ERROR"}: ${err.message}`;
    $("previewError").hidden = false;
  }
}

async function handleConfirm() {
  $("confirmError").hidden = true;
  if (!currentPreview) return;

  const state = await sendMessage("GET_STATE", {});
  const dryRun = $("dryRunCheckbox").checked;
  const { action, maxBid, maxItemPrice, maxTotal } = currentAmounts();

  const intentId = crypto.randomUUID();
  const idempotencyKey = crypto.randomUUID();

  const payload = {
    intent_id: intentId,
    account_id: state.accountId,
    auction_id: currentPreview.auction_id,
    preview_id: currentPreview.preview_id,
    action,
    currency: "JPY",
    unknown_cost_policy: "BLOCK",
    expires_in_seconds: 120,
    dry_run: dryRun,
  };
  if (action === "PLACE_BID") {
    payload.max_bid_jpy = maxBid;
    payload.max_total_jpy = maxTotal;
  } else {
    payload.max_item_price_jpy = maxItemPrice;
    payload.max_total_jpy = maxTotal;
  }

  // Lưu ý định TRƯỚC khi gửi (mục 5.3): nếu service worker/popup bị đóng
  // giữa chừng, mở lại vẫn tra được cùng lệnh qua intent_id.
  const entry = {
    intentId,
    idempotencyKey,
    action,
    auctionId: currentPreview.auction_id,
    accountId: state.accountId,
    createdAt: Date.now(),
    lastStatus: "SENDING",
  };
  await saveTrackedEntry(entry);
  refreshTrackedList();

  try {
    const result = await sendMessage("SUBMIT_COMMAND", { idempotencyKey, payload });
    entry.commandId = result.command_id;
    entry.lastStatus = result.command_status;
    await saveTrackedEntry(entry);
    refreshTrackedList();
    pollCommand(entry);
  } catch (err) {
    entry.lastStatus = "SEND_FAILED_WILL_RETRY_SAME_KEY";
    await saveTrackedEntry(entry);
    refreshTrackedList();
    $("confirmError").textContent = `${err.code || "ERROR"}: ${err.message}. Bấm lại để thử với cùng khóa.`;
    $("confirmError").hidden = false;
  }
}

async function showPairingPanel() {
  $("pairingPanel").hidden = false;
  $("mainPanel").hidden = true;
  setBadge("Chưa ghép cặp", "error");
}

async function showMainPanel() {
  const state = await sendMessage("GET_STATE", {});
  if (!state.paired) {
    return showPairingPanel();
  }
  $("pairingPanel").hidden = true;
  $("mainPanel").hidden = false;
  setBadge(`Đã ghép cặp (${state.ownerId})`, "ok");

  const detected = await detectAuctionIdFromActiveTab();
  if (detected && detected.auctionId && !$("auctionIdInput").value) {
    $("auctionIdInput").value = detected.auctionId;
  }
}

function wireEvents() {
  $("pairButton").addEventListener("click", handlePair);
  $("previewButton").addEventListener("click", handlePreview);
  $("confirmButton").addEventListener("click", handleConfirm);
  $("actionSelect").addEventListener("change", () => {
    $("previewBox").hidden = true;
    currentPreview = null;
  });
  ["maxBidInput", "maxItemPriceInput", "maxTotalInput", "dryRunCheckbox"].forEach((id) => {
    $(id).addEventListener("input", updateConfirmButtonLabel);
    $(id).addEventListener("change", updateConfirmButtonLabel);
  });
}

async function init() {
  wireEvents();
  try {
    await showMainPanel();
  } catch (_err) {
    await showPairingPanel();
  }
  await resumeTrackingOnOpen();
}

document.addEventListener("DOMContentLoaded", init);
