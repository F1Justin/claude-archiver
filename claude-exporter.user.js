// ==UserScript==
// @name         Claude 对话导出器 | Claude Conversation Exporter Plus
// @namespace    http://tampermonkey.net/
// @version      5.0.0
// @description  优雅导出 Claude 对话记录，支持 JSON 和 Markdown 格式，包含思考过程。Elegantly export Claude conversation records, supporting JSON and Markdown formats with thinking process.
// @author       Gao + Gemini
// @license      Custom License
// @match        https://*.claudesvip.top/chat/*
// @match        https://*.claude.ai/chat/*
// @match        https://*.fuclaude.com/chat/*
// @match        https://*.aikeji.vip/chat/*
// @match        https://share.mynanian.top/chat/*
// @match        https://demo.fuclaude.com/chat/*
// @run-at       document-start
// @grant        unsafeWindow
// @downloadURL https://update.greasyfork.org/scripts/517832/Claude%20%E5%AF%B9%E8%AF%9D%E5%AF%BC%E5%87%BA%E5%99%A8%20%7C%20Claude%20Conversation%20Exporter%20Plus.user.js
// @updateURL https://update.greasyfork.org/scripts/517832/Claude%20%E5%AF%B9%E8%AF%9D%E5%AF%BC%E5%87%BA%E5%99%A8%20%7C%20Claude%20Conversation%20Exporter%20Plus.meta.js
// ==/UserScript==

/*
 您可以在个人设备上使用和修改该代码。
 不得将该代码或其修改版本重新分发、再发布或用于其他公众渠道。
 保留所有权利，未经授权不得用于商业用途。
*/

(function() {
    'use strict';

    const targetWindow = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;

    let state = {
        targetResponse: null,
        lastUpdateTime: null,
        convertedMd: null,
        orgId: null,
        currentChatId: null,
        loading: false
    };

    let includeThinking = localStorage.getItem('claudeExporterIncludeThinking') !== 'false';

    const log = {
        info: (msg) => console.log(`[Claude Saver] ${msg}`),
        error: (msg, e) => console.error(`[Claude Saver] ${msg}`, e)
    };

    function getChatIdFromUrl() {
        const match = window.location.pathname.match(/\/chat\/([a-f0-9-]+)/);
        return match ? match[1] : null;
    }

    async function fetchOrgId() {
        if (state.orgId) return state.orgId;
        try {
            const resp = await targetWindow.fetch('/api/organizations');
            const orgs = await resp.json();
            state.orgId = orgs[0]?.uuid;
            log.info(`获取到 orgId: ${state.orgId}`);
            return state.orgId;
        } catch (e) {
            log.error('获取 orgId 失败:', e);
            return null;
        }
    }

    async function fetchConversationData() {
        const chatId = getChatIdFromUrl();
        if (!chatId) return;
        if (state.loading) return;
        if (state.currentChatId === chatId && state.targetResponse) return;

        state.loading = true;
        updateButtonStatus();

        try {
            const orgId = await fetchOrgId();
            if (!orgId) throw new Error('无法获取 orgId');

            const url = `/api/organizations/${orgId}/chat_conversations/${chatId}?tree=True&rendering_mode=messages&render_all_tools=true`;
            const resp = await targetWindow.fetch(url);

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const text = await resp.text();
            state.targetResponse = text;
            state.currentChatId = chatId;
            state.lastUpdateTime = new Date().toLocaleTimeString();

            const jsonData = JSON.parse(text);
            state.convertedMd = convertJsonToMd(jsonData);

            log.info(`成功获取对话数据 (${text.length} bytes)`);
        } catch (e) {
            log.error('获取对话数据失败:', e);
        } finally {
            state.loading = false;
            updateButtonStatus();
        }
    }

    function updateButtonStatus() {
        const jsonBtn = document.getElementById('downloadJsonButton');
        const mdBtn = document.getElementById('downloadMdButton');
        const modeBtn = document.getElementById('thinkingModeButton');
        const refreshBtn = document.getElementById('refreshDataButton');

        if (state.loading) {
            if (jsonBtn) jsonBtn.style.backgroundColor = '#ffc107';
            if (mdBtn) mdBtn.style.backgroundColor = '#ffc107';
            if (refreshBtn) refreshBtn.innerText = '加载中…';
            return;
        }

        const hasData = state.targetResponse !== null;
        if (jsonBtn) jsonBtn.style.backgroundColor = hasData ? '#28a745' : '#007bff';
        if (mdBtn) mdBtn.style.backgroundColor = state.convertedMd ? '#28a745' : '#007bff';
        if (modeBtn) modeBtn.innerText = includeThinking ? '含思考' : '无思考';
        if (refreshBtn) refreshBtn.innerText = '刷新';
    }

    // --- 核心转换逻辑 ---
    function convertJsonToMd(data) {
        if (!data || !data['chat_messages']) return "";

        let md = [];
        const title = (data.name || document.title.trim()).replace(/\s+-\s+Claude$/, '');
        md.push(`# ${title}\n`);

        const baseUrl = window.location.href.replace(/\/chat\/.*$/, '');

        for (const msg of data['chat_messages']) {
            const sender = msg['sender'] === 'human' ? 'Human' : 'Assistant';
            md.push(`## ${sender}`);
            md.push(`*${msg['created_at'] || '未知时间'}*\n`);

            if (msg['content'] && Array.isArray(msg['content'])) {
                for (const block of msg['content']) {
                    if (block.type === 'thinking' && includeThinking) {
                        const duration = (block.start_timestamp && block.stop_timestamp)
                            ? ((new Date(block.stop_timestamp) - new Date(block.start_timestamp)) / 1000).toFixed(1)
                            : null;

                        md.push(`### 思考过程 ${duration ? `(${duration}s)` : ''}`);
                        md.push(adjustHeadingLevel(block.thinking || '', 3));

                        if (block.summaries && block.summaries.length > 0) {
                            md.push(`\n**思考摘要：**`);
                            block.summaries.forEach(s => md.push(`- ${s.summary}`));
                        }
                        md.push(`\n---\n`);
                    }

                    if (block.type === 'text') {
                        let textContent = block.text || '';
                        let processedText = processLatex(textContent);
                        processedText = adjustHeadingLevel(processedText, includeThinking ? 3 : 2);
                        md.push(processedText + '\n');
                    }

                    if (block.type === 'tool_use') {
                        if (block.name === 'artifacts') {
                            const art = block.input || {};
                            const typeStr = art.type || 'text/plain';
                            const lang = typeStr.includes('/') ? typeStr.split('/').pop().replace('ant.', '') : typeStr;

                            md.push(`### Artifact: ${art.title || 'Untitled'}`);
                            md.push(`\`\`\`${lang}\n${art.content || ''}\n\`\`\`\n`);
                        } else if (block.name === 'web_search') {
                            md.push(`*> 联网搜索: ${block.input?.query || '执行搜索'}*\n`);
                        }
                    }
                }
            }

            const files = [...(msg['attachments'] || []), ...(msg['files_v2'] || [])];
            if (files.length > 0) {
                md.push(`### 附件清单`);
                files.forEach(file => {
                    const link = file.preview_url || (file.document_asset && file.document_asset.url);
                    if (link) {
                        md.push(`- [${file.file_name}](${baseUrl}${link})`);
                    } else if (file.extracted_content) {
                        md.push(`- ${file.file_name} (内容已提取)`);
                        md.push(`\n\`\`\`\n${file.extracted_content}\n\`\`\`\n`);
                    } else {
                        md.push(`- ${file.file_name}`);
                    }
                });
                md.push('');
            }
        }
        return md.join('\n');
    }

    function adjustHeadingLevel(text, increaseLevel = 2) {
        if (typeof text !== 'string' || !text) return '';

        const codeBlockPattern = /(```[\s\S]*?```)/g;
        const parts = text.split(codeBlockPattern);

        return parts.map(part => {
            if (part.startsWith('```')) return part;
            return part.split('\n').map(line => {
                if (line.trim().startsWith('#')) {
                    const levelMatch = line.match(/^#+/);
                    const level = levelMatch ? levelMatch[0].length : 0;
                    return '#'.repeat(level + increaseLevel) + line.slice(level);
                }
                return line;
            }).join('\n');
        }).join('');
    }

    function processLatex(text) {
        if (typeof text !== 'string') return '';
        return text.replace(/\$\$(.+?)\$\$/gs, (match, formula) => {
            return formula.includes('\n') ? `\n$$\n${formula.trim()}\n$$\n` : `$${formula.trim()}$`;
        });
    }

    // --- UI ---
    function createDownloadButtons() {
        if (document.getElementById('claude-exporter-ui')) return;

        const container = document.createElement('div');
        Object.assign(container.style, {
            position: 'fixed', top: '40%', right: '15px', zIndex: '10000',
            display: 'flex', flexDirection: 'column', gap: '6px',
            opacity: '0.6', transition: 'opacity 0.3s'
        });
        container.id = 'claude-exporter-ui';

        const btnStyle = `padding: 7px 12px; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 12px; font-weight: bold; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-family: sans-serif;`;

        container.innerHTML = `
            <div style="display: flex; gap: 4px;">
                <button id="downloadJsonButton" style="${btnStyle} background: #007bff; flex: 1;">JSON</button>
                <button id="downloadMdButton" style="${btnStyle} background: #007bff; flex: 1;">MD</button>
            </div>
            <div style="display: flex; gap: 4px;">
                <button id="thinkingModeButton" style="${btnStyle} background: #6c757d; flex: 1;">${includeThinking ? '含思考' : '无思考'}</button>
                <button id="refreshDataButton" style="${btnStyle} background: #17a2b8; flex: 1;">刷新</button>
            </div>
        `;

        container.onmouseenter = () => container.style.opacity = '1';
        container.onmouseleave = () => container.style.opacity = '0.6';

        document.body.appendChild(container);

        document.getElementById('downloadJsonButton').onclick = async () => {
            if (!state.targetResponse) await fetchConversationData();
            downloadFile(state.targetResponse, 'json');
        };

        document.getElementById('downloadMdButton').onclick = async () => {
            if (!state.convertedMd) await fetchConversationData();
            downloadFile(state.convertedMd, 'md');
        };

        document.getElementById('thinkingModeButton').onclick = () => {
            includeThinking = !includeThinking;
            localStorage.setItem('claudeExporterIncludeThinking', includeThinking);
            if (state.targetResponse) {
                state.convertedMd = convertJsonToMd(JSON.parse(state.targetResponse));
            }
            updateButtonStatus();
        };

        document.getElementById('refreshDataButton').onclick = () => {
            state.targetResponse = null;
            state.convertedMd = null;
            state.currentChatId = null;
            fetchConversationData();
        };

        let isDragging = false, offset = [0, 0];
        container.onmousedown = (e) => {
            if (e.target.tagName !== 'BUTTON') {
                isDragging = true;
                offset = [container.offsetLeft - e.clientX, container.offsetTop - e.clientY];
            }
        };
        document.onmousemove = (e) => {
            if (isDragging) {
                container.style.left = (e.clientX + offset[0]) + 'px';
                container.style.top = (e.clientY + offset[1]) + 'px';
                container.style.right = 'auto';
            }
        };
        document.onmouseup = () => isDragging = false;

        updateButtonStatus();
        fetchConversationData();
    }

    function downloadFile(content, ext) {
        if (!content) {
            alert("数据加载失败，请点击「刷新」按钮重试。");
            return;
        }
        const time = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 16);
        const name = document.title.split(' - ')[0].replace(/[\\/:*?"<>|]/g, '_').slice(0, 30);
        const blob = new Blob([content], { type: ext === 'json' ? 'application/json' : 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `Claude_${name}_${time}.${ext}`;
        a.click();
    }

    // --- URL 变化检测（SPA 内跳转） ---
    let lastUrl = window.location.href;
    setInterval(() => {
        if (window.location.href !== lastUrl) {
            lastUrl = window.location.href;
            if (getChatIdFromUrl()) {
                state.targetResponse = null;
                state.convertedMd = null;
                state.currentChatId = null;
                setTimeout(fetchConversationData, 500);
            }
        }
        if (!document.getElementById('claude-exporter-ui')) createDownloadButtons();
    }, 1000);

    // --- 初始化 ---
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        createDownloadButtons();
    } else {
        document.addEventListener('DOMContentLoaded', createDownloadButtons);
    }

})();
