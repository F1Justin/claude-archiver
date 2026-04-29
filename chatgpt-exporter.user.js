// ==UserScript==
// @name         ChatGPT Local JSON Exporter
// @namespace    local.chatgpt.exporter
// @version      0.3.2
// @description  Export the current ChatGPT conversation as JSON. No third-party uploads.
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(() => {
  "use strict";

  const EXPORTER_VERSION = "0.3.2";
  const BUTTON_ID = "local-json-exporter-button";
  const PANEL_ID = "local-json-exporter-panel";
  const SENSITIVE_KEY_PATTERN = /token|authorization|cookie|secret/i;
  const CHATGPT_PRIVATE_CITE_RE = /\uE200cite\uE202[^\uE201]+\uE201/g;

  const sameOriginFetchJson = async (url, init = {}) => {
    const response = await fetch(url, {
      credentials: "include",
      cache: "no-store",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.headers || {}),
      },
    });

    const text = await response.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = { parse_error: true, raw_text: text };
    }

    if (!response.ok) {
      const error = new Error(`Request failed: ${response.status} ${response.statusText}`);
      error.status = response.status;
      error.url = url;
      error.response = json;
      throw error;
    }

    return json;
  };

  const getConversationId = () => {
    const path = location.pathname;
    const patterns = [
      /\/c\/([0-9a-fA-F-]{20,})/,
      /\/chat\/([0-9a-fA-F-]{20,})/,
      /\/g\/[^/]+\/c\/([0-9a-fA-F-]{20,})/,
    ];

    for (const pattern of patterns) {
      const match = path.match(pattern);
      if (match) return match[1];
    }

    const candidate = path.split("/").filter(Boolean).find((part) => /^[0-9a-fA-F-]{20,}$/.test(part));
    return candidate || null;
  };

  const sanitizeForExport = (value, seen = new WeakSet()) => {
    if (value == null || typeof value !== "object") return value;
    if (seen.has(value)) return "[Circular]";
    seen.add(value);

    if (Array.isArray(value)) {
      return value.map((item) => sanitizeForExport(item, seen));
    }

    const sanitized = {};
    for (const [key, child] of Object.entries(value)) {
      if (SENSITIVE_KEY_PATTERN.test(key)) {
        sanitized[key] = "[redacted]";
      } else {
        sanitized[key] = sanitizeForExport(child, seen);
      }
    }
    return sanitized;
  };

  const sanitizeSession = (session) => {
    if (!session) return null;
    const sanitized = sanitizeForExport(session);
    return {
      user: sanitized.user || null,
      account: sanitized.account || null,
      authProvider: sanitized.authProvider || null,
      expires: sanitized.expires || null,
      warning_banner: sanitized.WARNING_BANNER || null,
      available_keys: Object.keys(session),
      redacted_keys: Object.keys(session).filter((key) => SENSITIVE_KEY_PATTERN.test(key)),
    };
  };

  const extractTextFromContent = (content) => {
    if (!content) return "";
    if (typeof content.text === "string") return content.text;
    if (Array.isArray(content.parts)) {
      return content.parts
        .map((part) => {
          if (typeof part === "string") return part;
          if (part && typeof part === "object") {
            if (typeof part.text === "string") return part.text;
            if (typeof part.content === "string") return part.content;
          }
          return "";
        })
        .filter(Boolean)
        .join("\n");
    }
    if (Array.isArray(content.thoughts)) {
      return content.thoughts
        .map((thought) => thought?.summary || thought?.content || thought?.text || "")
        .filter(Boolean)
        .join("\n");
    }
    return "";
  };

  const toIso = (timestamp) => {
    if (typeof timestamp !== "number") return null;
    return new Date(timestamp * 1000).toISOString();
  };

  const getModelSlug = (metadata = {}) =>
    metadata.model_slug ||
    metadata.default_model_slug ||
    metadata.request_model_slug ||
    metadata.resolved_model_slug ||
    metadata.model ||
    null;

  const stripPrivateCitationMarkup = (text = "") =>
    text
      .replace(CHATGPT_PRIVATE_CITE_RE, "")
      .replace(/[ \t]+(\n|$)/g, "$1")
      .replace(/\n{3,}/g, "\n\n")
      .trim();

  const isHiddenOrInternalMessage = (message) => {
    const metadata = message?.metadata || {};
    const contentType = message?.content?.content_type || null;
    const role = message?.author?.role || null;

    if (!["user", "assistant"].includes(role)) return true;
    if (
      metadata.is_visually_hidden_from_conversation === true ||
      metadata.is_contextual_answers_system_message === true ||
      metadata.is_thinking_preamble_message === true
    ) {
      return true;
    }

    return [
      "code",
      "thoughts",
      "reasoning_recap",
      "model_editable_context",
      "user_editable_context",
      "execution_output",
    ].includes(contentType);
  };

  const compactAttachment = (item) => {
    if (!item || typeof item !== "object") return item;
    return sanitizeForExport({
      id: item.id || item.file_id || item.asset_pointer || null,
      name: item.name || item.file_name || item.filename || null,
      type: item.type || item.mime_type || item.content_type || null,
      size: item.size || item.file_size || null,
      url: item.url || item.download_url || null,
    });
  };

  const extractAttachments = (message) => {
    const metadata = message?.metadata || {};
    const content = message?.content || {};
    const candidates = [
      metadata.attachments,
      metadata.files,
      metadata.uploaded_files,
      content.attachments,
      content.files,
    ].filter(Array.isArray);

    return candidates.flat().map(compactAttachment).filter(Boolean);
  };

  const collectDomMessages = () => {
    const turns = Array.from(document.querySelectorAll("article, section[data-turn-id], [data-message-author-role]"));
    const seen = new Set();

    return turns
      .map((node, index) => {
        const turnId = node.getAttribute("data-turn-id") || node.querySelector("[data-turn-id]")?.getAttribute("data-turn-id") || null;
        const role =
          node.getAttribute("data-message-author-role") ||
          node.querySelector("[data-message-author-role]")?.getAttribute("data-message-author-role") ||
          null;
        const text = (node.innerText || "").trim();
        const key = `${turnId || ""}:${role || ""}:${text.slice(0, 120)}`;
        if (!text || seen.has(key)) return null;
        seen.add(key);

        return {
          index,
          turn_id: turnId,
          role,
          text,
        };
      })
      .filter(Boolean);
  };

  const normalizeMessage = (messageId, message, node) => {
    if (!message) return null;
    const content = sanitizeForExport(message.content || {});
    const metadata = sanitizeForExport(message.metadata || {});
    const isHidden =
      metadata.is_visually_hidden_from_conversation === true ||
      metadata.is_contextual_answers_system_message === true ||
      metadata.is_thinking_preamble_message === true;

    return {
      id: messageId,
      parent: node?.parent || null,
      children: node?.children || [],
      role: message.author?.role || null,
      author: message.author || null,
      create_time: message.create_time || null,
      update_time: message.update_time || null,
      create_time_iso: message.create_time ? new Date(message.create_time * 1000).toISOString() : null,
      update_time_iso: message.update_time ? new Date(message.update_time * 1000).toISOString() : null,
      status: message.status || null,
      end_turn: message.end_turn ?? null,
      weight: message.weight ?? null,
      recipient: message.recipient || null,
      channel: message.channel || null,
      content_type: content.content_type || null,
      text: extractTextFromContent(content),
      content,
      model_slug:
        metadata.model_slug ||
        metadata.default_model_slug ||
        metadata.request_model_slug ||
        metadata.resolved_model_slug ||
        metadata.model ||
        null,
      resolved_model_slug: metadata.resolved_model_slug || null,
      default_model_slug: metadata.default_model_slug || null,
      request_id: metadata.request_id || null,
      turn_exchange_id: metadata.turn_exchange_id || null,
      message_type: metadata.message_type || null,
      is_complete: metadata.is_complete ?? null,
      is_visible: !isHidden,
      finish_details: metadata.finish_details || null,
      search_queries: metadata.search_queries || [],
      search_result_groups: metadata.search_result_groups || [],
      metadata,
    };
  };

  const normalizeConversation = (conversation, options = {}) => {
    const mapping = conversation?.mapping || {};
    const messages = Object.entries(mapping)
      .map(([id, node]) => normalizeMessage(id, node?.message, node))
      .filter(Boolean)
      .sort((a, b) => {
        const at = typeof a.create_time === "number" ? a.create_time : Number.MAX_SAFE_INTEGER;
        const bt = typeof b.create_time === "number" ? b.create_time : Number.MAX_SAFE_INTEGER;
        return at - bt;
      });

    const models = Array.from(
      new Set(
        messages
          .map((message) => message.model_slug)
          .filter(Boolean)
      )
    );

    return {
      id: conversation?.conversation_id || conversation?.id || getConversationId(),
      title: conversation?.title || document.title || null,
      create_time: conversation?.create_time || null,
      update_time: conversation?.update_time || null,
      create_time_iso: conversation?.create_time ? new Date(conversation.create_time * 1000).toISOString() : null,
      update_time_iso: conversation?.update_time ? new Date(conversation.update_time * 1000).toISOString() : null,
      current_node: conversation?.current_node || null,
      default_model_slug: conversation?.default_model_slug || null,
      flags: {
        is_archived: conversation?.is_archived ?? null,
        is_starred: conversation?.is_starred ?? null,
        is_temporary_chat: conversation?.is_temporary_chat ?? null,
        is_do_not_remember: conversation?.is_do_not_remember ?? null,
        is_read_only: conversation?.is_read_only ?? null,
        is_study_mode: conversation?.is_study_mode ?? null,
      },
      raw_top_level: sanitizeForExport(
        Object.fromEntries(
          Object.entries(conversation || {}).filter(([key]) => key !== "mapping")
        )
      ),
      raw_mapping_count: Object.keys(mapping).length,
      models,
      message_count: messages.length,
      messages,
      raw: options.includeRaw ? sanitizeForExport(conversation || null) : undefined,
    };
  };

  const buildClaudeLikeConversation = (conversation, session = null) => {
    const mapping = conversation?.mapping || {};
    const normalized = Object.entries(mapping)
      .map(([id, node]) => {
        const message = node?.message;
        if (!message || isHiddenOrInternalMessage(message)) return null;

        const content = sanitizeForExport(message.content || {});
        const metadata = sanitizeForExport(message.metadata || {});
        const rawText = extractTextFromContent(content).trim();
        const text = stripPrivateCitationMarkup(rawText);
        if (!text) return null;

        const createdAt = toIso(message.create_time);
        const updatedAt = toIso(message.update_time) || createdAt;
        const sender = message.author?.role === "user" ? "human" : "assistant";
        const attachments = extractAttachments(message);
        const model = getModelSlug(metadata);

        return {
          uuid: id,
          text,
          content: [
            {
              start_timestamp: createdAt,
              stop_timestamp: updatedAt,
              type: "text",
              text,
            },
          ],
          sender,
          index: 0,
          created_at: createdAt,
          updated_at: updatedAt,
          attachments,
          files: attachments,
          files_v2: attachments,
          parent_message_uuid: node?.parent || "00000000-0000-4000-8000-000000000000",
          model,
        };
      })
      .filter(Boolean)
      .sort((a, b) => {
        const at = a.created_at ? Date.parse(a.created_at) : Number.MAX_SAFE_INTEGER;
        const bt = b.created_at ? Date.parse(b.created_at) : Number.MAX_SAFE_INTEGER;
        return at - bt;
      });

    const exportedIds = new Set(normalized.map((message) => message.uuid));
    normalized.forEach((message, index) => {
      message.index = index;
      if (index === 0 || !exportedIds.has(message.parent_message_uuid)) {
        message.parent_message_uuid = index === 0 ? "00000000-0000-4000-8000-000000000000" : normalized[index - 1].uuid;
      }
    });

    const models = Array.from(new Set(normalized.map((message) => message.model).filter(Boolean)));

    return {
      uuid: conversation?.conversation_id || conversation?.id || getConversationId(),
      name: conversation?.title || document.title || "ChatGPT conversation",
      summary: "",
      model: conversation?.default_model_slug || models[0] || null,
      created_at: toIso(conversation?.create_time) || normalized[0]?.created_at || null,
      updated_at: toIso(conversation?.update_time) || normalized[normalized.length - 1]?.updated_at || null,
      account: {},
      settings: {
        models,
        source: "chatgpt_web_backend",
        exporter: "ChatGPT Local JSON Exporter",
        exporter_version: EXPORTER_VERSION,
      },
      platform: "CHATGPT",
      is_starred: conversation?.is_starred ?? false,
      chat_messages: normalized,
      export_warnings: session ? [] : ["Session metadata was unavailable; conversation may have been exported from fallback data."],
    };
  };

  const buildClaudeLikeFallback = (conversationId, session = null) => {
    const domMessages = collectDomMessages();
    const chatMessages = domMessages.map((message, index) => ({
      uuid: message.turn_id || `dom-${index}`,
      text: message.text,
      content: [
        {
          start_timestamp: null,
          stop_timestamp: null,
          type: "text",
          text: message.text,
        },
      ],
      sender: message.role === "assistant" ? "assistant" : "human",
      index,
      created_at: null,
      updated_at: null,
      attachments: [],
      files: [],
      files_v2: [],
      parent_message_uuid: index === 0 ? "00000000-0000-4000-8000-000000000000" : domMessages[index - 1].turn_id || `dom-${index - 1}`,
      model: null,
    }));

    return {
      uuid: conversationId,
      name: document.title || "ChatGPT conversation",
      summary: "",
      model: null,
      created_at: null,
      updated_at: null,
      account: {},
      settings: {
        models: [],
        source: "chatgpt_dom_fallback",
        exporter: "ChatGPT Local JSON Exporter",
        exporter_version: EXPORTER_VERSION,
      },
      platform: "CHATGPT",
      is_starred: false,
      chat_messages: chatMessages,
      export_warnings: ["Backend API unavailable; exported visible page text only."],
    };
  };

  const makeFilename = (payload) => {
    const title = payload.name || payload.conversation?.title || "chatgpt-conversation";
    const safeTitle = title
      .normalize("NFKD")
      .replace(/[\\/:*?"<>|]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80) || "chatgpt-conversation";
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    return `ChatGPT_${safeTitle}_${timestamp}.json`;
  };

  const downloadJson = (payload) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = makeFilename(payload);
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const exportCurrentConversation = async (options = {}) => {
    const exportOptions = {
      format: "claude",
      includeRaw: false,
      includeDomFallbackWhenBackendSucceeds: false,
      ...options,
    };
    const conversationId = getConversationId();
    const fullPayload = {
      exporter: {
        name: "ChatGPT Local JSON Exporter",
        version: EXPORTER_VERSION,
        exported_at: new Date().toISOString(),
        page_url: location.href,
        user_agent: navigator.userAgent,
        network_policy: "Only same-origin ChatGPT/OpenAI endpoints are requested. No third-party upload.",
        output_policy: "Clean JSON by default: no DOM HTML, no session tokens, no duplicate raw mapping unless includeRaw is explicitly enabled.",
        options: exportOptions,
      },
      session: null,
      conversation: null,
      dom_fallback: null,
      errors: [],
    };

    let rawSession = null;
    try {
      rawSession = await sameOriginFetchJson("/api/auth/session");
      fullPayload.session = sanitizeSession(rawSession);
    } catch (error) {
      fullPayload.errors.push({
        step: "fetch_session",
        message: error.message,
        status: error.status || null,
        response: error.response || null,
      });
    }

    if (conversationId) {
      try {
        let headers = {};
        const accessToken = rawSession?.accessToken || rawSession?.access_token;
        if (accessToken) {
          headers = { Authorization: `Bearer ${accessToken}` };
        }

        const rawConversation = await sameOriginFetchJson(`/backend-api/conversation/${conversationId}`, { headers });
        if (exportOptions.format === "full") {
          fullPayload.conversation = normalizeConversation(rawConversation, exportOptions);
        } else {
          const compactPayload = buildClaudeLikeConversation(rawConversation, rawSession);
          downloadJson(compactPayload);
          return compactPayload;
        }
      } catch (error) {
        fullPayload.errors.push({
          step: "fetch_conversation",
          conversation_id: conversationId,
          message: error.message,
          status: error.status || null,
          response: error.response || null,
        });
      }
    } else {
      fullPayload.errors.push({
        step: "detect_conversation_id",
        message: "No conversation id found in the current URL. DOM fallback was still exported.",
      });
    }

    if (exportOptions.format !== "full") {
      const compactPayload = buildClaudeLikeFallback(conversationId, rawSession);
      downloadJson(compactPayload);
      return compactPayload;
    }

    if (!fullPayload.conversation) {
      const domMessages = collectDomMessages();
      fullPayload.conversation = {
        id: conversationId,
        title: document.title || null,
        message_count: domMessages.length,
        messages: [],
      };
      fullPayload.dom_fallback = {
        used: true,
        reason: "Backend conversation JSON was not available. Exported text from the currently rendered page only.",
        message_count: domMessages.length,
        messages: domMessages,
      };
    } else if (exportOptions.includeDomFallbackWhenBackendSucceeds) {
      const domMessages = collectDomMessages();
      fullPayload.dom_fallback = {
        used: false,
        reason: "Backend conversation JSON succeeded. DOM fallback is included only because the option was enabled.",
        message_count: domMessages.length,
        messages: domMessages,
      };
    }

    downloadJson(fullPayload);
    return fullPayload;
  };

  const showStatus = (text, isError = false) => {
    let panel = document.getElementById(PANEL_ID);
    if (!panel) {
      panel = document.createElement("div");
      panel.id = PANEL_ID;
      panel.style.cssText = [
        "position:fixed",
        "right:16px",
        "bottom:64px",
        "z-index:2147483647",
        "max-width:360px",
        "padding:10px 12px",
        "border-radius:8px",
        "font:12px/1.4 system-ui,-apple-system,BlinkMacSystemFont,sans-serif",
        "box-shadow:0 8px 24px rgba(0,0,0,.18)",
        "background:#111827",
        "color:#f9fafb",
      ].join(";");
      document.documentElement.appendChild(panel);
    }
    panel.textContent = text;
    panel.style.background = isError ? "#7f1d1d" : "#111827";
    clearTimeout(panel._hideTimer);
    panel._hideTimer = setTimeout(() => panel.remove(), 6000);
  };

  const installButton = () => {
    if (document.getElementById(BUTTON_ID)) return;

    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "Export JSON";
    button.title = "Export current ChatGPT conversation as local JSON";
    button.style.cssText = [
      "position:fixed",
      "right:16px",
      "bottom:16px",
      "z-index:2147483647",
      "border:0",
      "border-radius:8px",
      "padding:10px 12px",
      "font:600 13px system-ui,-apple-system,BlinkMacSystemFont,sans-serif",
      "background:#0f766e",
      "color:white",
      "box-shadow:0 8px 24px rgba(0,0,0,.18)",
      "cursor:pointer",
    ].join(";");

    button.addEventListener("click", async () => {
      button.disabled = true;
      button.style.opacity = "0.72";
      showStatus("Exporting current conversation as JSON...");
      try {
        const payload = await exportCurrentConversation();
        const messageCount = payload.chat_messages?.length || payload.conversation?.message_count || 0;
        const warningCount = payload.export_warnings?.length || payload.errors?.length || 0;
        showStatus(`JSON exported. Messages: ${messageCount}. Warnings: ${warningCount}.`, warningCount > 0);
      } catch (error) {
        console.error("[local-json-exporter]", error);
        showStatus(`Export failed: ${error.message}`, true);
      } finally {
        button.disabled = false;
        button.style.opacity = "1";
      }
    });

    document.documentElement.appendChild(button);
  };

  window.ChatGPTLocalJsonExporter = {
    exportCurrentConversation,
    collectDomMessages,
    buildClaudeLikeConversation,
    sanitizeForExport,
    version: EXPORTER_VERSION,
  };

  installButton();
})();
