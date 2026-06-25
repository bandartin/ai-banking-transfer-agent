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

const msgContainer  = document.getElementById("chat-messages");
const chatForm      = document.getElementById("chat-form");
const chatInput     = document.getElementById("chat-input");
const sendBtn       = document.getElementById("send-btn");
const debugPanel    = document.getElementById("debug-panel");
const tracePanel    = document.getElementById("trace-panel");
const planPanel     = document.getElementById("plan-panel");
const activityPanel = document.getElementById("activity-panel");
const userSelect    = document.getElementById("user-select");

// 에이전트별 표시 색/이름
const AGENT_META = {
  supervisor: { label: "Supervisor", color: "#6f42c1" },
  transfer:   { label: "Transfer",   color: "#0d6efd" },
  inquiry:    { label: "Inquiry",    color: "#198754" },
  recommend:  { label: "Recommend",  color: "#fd7e14" },
  security:   { label: "Security",   color: "#dc3545" },
};

const EVENT_LABELS = {
  plan: "실행 계획 수립",
  respond: "응답 합성",
  start: "이체 분석 시작",
  resolved: "수신자 해석 완료",
  clarified: "되묻기 해소",
  alias_learned: "🧠 호칭 학습",
  reinterpret: "답변 재해석",
  security_consult: "→ Security 협업 의뢰",
  assess_done: "리스크 평가 완료",
  validated: "검증 통과",
  validation_failed: "검증 실패",
  amount_changed: "금액 수정",
  otp_verified: "OTP 인증 성공",
  otp_failed: "OTP 인증 실패",
  executed: "✅ 이체 실행",
  cancelled: "이체 취소",
  handoff_to_supervisor: "↩ Supervisor 핸드오프",
  balance_done: "잔액 조회 완료",
  history_done: "내역 조회 완료",
  recurring_done: "자동이체 조회 완료",
  done: "추천 완료",
  report_done: "보안 리포트 완료",
};

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
  if (slots.bank_hint)       rows += `<div class="debug-row"><span class="debug-label">은행 힌트</span><span class="debug-value">${escapeHtml(slots.bank_hint)}</span></div>`;
  if (slots.source_account_hint) rows += `<div class="debug-row"><span class="debug-label">출금계좌 힌트</span><span class="debug-value">${escapeHtml(slots.source_account_hint)}</span></div>`;
  if (slots.extraction_method) rows += `<div class="debug-row"><span class="debug-label">Slot 방식</span><span class="debug-value">${escapeHtml(slots.extraction_method)}</span></div>`;
  if (slots.ambiguous_fields && slots.ambiguous_fields.length) {
    rows += `<div class="text-warning small mt-1">확인 필요: ${slots.ambiguous_fields.map(escapeHtml).join(", ")}</div>`;
  }

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
// Supervisor 계획 패널 — 리더 에이전트가 어떤 하위 에이전트를 부르는지 가시화
// ─────────────────────────────────────────────────────────────────────────────

function agentChip(agent) {
  const meta = AGENT_META[agent] || { label: agent, color: "#6c757d" };
  return `<span class="badge" style="background:${meta.color};font-size:11px;">${meta.label}</span>`;
}

function updatePlanPanel(plan) {
  if (!plan) {
    planPanel.innerHTML = '<span class="text-muted" style="font-size:12px;">—</span>';
    return;
  }
  const steps = plan.steps || [];
  let html = `
    <div class="d-flex justify-content-between align-items-center mb-1">
      <span style="font-size:12px;">${agentChip("supervisor")}
        <span class="text-muted">planner: ${escapeHtml(plan.planner || "rule")}</span></span>
      ${plan.parallel ? '<span class="badge bg-info" style="font-size:10px;">⚡ 병렬 실행</span>' : ""}
    </div>`;

  if (!steps.length) {
    html += '<div class="text-muted" style="font-size:12px;">호출할 하위 에이전트 없음 (직접 응답)</div>';
  } else {
    html += steps.map(s => `
      <div class="border rounded p-1 mb-1" style="font-size:12px;">
        ${agentChip(s.agent)} <code style="font-size:11px;">${escapeHtml(s.sub_intent)}</code>
        <div class="text-muted" style="font-size:11px;">${escapeHtml(s.reason || "")}</div>
      </div>`).join("");
  }
  planPanel.innerHTML = html;
}

// ─────────────────────────────────────────────────────────────────────────────
// 에이전트 협업 타임라인
// ─────────────────────────────────────────────────────────────────────────────

function updateActivityPanel(activity) {
  if (!activity || !activity.length) {
    activityPanel.innerHTML = '<span class="text-muted" style="font-size:12px;">—</span>';
    return;
  }
  const rows = activity.map(a => {
    const label = EVENT_LABELS[a.event] || a.event;
    const detail = a.detail || {};
    let extra = "";
    if (detail.note) extra = escapeHtml(detail.note);
    else if (detail.name) extra = escapeHtml(detail.name);
    else if (detail.risk_score !== undefined) extra = `위험도 ${detail.risk_score}점 (${detail.level})`;
    else if (detail.steps) extra = detail.steps.map(s => s.agent).join(" + ");
    else if (detail.new_amount) extra = formatKRW(detail.new_amount);
    return `
      <div class="d-flex align-items-start gap-1 mb-1" style="font-size:12px;">
        <span class="text-muted" style="font-size:10px;min-width:52px;">${escapeHtml(a.ts || "")}</span>
        ${agentChip(a.agent)}
        <span>${escapeHtml(label)}${extra ? ` <span class="text-muted">· ${extra}</span>` : ""}</span>
      </div>`;
  }).join("");
  activityPanel.innerHTML = rows;
  activityPanel.scrollTop = activityPanel.scrollHeight;
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
    updatePlanPanel(result.plan);
    updateActivityPanel(result.agent_activity || []);

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

// 데모 사용자 전환 (나이 기반 맞춤 말투 시연)
if (userSelect) {
  userSelect.addEventListener("change", async () => {
    const resp = await fetch("/api/chat/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: Number(userSelect.value) }),
    });
    if (resp.ok) location.reload();
  });
}

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
