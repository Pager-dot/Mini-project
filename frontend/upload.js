/**
 * upload.js — PDF upload page logic.
 *
 * Handles user info display (welcome message + avatar dropdown),
 * PDF file selection & validation, upload to /upload-pdf/, and
 * polling /status/{collectionName} until processing completes or fails.
 */

document.addEventListener('DOMContentLoaded', () => {

    // --- Fetch user info and set up profile display / dropdown ---
    fetch('/user_info')
        .then(response => response.json())
        .then(data => {
            if (data.name) {
                document.getElementById('user-welcome').textContent = `Welcome, ${data.name}`;

                const avatar = document.getElementById('user-avatar');
                const dropdown = document.getElementById('profile-dropdown');

                if (data.picture) {
                    avatar.src = data.picture;
                    avatar.classList.remove('hidden');

                    // Toggle dropdown visibility on avatar click.
                    avatar.addEventListener('click', (e) => {
                        e.stopPropagation();
                        dropdown.classList.toggle('show');
                    });

                    // Close dropdown when clicking anywhere else on the page.
                    document.addEventListener('click', () => {
                        dropdown.classList.remove('show');
                    });
                }
            }
        })
        .catch(() => console.log("Not logged in"));

    const pdfInput = document.getElementById('pdf-input');
    const uploadBtn = document.getElementById('upload-btn');
    const statusMessage = document.getElementById('status-message');
    const fileNameDisplay = document.getElementById('file-name-display');
    const loadingWidget = document.getElementById('loading-widget');

    if (!pdfInput || !uploadBtn) return;

    // Update the displayed filename when the user selects a PDF.
    pdfInput.addEventListener('change', () => {
        if (pdfInput.files.length > 0) {
            fileNameDisplay.textContent = pdfInput.files[0].name;
            statusMessage.textContent = '';
        }
    });



    // --- Status Polling ---
    // Poll /status/{collectionName} every 2 seconds.
    // On "completed" → redirect to chat page. On "failed" → show error and re-enable upload.
    const pollProcessingStatus = async (collectionName) => {
        const intervalId = setInterval(async () => {
            try {
                const res = await fetch(`/status/${collectionName}`);
                const data = await res.json();

                if (data.status === 'completed') {
                    clearInterval(intervalId);
                    window.location.href = '/chat'; // Redirect to Chat
                } else if (data.status === 'failed') {
                    clearInterval(intervalId);
                    loadingWidget.classList.add('hidden'); // Hide loader
                    statusMessage.textContent = "❌ Processing Failed on Server.";
                    uploadBtn.disabled = false;
                }
            } catch (error) {
                console.error("Polling error:", error);
            }
        }, 2000); // Check every 2 seconds
    };

    // --- Upload Button Handler ---
    // Validate PDF selection, upload to /upload-pdf/, store the returned collection
    // name and filename in sessionStorage, show loading widget, and start polling.
    uploadBtn.addEventListener('click', async () => {
        const file = pdfInput.files[0];
        if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
            statusMessage.textContent = '⚠️ Please select a valid PDF.';
            return;
        }

        uploadBtn.disabled = true;
        statusMessage.textContent = 'Uploading...';

        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await fetch('/upload-pdf/', { method: 'POST', body: formData });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Upload failed');
            }

            const data = await response.json();

            // Store session data
            sessionStorage.setItem('activeCollectionName', data.collection_name);
            sessionStorage.setItem('activeFileName', file.name);

            // SHOW LOADING WIDGET & START POLLING
            loadingWidget.classList.remove('hidden');
            pollProcessingStatus(data.collection_name);

        } catch (error) {
            statusMessage.textContent = `⚠️ Error: ${error.message}`;
            uploadBtn.disabled = false;
        }
    });
});