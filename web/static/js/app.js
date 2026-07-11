/**
 * CodeMind IDE — main controller.
 *
 * Wires together:
 * - Monaco Editor (loaded from CDN via require.js)
 * - File tree (fetched from /api/files)
 * - Chat panel (WebSocket to /ws)
 * - Terminal panel (tool output logging)
 */

// ── State ──
let editor = null;
let monaco = null;
let ws = null;
let currentFile = null;
let _lastAssistantDiv = null;

// ── DOM refs ──
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── Language map ──
const LANG_MAP = {
    'py': 'python', 'js': 'javascript', 'ts': 'typescript',
    'html': 'html', 'css': 'css', 'json': 'json', 'md': 'markdown',
    'yaml': 'yaml', 'yml': 'yaml', 'toml': 'toml', 'sh': 'shell',
    'bash': 'shell', 'rs': 'rust', 'go': 'go', 'java': 'java',
    'c': 'c', 'cpp': 'cpp', 'h': 'c', 'hpp': 'cpp',
    'jsx': 'javascript', 'tsx': 'typescript', 'xml': 'xml',
};

// ── CSS.escape polyfill ──
if (!CSS.escape) {
    CSS.escape = function (value) {
        return String(value).replace(/([^\w-])/g, '\\$1');
    };
}

// ── Initialization ──
require.config({
    paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }
});

require(['vs/editor/editor.main'], function (monacoInstance) {
    monaco = monacoInstance || window.monaco;
    initEditor();
    initWebSocket();
    loadWorkspace();
    loadFileTree('');
    bindEvents();
});

// ── Editor ──
function initEditor() {
    if (!monaco) {
        monaco = window.monaco;
    }
    if (!monaco) {
        setTimeout(initEditor, 100);
        return;
    }
    editor = monaco.editor.create($('#editor-container'), {
        value: '// Welcome to CodeMind IDE\n// Select a file from the tree or start chatting!\n',
        language: 'plaintext',
        theme: 'vs-dark',
        fontSize: 14,
        fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
        minimap: { enabled: false },
        automaticLayout: true,
        scrollBeyondLastLine: false,
        lineNumbers: 'on',
        renderWhitespace: 'selection',
        tabSize: 4,
    });
}

function openFileInEditor(path, content) {
    if (!editor || !monaco) return;
    const ext = path.split('.').pop().toLowerCase();
    const lang = LANG_MAP[ext] || 'plaintext';
    const model = editor.getModel();
    monaco.editor.setModelLanguage(model, lang);
    editor.setValue(content);
    currentFile = path;
    updateTabs();
}

// ── Tabs ──
function updateTabs() {
    const tabs = $('#editor-tabs');
    if (!tabs) return;
    tabs.innerHTML = '';
    if (currentFile) {
        const span = document.createElement('span');
        span.className = 'editor-tab active';
        span.textContent = currentFile.split('/').pop();
        span.title = currentFile;
        tabs.appendChild(span);
    }
}

// ── File Tree ──
async function loadFileTree(subpath) {
    try {
        const resp = await fetch(`/api/files?path=${encodeURIComponent(subpath)}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            terminalLog(`File tree error: ${resp.status} ${err.detail || JSON.stringify(err)}`, 'error');
            return;
        }
        const data = await resp.json();
        renderFileTree(data.files, subpath);
    } catch (e) {
        terminalLog(`File tree error: ${e.message}`, 'error');
    }
}

function renderFileTree(files, parentPath) {
    const tree = $('#filetree');
    if (!parentPath) tree.innerHTML = '';

    const sorted = [...files].sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        return a.name.localeCompare(b.name);
    });

    for (const f of sorted) {
        const entry = document.createElement('div');
        entry.className = `file-entry ${f.is_dir ? 'dir' : 'file'}`;
        entry.dataset.path = f.path;
        entry.dataset.isDir = f.is_dir;
        entry.innerHTML = `<span class="icon">${f.is_dir ? '📁' : '📄'}</span><span class="name">${f.name}</span>`;

        entry.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (f.is_dir) {
                const subContainer = entry.nextElementSibling;
                if (subContainer && subContainer.classList.contains('sub-tree')) {
                    subContainer.remove();
                    entry.querySelector('.icon').textContent = '📁';
                } else {
                    entry.querySelector('.icon').textContent = '📂';
                    const subDiv = document.createElement('div');
                    subDiv.className = 'sub-tree';
                    subDiv.style.paddingLeft = '16px';
                    entry.after(subDiv);
                    try {
                        const resp = await fetch(`/api/files?path=${encodeURIComponent(f.path)}`);
                        const data = await resp.json();
                        renderSubTree(data.files, subDiv);
                    } catch (err) {
                        console.error(err);
                    }
                }
            } else {
                $$('.file-entry.active').forEach(el => el.classList.remove('active'));
                entry.classList.add('active');
                try {
                    const resp = await fetch(`/api/files/read?path=${encodeURIComponent(f.path)}`);
                    const data = await resp.json();
                    openFileInEditor(f.path, data.content);
                } catch (err) {
                    terminalLog(`Error reading ${f.path}`, 'error');
                }
            }
        });

        tree.appendChild(entry);
    }
}

function renderSubTree(files, container) {
    const sorted = [...files].sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        return a.name.localeCompare(b.name);
    });
    for (const f of sorted) {
        const entry = document.createElement('div');
        entry.className = `file-entry ${f.is_dir ? 'dir' : 'file'}`;
        entry.dataset.path = f.path;
        entry.innerHTML = `<span class="icon">${f.is_dir ? '📁' : '📄'}</span><span class="name">${f.name}</span>`;
        entry.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!f.is_dir) {
                $$('.file-entry.active').forEach(el => el.classList.remove('active'));
                entry.classList.add('active');
                try {
                    const resp = await fetch(`/api/files/read?path=${encodeURIComponent(f.path)}`);
                    const data = await resp.json();
                    openFileInEditor(f.path, data.content);
                } catch (err) {
                    terminalLog(`Error reading ${f.path}`, 'error');
                }
            }
        });
        container.appendChild(entry);
    }
}

// ── Chat ──
function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        terminalLog('Connected to CodeMind agent', 'info');
        updateStatus('idle', 'Ready');
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'text') {
            removeThinking();
            if (_lastAssistantDiv) {
                _lastAssistantDiv.querySelector('.body').textContent = msg.content;
            } else {
                _lastAssistantDiv = appendAssistantBubble('');
                _lastAssistantDiv.querySelector('.body').textContent = msg.content;
            }
        } else if (msg.type === 'status') {
            if (msg.status === 'thinking') {
                updateStatus('thinking', 'Thinking...');
            } else if (msg.status === 'done' || msg.status === 'stopped') {
                updateStatus('idle', msg.status === 'stopped' ? 'Stopped' : 'Ready');
                enableSend();
                _lastAssistantDiv = null;
            } else if (msg.status === 'cleared') {
                $('#chat-messages').innerHTML = '';
                _lastAssistantDiv = null;
            }
        } else if (msg.type === 'error') {
            terminalLog(msg.content, 'error');
            updateStatus('idle', 'Error');
            enableSend();
        }
    };

    ws.onclose = () => {
        updateStatus('idle', 'Disconnected');
        terminalLog('WebSocket disconnected, reconnecting...', 'error');
        setTimeout(initWebSocket, 3000);
    };
}

function sendChat() {
    const input = $('#chat-input');
    const content = input.value.trim();
    if (!content || !ws || ws.readyState !== WebSocket.OPEN) return;

    appendUserBubble(content);
    input.value = '';
    disableSend();
    appendThinking();
    ws.send(JSON.stringify({ type: 'chat', content }));
}

function appendUserBubble(content) {
    const div = document.createElement('div');
    div.className = 'msg user';
    div.innerHTML = `<div class="role">You</div><div>${escapeHtml(content)}</div>`;
    $('#chat-messages').appendChild(div);
    scrollChat();
}

function appendAssistantBubble(content) {
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `<div class="role">CodeMind</div><div class="body">${escapeHtml(content)}</div>`;
    $('#chat-messages').appendChild(div);
    scrollChat();
    return div;
}

function appendThinking() {
    const div = document.createElement('div');
    div.className = 'msg assistant thinking';
    div.id = 'msg-thinking';
    div.innerHTML = `<div class="role">CodeMind</div><div class="body"><em>Thinking...</em></div>`;
    $('#chat-messages').appendChild(div);
    scrollChat();
}

function removeThinking() {
    const el = $('#msg-thinking');
    if (el) el.remove();
}

function scrollChat() {
    const msgs = $('#chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

// ── Terminal ──
function terminalLog(text, level = 'info') {
    const out = $('#terminal-output');
    const div = document.createElement('div');
    div.className = `term-entry ${level}`;
    div.textContent = text;
    out.appendChild(div);
    out.scrollTop = out.scrollHeight;
}

// ── Status ──
function updateStatus(state, text) {
    const dot = $('#status-dot');
    const label = $('#status-text');
    if (dot) dot.className = state === 'thinking' ? 'dot-thinking' : 'dot-idle';
    if (label) label.textContent = text;
}

function disableSend() {
    $('#btn-send').style.display = 'none';
    $('#btn-stop').style.display = '';
}

function enableSend() {
    $('#btn-send').style.display = '';
    $('#btn-stop').style.display = 'none';
}

function stopAgent() {
    fetch('/api/stop');
    enableSend();
}

// ── Utils ──
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Folder dialog ──
async function browseFolder() {
    try {
        const resp = await fetch('/api/browse-folder');
        const data = await resp.json();
        if (data.status === 'ok') {
            $('#workspace-path').textContent = data.workspace;
            $('#folder-dialog').style.display = 'none';
            loadFileTree('');
            terminalLog(`Workspace: ${data.workspace}`, 'info');
        } else if (!data.cancelled) {
            terminalLog(data.error || 'Failed', 'error');
        }
    } catch (e) {
        terminalLog('Failed to open folder picker', 'error');
    }
}

function toggleFolderDialog() {
    const dlg = $('#folder-dialog');
    const show = dlg.style.display === 'none';
    dlg.style.display = show ? 'flex' : 'none';
    if (show) {
        $('#folder-input').value = '';
        $('#folder-input').focus();
    }
}

async function openFolder() {
    const path = $('#folder-input').value.trim();
    if (!path) return;
    try {
        const resp = await fetch(`/api/open-folder?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        if (data.error) {
            terminalLog(data.error, 'error');
        } else {
            $('#workspace-path').textContent = data.workspace;
            $('#folder-dialog').style.display = 'none';
            loadFileTree('');
            terminalLog(`Workspace: ${data.workspace}`, 'info');
        }
    } catch (e) {
        terminalLog('Failed to open folder', 'error');
    }
}

async function loadWorkspace() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        $('#workspace-path').textContent = data.workspace;
    } catch (e) {}
}

// ── Events ──
function bindEvents() {
    $('#btn-send').addEventListener('click', sendChat);
    $('#btn-stop').addEventListener('click', stopAgent);
    $('#btn-open-folder').addEventListener('click', browseFolder);
    $('#btn-folder-ok').addEventListener('click', openFolder);
    $('#btn-folder-cancel').addEventListener('click', () => {
        $('#folder-dialog').style.display = 'none';
    });
    $('#folder-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') openFolder();
        if (e.key === 'Escape') $('#folder-dialog').style.display = 'none';
    });
    $('#chat-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        }
    });
    $('#btn-refresh').addEventListener('click', () => loadFileTree(''));
    $('#workspace-path').addEventListener('click', toggleFolderDialog);
}
