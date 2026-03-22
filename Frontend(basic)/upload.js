// upload.js — PDF upload logic for KIIT Professor Finder

document.addEventListener('DOMContentLoaded', () => {

  // ── FETCH USER INFO ────────────────────────────────────────
  fetch('/user_info')
    .then(r => r.json())
    .then(data => {
      if (data.name) {
        const welcome = document.getElementById('user-welcome');
        if (welcome) welcome.textContent = `Welcome, ${data.name}`;

        const avatar   = document.getElementById('user-avatar');
        const dropdown = document.getElementById('profile-dropdown');

        if (avatar && data.picture) {
          avatar.src = data.picture;
          avatar.classList.remove('hidden');

          avatar.addEventListener('click', e => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
          });

          document.addEventListener('click', () => {
            dropdown.classList.add('hidden');
          });
        }
      }
    })
    .catch(() => {});

  const pdfInput        = document.getElementById('pdf-input');
  const uploadBtn       = document.getElementById('upload-btn');
  const statusMessage   = document.getElementById('status-message');
  const fileNameDisplay = document.getElementById('file-name-display');
  const loadingWidget   = document.getElementById('loading-widget');

  if (!pdfInput || !uploadBtn) return;

  pdfInput.addEventListener('change', () => {
    if (pdfInput.files.length > 0) {
      fileNameDisplay.textContent = pdfInput.files[0].name;
      if (statusMessage) statusMessage.textContent = '';
    }
  });

  const pollProcessingStatus = (collectionName) => {
    const intervalId = setInterval(async () => {
      try {
        const res  = await fetch(`/status/${collectionName}`);
        const data = await res.json();

        if (data.status === 'completed') {
          clearInterval(intervalId);
          window.location.href = '/chat';
        } else if (data.status === 'failed') {
          clearInterval(intervalId);
          loadingWidget.classList.add('hidden');
          if (statusMessage) statusMessage.textContent = 'Processing failed on server.';
          uploadBtn.disabled = false;
        }
      } catch (err) {
        console.error('Polling error:', err);
      }
    }, 2000);
  };

  uploadBtn.addEventListener('click', async () => {
    const file = pdfInput.files[0];
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      if (statusMessage) statusMessage.textContent = 'Please select a valid PDF.';
      return;
    }

    uploadBtn.disabled = true;
    if (statusMessage) statusMessage.textContent = 'Uploading...';

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/upload-pdf/', { method: 'POST', body: formData });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Upload failed');
      }

      const data = await response.json();

      sessionStorage.setItem('activeCollectionName', data.collection_name);
      sessionStorage.setItem('activeFileName', file.name);

      loadingWidget.classList.remove('hidden');
      pollProcessingStatus(data.collection_name);

    } catch (error) {
      if (statusMessage) statusMessage.textContent = `Error: ${error.message}`;
      uploadBtn.disabled = false;
    }
  });

});
