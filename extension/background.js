/**
 * Service worker (mục 5.1-5.3): nơi DUY NHẤT gọi API qua tunnel và giữ
 * token. Không nhận lệnh giao dịch từ content script/website — chỉ xử lý
 * message đã định nghĩa, và chỉ tin sender là chính extension này
 * (sender.id === chrome.runtime.id) và không phải content script
 * (!sender.tab). Không mở externally_connectable cho Yahoo hay bất kỳ ai.
 */

const API_BASE_URL = "http://127.0.0.1:18000";

const TRUSTED_MESSAGE_TYPES = new Set([
  "PAIR",
  "GET_STATE",
  "LOGOUT",
  "FETCH_PREVIEW",
  "SUBMIT_COMMAND",
  "GET_COMMAND_STATUS",
  "FIND_COMMAND_BY_INTENT",
  "CANCEL_COMMAND",
  "GET_ACCOUNT_STATUS",
]);

function isTrustedSender(sender) {
  // sender.tab tồn tại nghĩa là message tới từ content script/trang web,
  // không phải từ popup/trang extension đã xác nhận (mục 5.1).
  return sender.id === chrome.runtime.id && !sender.tab;
}

async function getSession() {
  const state = await chrome.storage.session.get(["deviceToken", "ownerId", "accountId", "scope"]);
  return state;
}

async function setSession(partial) {
  await chrome.storage.session.set(partial);
}

async function clearSession() {
  await chrome.storage.session.remove(["deviceToken", "ownerId", "accountId", "scope"]);
}

async function apiFetch(path, { method = "GET", body, headers = {}, requireAuth = true } = {}) {
  const finalHeaders = { "Content-Type": "application/json", ...headers };

  if (requireAuth) {
    const { deviceToken } = await getSession();
    if (!deviceToken) {
      const err = new Error("Chưa ghép cặp thiết bị");
      err.code = "NOT_PAIRED";
      throw err;
    }
    finalHeaders["Authorization"] = `Bearer ${deviceToken}`;
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (networkError) {
    const err = new Error("Không kết nối được API qua tunnel — kiểm tra SSH tunnel/VPS");
    err.code = "NETWORK_ERROR";
    err.cause = networkError;
    throw err;
  }

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const err = new Error((data && data.detail) || `API lỗi ${response.status}`);
    err.status = response.status;
    err.code = (data && data.code) || "UNKNOWN_ERROR";
    throw err;
  }
  return data;
}

const handlers = {
  async PAIR({ pairingCode, deviceLabel }) {
    const data = await apiFetch("/api/pairing/exchange", {
      method: "POST",
      requireAuth: false,
      body: { pairing_code: pairingCode, device_label: deviceLabel || "" },
    });
    await setSession({
      deviceToken: data.device_token,
      ownerId: data.owner_id,
      accountId: data.account_id,
      scope: data.scope,
    });
    return { ownerId: data.owner_id, accountId: data.account_id, scope: data.scope };
  },

  async GET_STATE() {
    const { deviceToken, ownerId, accountId, scope } = await getSession();
    return { paired: Boolean(deviceToken), ownerId: ownerId || null, accountId: accountId || null, scope: scope || [] };
  },

  async LOGOUT() {
    await clearSession();
    return { ok: true };
  },

  async FETCH_PREVIEW({ accountId, auctionId, action }) {
    return apiFetch("/api/previews", {
      method: "POST",
      body: { account_id: accountId, auction_id: auctionId, action },
    });
  },

  async SUBMIT_COMMAND({ idempotencyKey, payload }) {
    return apiFetch("/api/commands", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload,
    });
  },

  async GET_COMMAND_STATUS({ commandId }) {
    return apiFetch(`/api/commands/${encodeURIComponent(commandId)}`);
  },

  async FIND_COMMAND_BY_INTENT({ intentId }) {
    return apiFetch(`/api/commands?intent_id=${encodeURIComponent(intentId)}`);
  },

  async CANCEL_COMMAND({ commandId }) {
    return apiFetch(`/api/commands/${encodeURIComponent(commandId)}/cancel`, { method: "POST" });
  },

  async GET_ACCOUNT_STATUS({ accountId }) {
    return apiFetch(`/api/accounts/${encodeURIComponent(accountId)}/status`);
  },
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !TRUSTED_MESSAGE_TYPES.has(message.type) || !isTrustedSender(sender)) {
    sendResponse({ ok: false, error: { code: "REJECTED", message: "Message không hợp lệ hoặc không đáng tin" } });
    return false;
  }

  handlers[message.type](message.payload || {})
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) =>
      sendResponse({
        ok: false,
        error: { code: error.code || "ERROR", status: error.status, message: error.message },
      })
    );
  return true; // giữ kênh mở cho response bất đồng bộ
});
