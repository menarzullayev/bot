document.addEventListener('DOMContentLoaded', function() {
    // DOM elementlari
    const chatForm = document.getElementById('chat-form');
    const messageInput = document.getElementById('message-input');
    const chatMessages = document.getElementById('chat-messages');
    const fileInput = document.getElementById('file-input');
    const fileLabel = document.getElementById('file-label');
    const uploadedFilesContainer = document.getElementById('uploaded-files');
    const clearHistoryBtn = document.getElementById('clear-history');
    
    let files = [];
    
    // Dars jadvali kunlarini boshqarish
    function setupScheduleDays() {
        const dayElements = document.querySelectorAll('.schedule-day');
        
        if (dayElements.length > 0) {
            // Faqat birinchi kuni ko'rsatamiz
            dayElements[0].classList.add('active');
            
            // Kunlarni almashtirish logikasi
            // (kelajakda implement qilinadi)
        }
    }
    
    // Topshiriqlarni boshqarish
    function setupTasks() {
        const completeButtons = document.querySelectorAll('.task-complete');
        
        completeButtons.forEach(button => {
            button.addEventListener('click', function() {
                const taskItem = this.closest('.task-item');
                taskItem.style.opacity = '0.6';
                this.innerHTML = '<i class="fas fa-check"></i> Bajarildi';
                this.disabled = true;
                
                // Bu yerda backendga topshiriq bajarilganligi haqida xabar yuborish mumkin
            });
        });
    }
    
    // Fayl tanlanganda
    fileInput.addEventListener('change', function(e) {
        files = Array.from(e.target.files);
        updateFilePreviews();
    });
    
    // Fayl ko'rinishlarini yangilash
    function updateFilePreviews() {
        uploadedFilesContainer.innerHTML = '';
        
        if (files.length === 0) {
            uploadedFilesContainer.style.display = 'none';
            return;
        }
        
        uploadedFilesContainer.style.display = 'flex';
        
        files.forEach((file, index) => {
            const filePreview = document.createElement('div');
            filePreview.className = 'file-preview';
            
            const icon = getFileIcon(file);
            const size = formatFileSize(file.size);
            
            filePreview.innerHTML = `
                <span class="file-icon">${icon}</span>
                <span class="file-name">${file.name}</span>
                <span class="file-size">${size}</span>
                <span class="remove-file" data-index="${index}" title="O'chirish">
                    <i class="fas fa-times"></i>
                </span>
            `;
            
            uploadedFilesContainer.appendChild(filePreview);
        });
        
        // Fayllarni o'chirish
        document.querySelectorAll('.remove-file').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.getAttribute('data-index'));
                files.splice(index, 1);
                updateFilePreviews();
            });
        });
    }
    
    // Fayl turi bo'yicha icon olish
    function getFileIcon(file) {
        const fileType = file.type.split('/')[0];
        const fileExtension = file.name.split('.').pop().toLowerCase();
        
        const fileIcons = {
            'image': '<i class="fas fa-image"></i>',
            'application': file.type.includes('pdf') ? '<i class="fas fa-file-pdf"></i>' : 
                          (file.type.includes('word') || file.type.includes('document')) ? '<i class="fas fa-file-word"></i>' : 
                          (file.type.includes('zip') || file.type.includes('compressed')) ? '<i class="fas fa-file-archive"></i>' : 
                          '<i class="fas fa-file"></i>',
            'text': '<i class="fas fa-file-alt"></i>',
            'video': '<i class="fas fa-file-video"></i>',
            'audio': '<i class="fas fa-file-audio"></i>'
        };
        
        const extensionIcons = {
            'py': '<i class="fab fa-python"></i>',
            'js': '<i class="fab fa-js-square"></i>',
            'java': '<i class="fab fa-java"></i>',
            'cpp': '<i class="fas fa-file-code"></i>',
            'csv': '<i class="fas fa-file-csv"></i>',
            'xls': '<i class="fas fa-file-excel"></i>',
            'xlsx': '<i class="fas fa-file-excel"></i>'
        };
        
        return extensionIcons[fileExtension] || fileIcons[fileType] || '<i class="fas fa-file"></i>';
    }
    
    // Fayl hajmini formatlash
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }
    
    // Xabar yuborish
    chatForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const message = messageInput.value.trim();
        if (!message && files.length === 0) return;
        
        // Foydalanuvchi xabarini ko'rsatish
        displayMessage(message, files, 'user');
        
        // FormData yaratish
        const formData = new FormData();
        formData.append('message', message);
        
        files.forEach(file => {
            formData.append('files', file);
        });
        
        try {
            // Serverga so'rov yuborish
            const response = await fetch('/send_message', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.error) {
                displayMessage(data.error, [], 'bot');
            } else {
                displayMessage(data.message, data.files || [], 'bot');
                
                // Fayl kontentlarini ko'rsatish
                if (data.file_contents && data.file_contents.length > 0) {
                    data.file_contents.forEach((content, index) => {
                        if (content && content.trim() !== '') {
                            displayMessage(
                                `Fayl tarkibi (${data.files[index]}):\n${content}`,
                                [], 
                                'bot'
                            );
                        }
                    });
                }
            }
        } catch (error) {
            displayMessage('Xatolik yuz berdi: ' + error.message, [], 'bot');
        }
        
        // Inputlarni tozalash
        messageInput.value = '';
        files = [];
        fileInput.value = '';
        updateFilePreviews();
    });
    
    // Xabarlarni ekranga chiqarish
    function displayMessage(text, attachedFiles, sender) {
        const messageElement = document.createElement('div');
        messageElement.className = `message ${sender}`;
        
        let filesHTML = '';
        if (attachedFiles && attachedFiles.length > 0) {
            filesHTML = '<div class="message-files">';
            attachedFiles.forEach(file => {
                let icon = '';
                let preview = '';
                
                if (typeof file === 'string') {
                    // Server response file (string)
                    const ext = file.split('.').pop().toLowerCase();
                    if (['png', 'jpg', 'jpeg', 'gif'].includes(ext)) {
                        icon = '<i class="fas fa-image"></i>';
                        preview = `<img src="/uploads/${file}" alt="Rasm" loading="lazy">`;
                    } else if (ext === 'pdf') {
                        icon = '<i class="fas fa-file-pdf"></i>';
                    } else if (['doc', 'docx'].includes(ext)) {
                        icon = '<i class="fas fa-file-word"></i>';
                    } else {
                        icon = '<i class="fas fa-file"></i>';
                    }
                    
                    filesHTML += `
                        <div class="message-file">
                            <span class="file-icon">${icon}</span>
                            <span class="file-name">${file}</span>
                            ${preview}
                        </div>
                    `;
                } else {
                    // User uploaded file (object)
                    if (file.type.startsWith('image/')) {
                        icon = '<i class="fas fa-image"></i>';
                        const reader = new FileReader();
                        reader.onload = function(e) {
                            const img = document.createElement('img');
                            img.src =