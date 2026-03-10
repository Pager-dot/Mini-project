const chatContainer = document.getElementById('chat-container');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const voiceBtn = document.getElementById('voice-btn');

const userMessageTemplate = document.getElementById('user-message-template');
const botMessageTemplate = document.getElementById('bot-message-template');
const typingIndicatorTemplate = document.getElementById('typing-indicator-template');

let currentCollectionName = sessionStorage.getItem('activeCollectionName') || null;

// Helper: current time string
function timeNow() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// --- 1. FETCH USER INFO ---
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
    })
    .catch(() => {});
});

// --- 2. DISPLAY MESSAGE ---
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

  // Stamp time
  const timeEl = clone.querySelector('.msg-time');
  if (timeEl) timeEl.textContent = timeNow();

  chatContainer.appendChild(clone);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return clone;
}

// --- 3. SEND MESSAGE ---
async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message) return;

  displayMessage(userMessageTemplate, message, true);
  messageInput.value = '';

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
      body: JSON.stringify({ message, collection_name: currentCollectionName, history: [] })
    });

    chatContainer.removeChild(typingClone);

    if (!response.ok) throw new Error('Network response was not ok');
    const data = await response.json();
    displayMessage(botMessageTemplate, data.answer);

  } catch (error) {
    if (chatContainer.contains(typingClone)) chatContainer.removeChild(typingClone);
    displayMessage(botMessageTemplate, "Sorry, I couldn't reach the server.");
    console.error(error);
  }
}

// --- 4. MICROPHONE LOGIC ---
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
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); sendMessage(); }
});
