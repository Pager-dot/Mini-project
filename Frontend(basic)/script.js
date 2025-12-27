const chatContainer = document.getElementById('chat-container');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const voiceBtn = document.getElementById('voice-btn');

const userMessageTemplate = document.getElementById('user-message-template');
const botMessageTemplate = document.getElementById('bot-message-template');
const typingIndicatorTemplate = document.getElementById('typing-indicator-template');

let currentCollectionName = sessionStorage.getItem('activeCollectionName') || null;

// --- 1. FETCH USER INFO ---
document.addEventListener('DOMContentLoaded', () => {
    fetch('/user_info')
        .then(response => response.json())
        .then(data => {
            if (data.name) {
                // Update Name in Header
                const nameDisplay = document.getElementById('user-name');
                if(nameDisplay) nameDisplay.textContent = data.name;

                // Update Avatar
                if (data.picture) {
                    const avatar = document.getElementById('chat-user-avatar');
                    if (avatar) avatar.src = data.picture;
                }
            }
        })
        .catch(() => console.log("Not logged in (Guest Mode)"));
});

// --- 2. DISPLAY MESSAGE ---
function displayMessage(template, text, isUser = false) {
    const clone = template.cloneNode(true);
    clone.removeAttribute('id');
    clone.classList.remove('hidden'); // Remove hidden class
    
    // Find text container
    const textContainer = clone.querySelector('p');
    
    if (isUser) {
        textContainer.textContent = text;
    } else {
        // Parse Markdown for bot
        textContainer.innerHTML = marked.parse(text);
    }
    
    chatContainer.appendChild(clone);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return clone;
}

// --- 3. SEND MESSAGE ---
async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;

    // Show User Message
    displayMessage(userMessageTemplate, message, true);
    messageInput.value = '';

    // Show Typing Indicator
    const typingClone = typingIndicatorTemplate.cloneNode(true);
    typingClone.removeAttribute('id');
    typingClone.classList.remove('hidden');
    chatContainer.appendChild(typingClone);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                collection_name: currentCollectionName, 
                history: [] 
            })
        });

        // Remove Typing Indicator
        chatContainer.removeChild(typingClone);

        if (!response.ok) throw new Error('Network response was not ok');
        
        const data = await response.json();
        displayMessage(botMessageTemplate, data.answer);

    } catch (error) {
        if(chatContainer.contains(typingClone)) chatContainer.removeChild(typingClone);
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
        voiceBtn.style.color = '#9ca3af'; // Reset color
        isRecording = false;
        if (mediaRecorder) mediaRecorder.stop();
    } else {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
            
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                stream.getTracks().forEach(track => track.stop()); // Stop mic
                
                const formData = new FormData();
                formData.append("audio_file", audioBlob, "recording.webm");
                
                // Show temp message
                const loadingMsg = displayMessage(botMessageTemplate, "*Transcribing audio...*");
                
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
            voiceBtn.style.color = '#ef4444'; // Red
            isRecording = true;
        } catch (error) {
            console.error(error);
            alert("Microphone access denied.");
        }
    }
});

// --- 5. EVENT LISTENERS ---
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        sendMessage();
    }
});