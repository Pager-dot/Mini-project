/**
 * script.js — Chat page logic.
 *
 * Handles message sending/receiving, voice recording & transcription,
 * conversation history persistence (localStorage for auth users,
 * sessionStorage for guests), and user info display.
 */

// --- DOM Element References ---
const chatContainer = document.getElementById('chat-container');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const voiceBtn = document.getElementById('voice-btn');

const userMessageTemplate = document.getElementById('user-message-template');
const botMessageTemplate = document.getElementById('bot-message-template');
const typingIndicatorTemplate = document.getElementById('typing-indicator-template');

// Active uploaded-doc collection name, persisted in sessionStorage across page navigations.
let currentCollectionName = sessionStorage.getItem('activeCollectionName') || null;

// In-memory chat history array, its storage key, and guest flag.
let conversationHistory = [];
let historyStorageKey = null;
let isGuestUser = false;

// Return current time as a short "HH:MM" string for message timestamps.
function timeNow() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Return today's date as "YYYY-MM-DD" — used to key history so it auto-expires at midnight.
function todayStr() {
  return new Date().toISOString().split('T')[0];
}

// Persist conversation history — guests use sessionStorage (lost on tab close),
// authenticated users use localStorage (survives browser restarts).
function saveHistory() {
  if (!historyStorageKey) return;
  const storage = isGuestUser ? sessionStorage : localStorage;
  storage.setItem(historyStorageKey, JSON.stringify(conversationHistory));
}

// Load conversation history from storage. For authenticated users, also
// cleans up entries from previous days to avoid stale data buildup.
function loadHistory(isGuest, userId) {
  isGuestUser = isGuest;
  if (isGuest) {
    historyStorageKey = 'chat_history_guest';
    const raw = sessionStorage.getItem(historyStorageKey);
    return raw ? JSON.parse(raw) : [];
  } else {
    historyStorageKey = `chat_history_${userId}_${todayStr()}`;
    // Remove any entries from previous days
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key && key.startsWith(`chat_history_${userId}_`) && key !== historyStorageKey) {
        localStorage.removeItem(key);
      }
    }
    const raw = localStorage.getItem(historyStorageKey);
    return raw ? JSON.parse(raw) : [];
  }
}

// --- 1. FETCH USER INFO & RESTORE HISTORY ---
// On page load: fetch user info from /user_info, display name/avatar,
// load stored chat history, and re-render all previous messages.
document.addEventListener('DOMContentLoaded', () => {
  fetch('/user_info')
    .then(r => r.json())
    .then(data => {
      if (data.name) {
        const strip = document.getElementById('user-strip');
        const nameEl = document.getElementById('user-name');
        if (strip)  { strip.style.display = 'flex'; strip.classList.remove('hidden'); }
        if (nameEl) nameEl.textContent = data.name;
        if (data.picture) {
          const av = document.getElementById('chat-user-avatar');
          if (av) av.src = data.picture;
        }
      }

      const isGuest = data.sub === 'guest';
      const userId = data.sub || 'unknown';

      conversationHistory = loadHistory(isGuest, userId);

      // Re-display stored messages
      conversationHistory.forEach(msg => {
        const template = msg.role === 'user' ? userMessageTemplate : botMessageTemplate;
        displayMessage(template, msg.content, msg.role === 'user');
      });
    })
    .catch(() => {});
});

// --- 2. DISPLAY MESSAGE ---
// Clone a message template, inject text (plain for user, markdown-parsed for bot),
// add timestamp, append to chat container, and auto-scroll to the bottom.
function displayMessage(template, text, isUser = false) {
  const clone = template.cloneNode(true);
  clone.removeAttribute('id');
  clone.classList.remove('hidden');

  const textEl = clone.querySelector('p');
  if (isUser) {
    textEl.textContent = text;
  } else {
    textEl.innerHTML = marked.parse(text);
  }

  const timeEl = clone.querySelector('.msg-time');
  if (timeEl) timeEl.textContent = timeNow();

  chatContainer.appendChild(clone);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return clone;
}

// --- 3. SEND MESSAGE ---
// Send user's message to /chat with last 10 history items and the active
// collection name. Shows a typing indicator while waiting, then displays
// the bot's response and persists both messages to history.
async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message) return;

  displayMessage(userMessageTemplate, message, true);
  messageInput.value = '';

  // Capture last 10 messages as context BEFORE adding the current one
  const historySlice = conversationHistory.slice(-10);

  conversationHistory.push({ role: 'user', content: message });
  saveHistory();

  // Typing indicator
  const typingClone = typingIndicatorTemplate.cloneNode(true);
  typingClone.removeAttribute('id');
  typingClone.classList.remove('hidden');
  chatContainer.appendChild(typingClone);
  chatContainer.scrollTop = chatContainer.scrollHeight;

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, collection_name: currentCollectionName, history: historySlice })
    });

    chatContainer.removeChild(typingClone);

    if (!response.ok) throw new Error('Network response was not ok');
    const data = await response.json();
    displayMessage(botMessageTemplate, data.answer);

    conversationHistory.push({ role: 'assistant', content: data.answer });
    saveHistory();

  } catch (error) {
    if (chatContainer.contains(typingClone)) chatContainer.removeChild(typingClone);
    displayMessage(botMessageTemplate, "Sorry, I couldn't reach the server.");
    console.error(error);
  }
}

// --- 4. MICROPHONE LOGIC ---
// Toggle voice recording on button click. Uses MediaRecorder API to capture
// audio in WebM format, sends to /transcribe-audio/ for speech-to-text,
// then auto-sends the transcribed text as a chat message.
let isRecording = false;
let mediaRecorder;
let audioChunks = [];

voiceBtn.addEventListener('click', async () => {
  if (isRecording) {
    voiceBtn.classList.remove('recording');
    isRecording = false;
    if (mediaRecorder) mediaRecorder.stop();
  } else {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        stream.getTracks().forEach(t => t.stop());

        const formData = new FormData();
        formData.append("audio_file", audioBlob, "recording.webm");

        const loadingMsg = displayMessage(botMessageTemplate, "*Transcribing audio…*");
        const res = await fetch("/transcribe-audio/", { method: "POST", body: formData });
        const data = await res.json();

        chatContainer.removeChild(loadingMsg);

        if (data.text_english) {
          messageInput.value = data.text_english;
          sendMessage();
        } else {
          displayMessage(botMessageTemplate, "Could not understand audio.");
        }
      };

      mediaRecorder.start();
      voiceBtn.classList.add('recording');
      isRecording = true;
    } catch (err) {
      console.error(err);
      alert("Microphone access denied.");
    }
  }
});

// --- 5. EVENT LISTENERS ---
// Wire up send button click and Enter key to sendMessage().
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); sendMessage(); }
});
