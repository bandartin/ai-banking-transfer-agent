/**
 * Banking AI Transfer Agent — Chat UI JavaScript
 *
 * Handles:
 *  - Sending messages via AJAX
 *  - Rendering assistant responses (plain text, confirmation card, OTP prompt,
 *    ambiguity selection, success/error)
 *  - Updating the debug and graph-trace panels
 *  - Sample utterance buttons
 *  - Chat and demo data reset
 */

"use strict";

const CHAT_API   = "/api/chat/message";
const RESET_API  = "/api/chat/reset";
const DEMO_RESET = "/admin/reset-demo";

const msgContainer = document.getElementById("chat-messages");
const chatForm     = document.getElementById("chat-form");
const chatInput    = document.getElementById("chat-input");
const sendBtn      = document.getElementById("send-btn");
const debugPanel   = document.getElementById("debug-panel");
const tracePanel   = document.getElementById("trace-panel");

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function scrollToBottom() {
  msgContainer.scrollTop = msgContainer.scrollHeight;
}

function formatKRW(n) {
  return Number(n).toLocaleString("ko-KR") + "원";
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

// ─────────────────────────────────────────────────────────────────────────────
// Append a plain text bubble
// ─────────────────────────────────────────────────────────────────────────────

function appendBubble(role, html) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  row.innerHTML = `<div class="message-bubble ${role}-bubble">${html}</div>`;
  msgContainer.appendChild(row);
  scrollToBottom();
  return row;
}

// ─────────────────────────────────────────────────────────────────────────────
// Typing indicator
// ─────────────────────────────────────────────────────────────────────────────

let typingRow = null;

function showTyping() {
  typingRow = document.createElement("div");
  typingRow.className = "message-row assistant";
  typingRow.innerHTML = `
    <div class="message-bubble assistant-bubble">
      <div class="typing-indicator">
        <span></span><span></span><span></span>
      </div>
    </div>`;
  msgContainer.appendChild(typingRow);
  scrollToBottom();
}

function hideTyping() {
  if (typingRow) { typingRow.remove(); typingRow = null; }
}

// ─────────────────────────────────────────────────────────────────────────────
// Render confirmation card
// ─────────────────────────────────────────────────────────────────────────────

function renderConfirmationCard(responseText, data) {
  const html = `
    <div class="confirmation-card">
      <div class="fw-semibold mb-2">📋 이체 확인</div>
      <table class="table table-sm mb-2">
        <tbody>
          <tr><td class="text-muted">출금 계좌</td><td>${escapeHtml(data.source_account_name || "")} (****${(data.source_account_number||"").slice(-4)})</td></tr>
          <tr><td class="text-muted">현재 잔액</td><td><strong>${formatKRW(data.current_balance)}</strong></td></tr>
          <tr><td class="text-muted">수신자</td><td>${escapeHtml(data.recipient_alias || data.recipient_name || "")} (${escapeHtml(data.recipient_bank || "")})</td></tr>
          <tr><td class="text-muted">수신 계좌</td><td>****${(data.recipient_account||"").replace(/-/g,"").slice(-4)}</td></tr>
          <tr><td class="text-muted">이체 금액</td><td><strong class="text-dark fw-bold">${formatKRW(data.amount)}</strong></td></tr>
          <tr><td class="text-muted">수수료</td><td>${data.fee > 0 ? formatKRW(data.fee) : "없음 (동일 은행)"}</td></tr>
          <tr><td class="text-muted">이체 후 잔액</td><td>${formatKRW(data.remaining_balance)}</td></tr>
          ${data.memo ? `<tr><td class="text-muted">메모</td><td>${escapeHtml(data.memo)}</td></tr>` : ""}
        </tbody>
      </table>
      ${data.warnings && data.warnings.length ? `<div class="text-warning small mb-2">${data.warnings.map(w=>"⚠️ "+escapeHtml(w)).join("<br>")}</div>` : ""}
      <div class="confirm-actions">
        <button class="btn btn-success btn-sm confirm-yes-btn">✓ 확인</button>
        <button class="btn btn-outline-secondary btn-sm confirm-no-btn">✗ 취소</button>
      </div>
    </div>`;

  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.innerHTML = `<div class="message-bubble assistant-bubble" style="max-width:95%">${html}</div>`;
  msgContainer.appendChild(row);
  scrollToBottom();

  row.querySelector(".confirm-yes-btn").addEventListener("click", () => sendMessage("확인"));
  row.querySelector(".confirm-no-btn").addEventListener("click", () => sendMessage("취소"));
}

// ─────────────────────────────────────────────────────────────────────────────
// Render OTP prompt
// ─────────────────────────────────────────────────────────────────────────────

function renderOtpPrompt(text) {
  const html = `
    <div>
      ${escapeHtml(text)}
      <div class="mt-2 d-flex gap-2">
        <input class="form-control otp-input" id="otp-inline-input" maxlength="6"
               placeholder="000000" inputmode="numeric">
        <button class="btn btn-dark btn-sm" id="otp-submit-btn">확인</button>
      </div>
      <div class="text-muted small mt-1">데모 OTP: <strong>123456</strong></div>
    </div>`;
  const row = appendBubble("assistant", html);
  const inp = row.querySelector("#otp-inline-input");
  const btn = row.querySelector("#otp-submit-btn");
  inp.focus();
  btn.addEventListener("click", () => sendMessage(inp.value.trim()));
  inp.addEventListener("keydown", e => { if (e.key === "Enter") sendMessage(inp.value.trim()); });
}

// ─────────────────────────────────────────────────────────────────────────────
// Render ambiguity selection
// ─────────────────────────────────────────────────────────────────────────────

function renderAmbiguityCard(text, data) {
  const candidates = (data && data.candidates) || [];
  let btns = "";
  candidates.forEach(c => {
    const label = `${c.index}. ${c.alias || c.name} — ${c.bank_name} (****${(c.account_number||"").replace(/-/g,"").slice(-4)})`;
    btns += `<button class="btn btn-outline-primary btn-sm candidate-btn" data-choice="${c.index}">${escapeHtml(label)}</button>`;
  });

  const html = `<div>${escapeHtml(text)}<div class="mt-2">${btns}</div></div>`;
  const row = appendBubble("assistant", html);
  row.querySelectorAll(".candidate-btn").forEach(btn => {
    btn.addEventListener("click", () => sendMessage(btn.dataset.choice));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Update debug panel
// ─────────────────────────────────────────────────────────────────────────────

function updateDebugPanel(result) {
  const intent       = result.intent || "—";
  const pending      = result.pending_state || "none";
  const slots        = result.debug_info && result.debug_info.extracted_slots || {};
  const validation   = result.debug_info && result.debug_info.validation_result || null;
  const lsUrl        = result.langsmith_url || null;

  let rows = `
    <div class="debug-row"><span class="debug-label">인텐트</span><span class="debug-value">${escapeHtml(intent)}</span></div>
    <div class="debug-row"><span class="debug-label">대기 상태</span><span class="debug-value">${escapeHtml(pending)}</span></div>`;

  if (lsUrl) {
    rows += `<div class="debug-row"><span class="debug-label">LangSmith</span>
      <span class="debug-value"><a href="${escapeHtml(lsUrl)}" target="_blank" rel="noopener" class="small">🔭 트레이스 보기</a></span></div>`;
  }

  if (slots.recipient_alias) rows += `<div class="debug-row"><span class="debug-label">수신자 별칭</span><span class="debug-value">${escapeHtml(slots.recipient_alias)}</span></div>`;
  if (slots.amount)          rows += `<div class="debug-row"><span class="debug-label">금액</span><span class="debug-value">${formatKRW(slots.amount)}</span></div>`;
  if (slots.memo)            rows += `<div class="debug-row"><span class="debug-label">메모</span><span class="debug-value">${escapeHtml(slots.memo)}</span></div>`;
  if (slots.use_last_transfer) rows += `<div class="debug-row"><span class="debug-label">지난번처럼</span><span class="debug-value text-info">✓</span></div>`;
  if (slots.recurring_hint)  rows += `<div class="debug-row"><span class="debug-label">반복 힌트</span><span class="debug-value">${escapeHtml(slots.recurring_hint)}</span></div>`;

  if (validation) {
    const icon = validation.passed ? "✅" : "❌";
    rows += `<div class="debug-row"><span class="debug-label">검증</span><span class="debug-value">${icon} ${validation.passed ? "통과" : "실패"}</span></div>`;
    if (validation.errors && validation.errors.length) {
      rows += `<div class="text-danger small mt-1">${validation.errors.map(e => "• " + escapeHtml(e)).join("<br>")}</div>`;
    }
  }

  debugPanel.innerHTML = rows || '<p class="text-muted mb-0">—</p>';
}

// ─────────────────────────────────────────────────────────────────────────────
// Update graph trace panel
// ─────────────────────────────────────────────────────────────────────────────

function updateTracePanel(trace) {
  if (!trace || trace.length === 0) {
    tracePanel.innerHTML = '<p class="text-muted mb-0">—</p>';
    return;
  }
  const pills = trace.map((t, i) =>
    `<span class="trace-pill">${i + 1}. ${escapeHtml(t)}</span>`
  ).join(" → ");
  tracePanel.innerHTML = `<div>${pills}</div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Core send function
// ─────────────────────────────────────────────────────────────────────────────

async function sendMessage(text) {
  const message = (text || chatInput.value).trim();
  if (!message) return;

  chatInput.value = "";
  sendBtn.disabled = true;

  appendBubble("user", escapeHtml(message));
  showTyping();

  try {
    const resp = await fetch(CHAT_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const result = await resp.json();
    hideTyping();

    updateDebugPanel(result);
    updateTracePanel(result.graph_trace || []);

    const rtype = result.response_type || "message";
    const rtext = result.response_text || "";
    const rdata = result.response_data || {};

    if (rtype === "confirmation") {
      renderConfirmationCard(rtext, rdata);
    } else if (rtype === "otp_request") {
      renderOtpPrompt(rtext);
    } else if (rtype === "ambiguity") {
      renderAmbiguityCard(rtext, rdata);
    } else {
      // success / error / balance / history / recommendation / message
      const icon = rtype === "success" ? "✅ " : rtype === "error" ? "❌ " : "";
      appendBubble("assistant", icon + escapeHtml(rtext));
    }

  } catch (err) {
    hideTyping();
    appendBubble("assistant", "❌ 서버 오류가 발생했습니다: " + escapeHtml(err.message));
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event listeners
// ─────────────────────────────────────────────────────────────────────────────

chatForm.addEventListener("submit", e => {
  e.preventDefault();
  sendMessage();
});

// Sample utterance buttons
document.querySelectorAll(".sample-btn").forEach(btn => {
  btn.addEventListener("click", () => sendMessage(btn.dataset.msg));
});

// Reset chat (clears session state, not DB)
document.getElementById("btn-reset-chat").addEventListener("click", async () => {
  if (!confirm("채팅 대화를 초기화하시겠습니까?")) return;
  await fetch(RESET_API, { method: "POST" });
  msgContainer.innerHTML = "";
  debugPanel.innerHTML = '<p class="text-muted mb-0">초기화되었습니다.</p>';
  tracePanel.innerHTML = '<p class="text-muted mb-0">—</p>';
  location.reload();
});

// Reset demo data
const resetDemoBtn = document.getElementById("btn-reset-demo");
if (resetDemoBtn) {
  resetDemoBtn.addEventListener("click", async () => {
    if (!confirm("데모 데이터를 초기화하시겠습니까?\n모든 이체 내역과 채팅 기록이 삭제됩니다.")) return;
    resetDemoBtn.disabled = true;
    resetDemoBtn.textContent = "초기화 중…";
    try {
      const r = await fetch(DEMO_RESET, { method: "POST" });
      const d = await r.json();
      alert(d.message || "초기화 완료");
      location.reload();
    } catch (e) {
      alert("오류: " + e.message);
    } finally {
      resetDemoBtn.disabled = false;
    }
  });
}

// Auto-scroll on load
scrollToBottom();
