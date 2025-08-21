// --- Seletores de Elementos DOM ---
const bodyEl = document.body;
const themeToggle = document.getElementById('theme-checkbox');
const apiStatusIndicatorEl = document.getElementById('apiStatusIndicator');
const isLoggedIn = bodyEl.dataset.isLoggedIn === 'true';

// --- Seletores da App Principal ---
const mainAppWrapper = document.getElementById('mainAppWrapper');
const wizardSteps = document.querySelectorAll('.wizard-step');
const originalEmailEl = document.getElementById('originalEmail');
const analyzeBtn = document.getElementById('analyzeBtn');
const analyzeSpinner = document.getElementById('analyzeSpinner');
const analyzeErrorEl = document.getElementById('analyzeError');
const analysisResultEl = document.getElementById('analysisResult');
const userInputsContainer = document.getElementById('userInputsContainer');
const userInputsSection = document.getElementById('userInputsSection');
const personaSelect = document.getElementById('personaSelect');
const draftBtn = document.getElementById('draftBtn');
const draftSpinner = document.getElementById('draftSpinner');
const draftErrorEl = document.getElementById('draftError');
const generatedDraftEl = document.getElementById('generatedDraft');
const copyDraftBtn = document.getElementById('copyDraftBtn');
const contextInfoEl = document.getElementById('contextInfo');
const contextDetailsEl = document.getElementById('contextDetails');
const refinementControlsEl = document.getElementById('refinementControls');
const feedbackBtn = document.getElementById('feedbackBtn');
const feedbackSuccessMessageEl = document.getElementById('feedbackSuccessMessage');
const fetchEmailsBtn = document.getElementById('fetchEmailsBtn');
const emailListEl = document.getElementById('emailList');
const gmailSpinnerEl = document.getElementById('gmailSpinner');
const gmailErrorEl = document.getElementById('gmailError');
const sendEmailBtn = document.getElementById('sendEmailBtn');
const sendEmailSpinner = document.getElementById('sendEmailSpinner');
const sendEmailSuccessMessageEl = document.getElementById('sendEmailSuccessMessage');
const sendEmailErrorEl = document.getElementById('sendEmailError');
const backToAnalysisBtn = document.getElementById('backToAnalysisBtn');
const backToSelectBtn = document.getElementById('backToSelectBtn');
const progressSteps = document.querySelectorAll('.progress-step');

// --- Seletores para Modais ---
const feedbackModalEl = document.getElementById('feedbackModal');
const feedbackOriginalResponseEl = document.getElementById('feedbackOriginalResponse');
const feedbackUserCorrectionEl = document.getElementById('feedbackUserCorrection');
const feedbackErrorModalEl = document.getElementById('feedbackErrorModal');
const feedbackSubmitSpinner = document.getElementById('feedbackSubmitSpinner');
const sendEmailConfirmModalEl = document.getElementById('sendEmailConfirmModal');
const confirmRecipientEl = document.getElementById('confirmRecipient');
const confirmSubjectEl = document.getElementById('confirmSubject');
const confirmBodyPreviewEl = document.getElementById('confirmBodyPreview');
const confirmSendBtn = document.getElementById('confirmSendBtn');
const cancelSendBtn = document.getElementById('cancelSendBtn');
const personaFormModalEl = document.getElementById('personaFormModal');
const deletePersonaConfirmModalEl = document.getElementById('deletePersonaConfirmModal');

// --- Seletores para Gestão de Personas ---
const createPersonaBtn = document.getElementById('createPersonaBtn');
const personasTableBody = document.getElementById('personasTableBody');
const personaFormModalLabel = document.getElementById('personaFormModalLabel');
const personaForm = document.getElementById('personaForm');
const personaKeyInput = document.getElementById('personaKeyInput');
const personaLabelInput = document.getElementById('personaLabelInput');
const personaDescriptionInput = document.getElementById('personaDescriptionInput');
const savePersonaBtn = document.getElementById('savePersonaBtn');
const savePersonaSpinner = document.getElementById('savePersonaSpinner');
const personaFormError = document.getElementById('personaFormError');
const personaListError = document.getElementById('personaListError');
const personaToDeleteNameEl = document.getElementById('personaToDeleteName');
const confirmDeletePersonaBtn = document.getElementById('confirmDeletePersonaBtn');
const deletePersonaSpinner = document.getElementById('deletePersonaSpinner');
const currentPersonaKeyInput = document.getElementById('currentPersonaKey');

// --- Seletores para Gestão de Memória ---
const memoryManagementModalEl = document.getElementById('memoryManagementModal');
const memoryPersonaNameEl = document.getElementById('memoryPersonaName');
const memoryFormTitleEl = document.getElementById('memoryFormTitle');
const memoryForm = document.getElementById('memoryForm');
const memoryFormErrorEl = document.getElementById('memoryFormError');
const currentMemoryIdInput = document.getElementById('currentMemoryId');
const currentMemoryPersonaKeyInput = document.getElementById('currentMemoryPersonaKey');
const memoryContentInput = document.getElementById('memoryContentInput');
const memoryTypeSelect = document.getElementById('memoryTypeSelect');
const memoryTriggersInput = document.getElementById('memoryTriggersInput');
const saveMemoryBtn = document.getElementById('saveMemoryBtn');
const saveMemorySpinner = document.getElementById('saveMemorySpinner');
const cancelEditMemoryBtn = document.getElementById('cancelEditMemoryBtn');
const memoryListErrorEl = document.getElementById('memoryListError');
const memoryTableBody = document.getElementById('memoryTableBody');
const manageBaseMemoryBtn = document.getElementById('manageBaseMemoryBtn');

// --- Seletores para Dashboard ---
const navButtons = document.querySelectorAll('.nav-btn');
const views = document.querySelectorAll('.view');
const draftsTableBody = document.getElementById('draftsTableBody');
const statusChartCanvas = document.getElementById('statusChart');
const kpiValues = document.querySelectorAll('.kpi-value');
const chartCenterMetric = document.getElementById('chartCenterMetric');

// --- Instâncias de Modais ---
let feedbackModalInstance = null;
let sendEmailConfirmModalInstance = null;
let personaFormModalInstance = null;
let deletePersonaConfirmModalInstance = null;
let memoryManagementModalInstance = null;

// --- Estado da Aplicação ---
let currentStep = 1;
let currentAnalysisPoints = [];
let isRefining = false;
let currentDraftContext = {};
let lastGeneratedDraftForFeedback = "";
let currentOriginalSenderEmail = "";
let currentOriginalSubject = "";
let currentThreadId = "";
let resolveSendConfirmation;
let personaToDeleteKey = null;
let statusChart = null;
let currentView = 'dashboard';

// --- Funções Auxiliares ---
function showSpinner(spinner) { if (spinner) spinner.style.display = 'inline-block'; }
function hideSpinner(spinner) { if (spinner) spinner.style.display = 'none'; }
function showError(element, message) {
    if (!element) return;
    element.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i> ${message}`;
    element.style.display = 'block';
}
function hideError(element) { if (element) { element.textContent = ''; element.style.display = 'none'; } }
function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return '';
    return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
function showSuccessMessage(element, message, duration = 4000) {
    if (!element) return;
    element.innerHTML = `<i class="fas fa-check-circle me-2"></i> ${message}`;
    element.style.display = 'block';
    setTimeout(() => {
        element.style.display = 'none';
    }, duration);
}

// --- Lógica de Tema (Dark/Light Mode) ---
function applyTheme(theme) {
    document.body.className = theme === 'light' ? 'light-mode' : 'dark-mode';
    if (themeToggle) themeToggle.checked = (theme === 'dark');
}

// --- Lógica Principal da Aplicação ---
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('themePreference') || 'dark';
    applyTheme(savedTheme);
    if (themeToggle) {
        themeToggle.addEventListener('change', () => {
            const newTheme = themeToggle.checked ? 'dark' : 'light';
            applyTheme(newTheme);
            localStorage.setItem('themePreference', newTheme);
        });
    }
    if (isLoggedIn) {
        initializeMainApp();
        fetchDashboardData();  // Load dashboard data on start
    }

    // View Switching
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            navButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentView = btn.dataset.view;
            views.forEach(view => view.classList.toggle('active', view.id === `${currentView}-view`));
            if (currentView === 'dashboard') fetchDashboardData();
            if (currentView === 'manual') showStep(1);
        });
    });
});

function initializeMainApp() {
    // Inicialização dos Modais
    if (feedbackModalEl) feedbackModalInstance = new bootstrap.Modal(feedbackModalEl);
    if (sendEmailConfirmModalEl) sendEmailConfirmModalInstance = new bootstrap.Modal(sendEmailConfirmModalEl);
    if (personaFormModalEl) personaFormModalInstance = new bootstrap.Modal(personaFormModalEl);
    if (deletePersonaConfirmModalEl) deletePersonaConfirmModalInstance = new bootstrap.Modal(deletePersonaConfirmModalEl);
    if (memoryManagementModalEl) memoryManagementModalInstance = new bootstrap.Modal(memoryManagementModalEl);

    // Adiciona Event Listeners
    analyzeBtn.addEventListener('click', handleAnalysisAndAdvance);
    draftBtn.addEventListener('click', handleDrafting);
    copyDraftBtn.addEventListener('click', handleCopy);
    userInputsSection.addEventListener('click', handleGuidanceSuggestion);
    generatedDraftEl.addEventListener('select', handleTextSelection);
    generatedDraftEl.addEventListener('mouseup', handleTextSelection);
    document.addEventListener('click', handleDeselection);
    refinementControlsEl.addEventListener('click', handleRefinement);
    feedbackBtn.addEventListener('click', openFeedbackModal);
    document.getElementById('submitFeedbackBtn').addEventListener('click', submitFeedback);
    fetchEmailsBtn.addEventListener('click', fetchAndRenderEmails);
    emailListEl.addEventListener('click', handleEmailClick);
    sendEmailBtn.addEventListener('click', handleSendEmail);
    backToSelectBtn.addEventListener('click', () => showStep(1));
    backToAnalysisBtn.addEventListener('click', () => showStep(2));
    document.getElementById('progress-step-4').addEventListener('click', () => showStep(4));
    document.getElementById('backToMainFlowBtn').addEventListener('click', () => showStep(1));
    originalEmailEl.addEventListener('input', () => {
        analyzeBtn.disabled = originalEmailEl.value.trim() === '';
    });
    confirmSendBtn.addEventListener('click', () => {
        if (resolveSendConfirmation) resolveSendConfirmation(true);
    });
    cancelSendBtn.addEventListener('click', () => {
        if (resolveSendConfirmation) resolveSendConfirmation(false);
    });
    createPersonaBtn.addEventListener('click', openCreatePersonaModal);
    personaForm.addEventListener('submit', submitPersonaForm);
    personasTableBody.addEventListener('click', handlePersonaTableClick);
    confirmDeletePersonaBtn.addEventListener('click', deletePersona);

    // Event Listeners para Gestão de Memória
    memoryForm.addEventListener('submit', handleMemoryFormSubmit);
    cancelEditMemoryBtn.addEventListener('click', clearMemoryForm);
    memoryTableBody.addEventListener('click', handleMemoryTableClick);
    
    manageBaseMemoryBtn.addEventListener('click', openBaseMemoryManagementModal);

    // Draft Actions for Dashboard
    draftsTableBody.addEventListener('click', handleDraftAction);

    // Funções de inicialização for Manual Flow
    showStep(1);
    fetchAndRenderEmails();
    fetchAndRenderPersonas();
    populatePersonaSelect();
}

function showStep(stepNumber) {
    currentStep = stepNumber;
    wizardSteps.forEach(step => step.classList.remove('active-step'));
    document.getElementById(`step-${stepNumber}`).classList.add('active-step');
    progressSteps.forEach((step, index) => {
        step.classList.toggle('active', index + 1 === stepNumber);
        step.classList.toggle('completed', index + 1 < stepNumber);
    });
}

async function fetchAndRenderEmails() {
    showSpinner(gmailSpinnerEl);
    hideError(gmailErrorEl);
    emailListEl.innerHTML = '<li class="list-group-item text-secondary">A carregar emails...</li>';
    try {
        const response = await fetch('/api/emails');
        if (!response.ok) throw new Error(`Erro: ${response.statusText}`);
        const emails = await response.json();
        emailListEl.innerHTML = '';
        if (emails.error) throw new Error(emails.error);
        if (emails.length === 0) {
            emailListEl.innerHTML = '<li class="list-group-item text-secondary">Nenhum email encontrado.</li>';
            return;
        }
        emails.forEach(email => {
            const li = document.createElement('li');
            li.className = 'list-group-item email-list-item';
            li.dataset.threadId = email.threadId;
            li.innerHTML = `
                <span class="email-sender">${escapeHtml(email.sender.replace(/<.*?>/g, ''))}</span>
                <span class="email-subject">${escapeHtml(email.subject)}</span>
                <span class="email-snippet">${escapeHtml(email.snippet)}</span>
            `;
            emailListEl.appendChild(li);
        });
    } catch (error) {
        showError(gmailErrorEl, error.message);
    } finally {
        hideSpinner(gmailSpinnerEl);
    }
}

async function handleEmailClick(event) {
    const listItem = event.target.closest('.email-list-item');
    if (!listItem) return;
    document.querySelectorAll('.email-list-item.active').forEach(item => item.classList.remove('active'));
    listItem.classList.add('active');
    const threadId = listItem.dataset.threadId;
    originalEmailEl.value = `A carregar a conversa (Thread ID: ${threadId})...`;
    analyzeBtn.disabled = true;
    try {
        const response = await fetch(`/api/thread/${threadId}`);
        if (!response.ok) throw new Error('Falha ao carregar a thread.');
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        originalEmailEl.value = data.thread_text;
        currentOriginalSenderEmail = data.original_sender_email;
        currentOriginalSubject = data.original_subject;
        currentThreadId = threadId;
        analyzeBtn.disabled = false;
    } catch (error) {
        showError(analyzeErrorEl, error.message);
        originalEmailEl.value = '';
    }
}

async function handleAnalysisAndAdvance() {
    const emailText = originalEmailEl.value.trim();
    if (!emailText) {
        showError(analyzeErrorEl, "Por favor, insira o texto do email.");
        return;
    }
    showSpinner(analyzeSpinner);
    hideError(analyzeErrorEl);
    analyzeBtn.disabled = true;
    try {
        const response = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email_text: emailText })
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `Erro HTTP ${response.status}`);
        currentAnalysisPoints = data.points || [];
        displayAnalysisResults(data);
        createUserInputFields(currentAnalysisPoints);
        showStep(2);
    } catch (error) {
        showError(analyzeErrorEl, `Erro na análise: ${error.message}`);
    } finally {
        hideSpinner(analyzeSpinner);
        analyzeBtn.disabled = false;
    }
}

function displayAnalysisResults(data) {
    let html = '<h4>Pontos de Ação Identificados:</h4>';
    if (data.points && data.points.length > 0) {
        html += '<ol class="list-group list-group-numbered list-group-flush mb-3">';
        data.points.forEach(point => { html += `<li class="list-group-item">${escapeHtml(point)}</li>`; });
        html += '</ol>';
    } else {
        html += '<p class="text-secondary fst-italic">Nenhum ponto específico identificado.</p>';
    }
    analysisResultEl.innerHTML = html;
}

function createUserInputFields(points) {
    userInputsSection.innerHTML = '';
    const createGroup = (point, index, isGeneral = false) => {
        const div = document.createElement('div');
        div.className = 'point-input-group';
        const inputId = isGeneral ? 'userInput-general' : `userInput-${index}`;
        const pointIdentifier = isGeneral ? "N/A" : (point || "N/A");
        const labelText = isGeneral ? '<strong>Diretriz Geral:</strong> <span class="form-label-sm">(Opcional - instrução global para este rascunho)</span>' : `<strong>Ponto ${index + 1}:</strong>`;
        const pointDisplay = !isGeneral ? `<p class="point-text">"${escapeHtml(point)}"</p>` : '';
        
        const directionRadiosHTML = !isGeneral ? `<div class="mb-2 guidance-direction-group"><span class="form-label-sm d-block mb-1">Vetor de Resposta Rápida:</span><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-sim" value="sim"><label class="form-check-label" for="direction-${index}-sim">Afirmativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-nao" value="nao"><label class="form-check-label" for="direction-${index}-nao">Negativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-outro" value="outro" checked><label class="form-check-label" for="direction-${index}-outro">Detalhado</label></div></div>` : '';
        const suggestButtonHTML = !isGeneral ? `<button class="btn btn-sm btn-outline-secondary suggest-btn" data-target-textarea="${inputId}" data-point-index="${index}" type="button" title="Gerar sugestão de diretriz via IA, usando o Vetor de Resposta">Sugerir Diretriz<div class="spinner-border spinner-border-sm loading-spinner" role="status" style="display: none;"></div></button>` : '';
        
        div.innerHTML = `<div class="d-flex justify-content-between align-items-start mb-1 flex-wrap"><label for="${inputId}" class="form-label mb-0 me-2">${labelText}</label>${suggestButtonHTML}</div>${pointDisplay}${directionRadiosHTML}<textarea class="form-control user-guidance" id="${inputId}" data-point="${escapeHtml(pointIdentifier)}" rows="3" placeholder="Insira a sua diretriz para este ponto..."></textarea>`;
        userInputsSection.appendChild(div);
    };

    const hasRealPoints = points && points.length > 0 && !(points.length === 1 && points[0].toLowerCase().includes("nenhum ponto"));
    if (hasRealPoints) {
        points.forEach((point, index) => createGroup(point, index, false));
    }
    createGroup(null, 'general', true);
}

async function handleDrafting() {
    const originalEmail = originalEmailEl.value.trim();
    const selectedPersona = personaSelect.value;
    const userInputsData = Array.from(userInputsSection.querySelectorAll('.user-guidance')).map(input => ({
        point: input.getAttribute('data-point'),
        guidance: input.value.trim()
    })).filter(item => item.guidance);

    if (!selectedPersona) {
        showError(draftErrorEl, "Por favor, selecione uma persona.");
        return;
    }
    showSpinner(draftSpinner);
    hideError(draftErrorEl);
    draftBtn.disabled = true;
    try {
        const response = await fetch('/draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ original_email: originalEmail, persona_name: selectedPersona, user_inputs: userInputsData })
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `Erro HTTP ${response.status}`);
        generatedDraftEl.value = data.draft || "";
        lastGeneratedDraftForFeedback = data.draft || "";
        feedbackBtn.disabled = !lastGeneratedDraftForFeedback;
        sendEmailBtn.disabled = !lastGeneratedDraftForFeedback;
        showStep(3);
    } catch (error) {
        showError(draftErrorEl, `Erro na geração: ${error.message}`);
    } finally {
        hideSpinner(draftSpinner);
        draftBtn.disabled = false;
    }
}

function handleCopy() {
    navigator.clipboard.writeText(generatedDraftEl.value).then(() => {
        copyDraftBtn.innerHTML = '<i class="fas fa-check"></i> Copiado!';
        setTimeout(() => { copyDraftBtn.innerHTML = '<i class="fas fa-copy"></i> Copiar'; }, 2000);
    });
}

function handleTextSelection() {
    refinementControlsEl.style.display = generatedDraftEl.selectionStart !== generatedDraftEl.selectionEnd ? 'flex' : 'none';
}

function handleDeselection(event) {
    if (!generatedDraftEl.contains(event.target) && !refinementControlsEl.contains(event.target)) {
        refinementControlsEl.style.display = 'none';
    }
}

async function handleRefinement(event) {
    const button = event.target.closest('.refine-btn');
    if (button && !isRefining) {
        const action = button.dataset.action;
        const spinner = button.querySelector('.loading-spinner');
        const selectedText = generatedDraftEl.value.substring(generatedDraftEl.selectionStart, generatedDraftEl.selectionEnd);
        const fullContext = generatedDraftEl.value;
        const selectedPersonaName = personaSelect.value;
        const start = generatedDraftEl.selectionStart;
        const end = generatedDraftEl.selectionEnd;

        if (!selectedText) {
            refinementControlsEl.style.display = 'none';
            return;
        }
        if (!selectedPersonaName) {
            showError(draftErrorEl, "Selecione uma persona para o refinamento.");
            return;
        }

        isRefining = true;
        if (spinner) showSpinner(spinner);
        refinementControlsEl.querySelectorAll('.refine-btn').forEach(btn => btn.disabled = true);
        hideError(draftErrorEl);

        try {
            const response = await fetch('/refine_text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    selected_text: selectedText,
                    full_context: fullContext,
                    action: action,
                    persona_name: selectedPersonaName
                })
            });
            const data = await response.json();
            if (!response.ok || data.error) { throw new Error(data.error || `Erro HTTP ${response.status}`); }

            const before = fullContext.substring(0, start);
            const after = fullContext.substring(end);
            const refinedText = data.refined_text || "";
            generatedDraftEl.value = before + refinedText + after;
            lastGeneratedDraftForFeedback = generatedDraftEl.value;
            generatedDraftEl.focus();
            const newCursorPos = start + refinedText.length;
            generatedDraftEl.setSelectionRange(newCursorPos, newCursorPos);
        } catch (error) {
            showError(draftErrorEl, `Erro no refinamento (${action}): ${error.message}`);
        } finally {
            if (spinner) hideSpinner(spinner);
            refinementControlsEl.querySelectorAll('.refine-btn').forEach(btn => btn.disabled = false);
            isRefining = false;
        }
    }
}

async function handleGuidanceSuggestion(event) {
    const button = event.target.closest('.suggest-btn');
    if (button && !button.disabled) {
        const spinner = button.querySelector('.loading-spinner');
        const targetTextareaId = button.dataset.targetTextarea;
        const pointIndex = parseInt(button.dataset.pointIndex, 10);
        const targetTextarea = document.getElementById(targetTextareaId);
        const originalEmail = originalEmailEl.value.trim();
        const selectedPersonaName = personaSelect.value;
        const radioGroupName = `direction-${pointIndex}`;
        const checkedRadio = userInputsSection.querySelector(`input[name="${radioGroupName}"]:checked`);
        const selectedDirection = checkedRadio ? checkedRadio.value : "outro";
        const pointToAddress = (currentAnalysisPoints && pointIndex >= 0 && pointIndex < currentAnalysisPoints.length) ? currentAnalysisPoints[pointIndex] : null;

        if (!targetTextarea || !originalEmail || !pointToAddress || !selectedPersonaName || pointToAddress === 'N/A') {
            showError(draftErrorEl, "Erro interno: Dados insuficientes para sugestão.");
            return;
        }
        if (spinner) showSpinner(spinner);
        button.disabled = true;
        hideError(draftErrorEl);

        try {
            const response = await fetch('/suggest_guidance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    original_email: originalEmail,
                    point_to_address: pointToAddress,
                    persona_name: selectedPersonaName,
                    direction: selectedDirection
                })
            });
            const data = await response.json();
            if (!response.ok || data.error) { throw new Error(data.error || `Erro HTTP ${response.status}`); }
            targetTextarea.value = data.suggestion || '';
            targetTextarea.dispatchEvent(new Event('input', { bubbles: true }));
        } catch (error) {
            showError(draftErrorEl, `Erro na sugestão: ${error.message}`);
        } finally {
            if (spinner) hideSpinner(spinner);
            button.disabled = false;
        }
    }
}

// --- Lógica de Feedback ---
function openFeedbackModal() {
    if (!lastGeneratedDraftForFeedback) {
        showError(draftErrorEl, "Não há rascunho para dar feedback.");
        return;
    }
    feedbackOriginalResponseEl.value = lastGeneratedDraftForFeedback;
    feedbackUserCorrectionEl.value = '';
    feedbackModalInstance.show();
}

async function submitFeedback() {
    const payload = {
        persona_name: personaSelect.value,
        ai_original_response: feedbackOriginalResponseEl.value,
        user_corrected_output: feedbackUserCorrectionEl.value.trim(),
        interaction_context: currentDraftContext
    };
    if (!payload.user_corrected_output) {
        showError(feedbackErrorModalEl, "Forneça a sua versão correta.");
        return;
    }
    showSpinner(feedbackSubmitSpinner);
    try {
        const response = await fetch('/submit_feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Erro no servidor.");
        feedbackModalInstance.hide();
        showSuccessMessage(feedbackSuccessMessageEl, `Feedback submetido! Nova regra: "${data.inferred_rule}"`);
    } catch (error) {
        showError(feedbackErrorModalEl, `Erro: ${error.message}`);
    } finally {
        hideSpinner(feedbackSubmitSpinner);
    }
}

// --- Lógica de Envio de Email ---
async function handleSendEmail() {
    const confirmation = await showSendEmailConfirmation(
        currentOriginalSenderEmail,
        `Re: ${currentOriginalSubject}`,
        generatedDraftEl.value.substring(0, 150) + "..."
    );
    if (!confirmation) return;
    showSpinner(sendEmailSpinner);
    try {
        const response = await fetch('/api/send_email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                recipient: currentOriginalSenderEmail,
                subject: `Re: ${currentOriginalSubject}`,
                body: generatedDraftEl.value,
                thread_id: currentThreadId
            })
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error);
        showSuccessMessage(sendEmailSuccessMessageEl, "Email enviado!");
    } catch (error) {
        showError(sendEmailErrorEl, `Erro ao enviar: ${error.message}`);
    } finally {
        hideSpinner(sendEmailSpinner);
    }
}

function showSendEmailConfirmation(recipient, subject, bodyPreview) {
    return new Promise(resolve => {
        resolveSendConfirmation = (confirmed) => {
            sendEmailConfirmModalInstance.hide();
            resolve(confirmed);
        };
        confirmRecipientEl.textContent = recipient;
        confirmSubjectEl.textContent = subject;
        confirmBodyPreviewEl.textContent = bodyPreview;
        sendEmailConfirmModalInstance.show();
    });
}

// --- Funções para Gestão de Personas ---
async function fetchAndRenderPersonas() {
    personasTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary">A carregar...</td></tr>';
    try {
        const response = await fetch('/api/personas');
        const personas = await response.json();
        personasTableBody.innerHTML = '';
        Object.entries(personas).forEach(([key, persona]) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(key)}</td>
                <td>${escapeHtml(persona.label || 'N/A')}</td>
                <td>${escapeHtml(persona.description || 'N/A')}</td>
                <td class="persona-actions">
                    <button class="btn btn-sm btn-info edit-persona-btn" data-persona-key="${escapeHtml(key)}" title="Editar Persona"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-sm btn-secondary manage-memory-btn" data-persona-key="${escapeHtml(key)}" data-persona-name="${escapeHtml(persona.label || key)}" title="Gerir Memória"><i class="fas fa-brain"></i></button>
                    <button class="btn btn-sm btn-danger delete-persona-btn" data-persona-key="${escapeHtml(key)}" data-persona-name="${escapeHtml(persona.label || key)}" title="Eliminar Persona"><i class="fas fa-trash-alt"></i></button>
                </td>
            `;
            personasTableBody.appendChild(tr);
        });
    } catch (error) {
        showError(personaListError, "Falha ao carregar personas.");
    }
}

async function populatePersonaSelect() {
    try {
        const response = await fetch('/api/personas');
        const personas = await response.json();
        personaSelect.innerHTML = '<option value="">Selecione uma persona...</option>';
        Object.entries(personas).forEach(([key, persona]) => {
            personaSelect.innerHTML += `<option value="${key}">${escapeHtml(persona.label)}</option>`;
        });
        personaSelect.disabled = false;
        draftBtn.disabled = false;
    } catch (error) {
        personaSelect.innerHTML = '<option value="">Erro ao carregar</option>';
    }
}

function openCreatePersonaModal() {
    personaForm.reset();
    currentPersonaKeyInput.value = '';
    personaKeyInput.disabled = false;
    personaFormModalLabel.textContent = 'Criar Nova Persona';
    personaFormModalInstance.show();
}

async function openEditPersonaModal(personaKey) {
    try {
        const response = await fetch(`/api/personas/${personaKey}`);
        const persona = await response.json();
        personaForm.reset();
        currentPersonaKeyInput.value = personaKey;
        personaKeyInput.value = personaKey;
        personaKeyInput.disabled = true;
        personaLabelInput.value = persona.label;
        personaDescriptionInput.value = persona.description;
        personaFormModalLabel.textContent = 'Editar Persona';
        personaFormModalInstance.show();
    } catch (error) {
        showError(personaListError, "Falha ao carregar dados da persona.");
    }
}

async function submitPersonaForm(event) {
    event.preventDefault();
    const isEditing = !!currentPersonaKeyInput.value;
    const key = isEditing ? currentPersonaKeyInput.value : personaKeyInput.value.trim();
    const payload = {
        label: personaLabelInput.value.trim(),
        description: personaDescriptionInput.value.trim()
    };
    const url = isEditing ? `/api/personas/${key}` : '/api/personas';
    const method = isEditing ? 'PUT' : 'POST';
    const body = isEditing ? JSON.stringify(payload) : JSON.stringify({ persona_key: key, persona_data: payload });

    showSpinner(savePersonaSpinner);
    try {
        const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        personaFormModalInstance.hide();
        fetchAndRenderPersonas();
        populatePersonaSelect();
    } catch (error) {
        showError(personaFormError, error.message);
    } finally {
        hideSpinner(savePersonaSpinner);
    }
}

function handlePersonaTableClick(event) {
    const editBtn = event.target.closest('.edit-persona-btn');
    const deleteBtn = event.target.closest('.delete-persona-btn');
    const memoryBtn = event.target.closest('.manage-memory-btn');

    if (editBtn) openEditPersonaModal(editBtn.dataset.personaKey);
    if (deleteBtn) confirmDeletePersona(deleteBtn.dataset.personaKey, deleteBtn.dataset.personaName);
    if (memoryBtn) openMemoryManagementModal(memoryBtn.dataset.personaKey, memoryBtn.dataset.personaName);
}

function confirmDeletePersona(key, name) {
    personaToDeleteKey = key;
    personaToDeleteNameEl.textContent = name;
    deletePersonaConfirmModalInstance.show();
}

async function deletePersona() {
    if (!personaToDeleteKey) return;
    showSpinner(deletePersonaSpinner);
    try {
        const response = await fetch(`/api/personas/${personaToDeleteKey}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Falha ao eliminar.');
        deletePersonaConfirmModalInstance.hide();
        fetchAndRenderPersonas();
        populatePersonaSelect();
    } catch (error) {
        showError(personaListError, error.message);
    } finally {
        hideSpinner(deletePersonaSpinner);
    }
}

// --- Funções para Gestão de Memória ---
async function openMemoryManagementModal(personaKey, personaName) {
    memoryPersonaNameEl.textContent = personaName;
    currentMemoryPersonaKeyInput.value = personaKey;
    clearMemoryForm();
    memoryManagementModalInstance.show();
    await fetchAndRenderMemories(personaKey);
}

// EM APP.JS, substitua a sua função fetchAndRenderMemories por esta
async function fetchAndRenderMemories(contextKey) {
    memoryTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary">A carregar...</td></tr>';
    hideError(memoryListErrorEl);

    // ESCOLHE A ROTA DA API CORRETA: BASE OU PERSONA
    const isBaseContext = contextKey === 'base_knowledge';
    const apiUrl = isBaseContext ? '/api/base_knowledge' : `/api/personas/${contextKey}/memories`;

    try {
        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`Erro: ${response.statusText}`);
        const memories = await response.json();
        memoryTableBody.innerHTML = '';

        if (memories.length === 0) {
            memoryTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary">Nenhuma memória guardada.</td></tr>';
            return;
        }

        memories.forEach(memory => {
            const tr = document.createElement('tr');
            tr.dataset.memoryId = memory.id;

            let sourceBadge = '';
            // Se o 'source' não vier da API (no caso da rota /api/base_knowledge), assumimos que é 'Base'
            const source = memory.source || (isBaseContext ? 'Base' : 'Persona');
            
            if (source === 'Base') {
                sourceBadge = `<span class="badge bg-info" title="Esta memória é partilhada por todas as personas.">Base</span>`;
            } else {
                sourceBadge = `<span class="badge bg-primary" title="Esta memória é específica desta persona.">Persona</span>`;
            }

            // ATIVA/DESATIVA BOTÕES COM BASE NO CONTEXTO
            // Se estamos no contexto de uma persona, os botões para memórias 'Base' são desativados.
            // Se estamos no contexto 'Base', todos os botões são ativados.
            const buttonsDisabled = !isBaseContext && source === 'Base' ? 'disabled' : '';
            const disabledTitle = buttonsDisabled ? 'title="Memórias Base devem ser editadas no gestor de Memória Base."' : '';

            tr.innerHTML = `
                <td>
                    <span class="badge bg-secondary me-2">${escapeHtml(memory.type)}</span>
                    ${sourceBadge}
                </td>
                <td>${escapeHtml(memory.content)}</td>
                <td>${escapeHtml((memory.trigger_keywords || []).join(', '))}</td>
                <td class="persona-actions">
                    <button class="btn btn-sm btn-info edit-memory-btn" ${buttonsDisabled} ${disabledTitle}><i class="fas fa-edit"></i></button>
                    <button class="btn btn-sm btn-danger delete-memory-btn" ${buttonsDisabled} ${disabledTitle}><i class="fas fa-trash-alt"></i></button>
                </td>
            `;
            memoryTableBody.appendChild(tr);
        });
    } catch (error) {
        showError(memoryListErrorEl, `Falha ao carregar memórias: ${error.message}`);
    }
}

function clearMemoryForm() {
    memoryForm.reset();
    currentMemoryIdInput.value = '';
    memoryFormTitleEl.textContent = 'Adicionar Nova Memória';
    cancelEditMemoryBtn.style.display = 'none';
    hideError(memoryFormErrorEl);
}

function populateMemoryForm(memoryData) {
    currentMemoryIdInput.value = memoryData.id;
    memoryContentInput.value = memoryData.content;
    memoryTypeSelect.value = memoryData.type;
    memoryTriggersInput.value = (memoryData.trigger_keywords || []).join(', ');
    memoryFormTitleEl.textContent = 'Editar Memória';
    cancelEditMemoryBtn.style.display = 'inline-block';
    memoryContentInput.focus();
}

async function handleMemoryFormSubmit(event) {
    event.preventDefault();
    showSpinner(saveMemorySpinner);
    saveMemoryBtn.disabled = true;
    hideError(memoryFormErrorEl);

    // --- LÓGICA ATUALIZADA ---
    // 1. Determinar o contexto (Base ou Persona) a partir do input escondido
    const contextKey = currentMemoryPersonaKeyInput.value;
    const isBaseContext = contextKey === 'base_knowledge';
    const memoryId = currentMemoryIdInput.value;
    const isEditing = !!memoryId;

    const payload = {
        content: memoryContentInput.value.trim(),
        type: memoryTypeSelect.value,
        trigger_keywords: memoryTriggersInput.value.split(',').map(k => k.trim()).filter(Boolean)
    };

    if (!payload.content) {
        showError(memoryFormErrorEl, "O conteúdo não pode estar vazio.");
        hideSpinner(saveMemorySpinner);
        saveMemoryBtn.disabled = false;
        return;
    }

    // 2. Definir a URL da API e o método com base no contexto
    let url, method;
    if (isEditing) {
        method = 'PUT';
        url = isBaseContext ? `/api/base_knowledge/${memoryId}` : `/api/personas/${contextKey}/memories/${memoryId}`;
    } else {
        method = 'POST';
        url = isBaseContext ? '/api/base_knowledge' : `/api/personas/${contextKey}/memories`;
    }

    try {
        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
        
        clearMemoryForm();
        // 3. Recarregar as memórias do contexto em que estamos a trabalhar
        await fetchAndRenderMemories(contextKey);
    } catch (error) {
        showError(memoryFormErrorEl, `Erro ao guardar: ${error.message}`);
    } finally {
        hideSpinner(saveMemorySpinner);
        saveMemoryBtn.disabled = false;
    }
}

async function handleMemoryTableClick(event) {
    const editBtn = event.target.closest('.edit-memory-btn');
    const deleteBtn = event.target.closest('.delete-memory-btn');

    // --- LÓGICA ATUALIZADA ---
    // 1. Ignorar cliques em botões desativados (importante para a segurança da UI)
    if ((editBtn && editBtn.disabled) || (deleteBtn && deleteBtn.disabled)) {
        return;
    }

    // 2. Determinar o contexto (Base ou Persona)
    const contextKey = currentMemoryPersonaKeyInput.value;
    const isBaseContext = contextKey === 'base_knowledge';

    if (editBtn) {
        const row = editBtn.closest('tr');
        const memoryId = row.dataset.memoryId;
        // 3. Escolher a API correta para ir buscar os dados para o formulário de edição
        const apiUrl = isBaseContext ? `/api/base_knowledge` : `/api/personas/${contextKey}/memories`;
        
        try {
            const response = await fetch(apiUrl);
            const memories = await response.json();
            const memoryData = memories.find(m => m.id === memoryId);
            if (memoryData) populateMemoryForm(memoryData);
        } catch (error) {
            showError(memoryListErrorEl, "Não foi possível carregar os dados para edição.");
        }
    }

    if (deleteBtn) {
        const row = deleteBtn.closest('tr');
        const memoryId = row.dataset.memoryId;
        // 4. Escolher a API correta para enviar o pedido de eliminação
        const apiUrl = isBaseContext ? `/api/base_knowledge/${memoryId}` : `/api/personas/${contextKey}/memories/${memoryId}`;
        
        if (confirm('Tem a certeza que deseja apagar esta memória?')) {
            try {
                const response = await fetch(apiUrl, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error);
                // 5. Recarregar as memórias do contexto atual para refletir a eliminação
                await fetchAndRenderMemories(contextKey);
            } catch (error) {
                showError(memoryListErrorEl, `Erro ao apagar: ${error.message}`);
            }
        }
    }
}

// --- Dashboard Functions ---
async function fetchDashboardData() {
    try {
        const response = await fetch('/api/dashboard_stats');
        if (!response.ok) throw new Error('Falha ao carregar estatísticas.');
        const data = await response.json();
        if(data.error) throw new Error(data.error);
        updateKPICards(data);
        updateDraftsTable(data.drafts);
        updateStatusChart(data);
        const sentPercentage = data.total > 0 ? Math.round(((data.sent || 0) / data.total) * 100) : 0;
        chartCenterMetric.textContent = `${sentPercentage}%`;
    } catch (error) {
        console.error('Erro ao carregar dados do dashboard:', error);
        // Opcional: mostrar um erro no UI
    }
}

function updateKPICards(data) {
    const animateCount = (element, endValue) => {
        const startValue = parseInt(element.dataset.count, 10) || 0;
        if (startValue === endValue) return;

        let current = startValue;
        const increment = endValue > startValue ? 1 : -1;
        const stepTime = Math.abs(Math.floor(1000 / (endValue - startValue))) || 50;

        const timer = setInterval(() => {
            current += increment;
            element.textContent = current;
            if (current == endValue) {
                clearInterval(timer);
            }
        }, stepTime);
    };

    kpiValues.forEach(card => {
        // CORREÇÃO: Usar dataset.status do elemento pai (o .kpi-card)
        const status = card.parentElement.dataset.status; 
        const count = data[status] || 0;
        animateCount(card, count);
        card.dataset.count = count; // Atualiza o valor para a próxima animação
    });
}


function updateDraftsTable(drafts) {
    draftsTableBody.innerHTML = '';
    if (!drafts || drafts.length === 0) {
        draftsTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary p-4">Nenhum rascunho pendente.</td></tr>';
        return;
    }
    drafts.forEach(draft => {
        const tr = document.createElement('tr');
        tr.dataset.draftId = draft.id;
        tr.innerHTML = `
            <td>${escapeHtml(draft.recipient)}</td>
            <td>${escapeHtml(draft.subject)}</td>
            <td>${new Date(draft.created_at).toLocaleDateString('pt-PT')}</td>
            <td>
                <button class="action-btn approve" data-draft-id="${draft.id}" title="Aprovar">✓</button>
                <button class="action-btn reject" data-draft-id="${draft.id}" title="Rejeitar">✗</button>
            </td>
        `;
        draftsTableBody.appendChild(tr);
    });
}

function updateStatusChart(data) {
    if (!statusChartCanvas) return;
    const ctx = statusChartCanvas.getContext('2d');
    const sentValue = data.sent || 0;
    const rejectedValue = data.rejected || 0;
    const pendingValue = data.pending || 0;

    if (statusChart) statusChart.destroy();
    
    statusChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Enviadas', 'Rejeitados', 'Pendente'],
            datasets: [{
                data: [sentValue, rejectedValue, pendingValue],
                backgroundColor: ['#20c997', '#dc3545', '#ffc107'],
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '70%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(0,0,0,0.7)',
                    titleFont: { size: 14 },
                    bodyFont: { size: 12 },
                    padding: 10,
                    cornerRadius: 4
                }
            }
        }
    });
}

async function handleDraftAction(event) {
    const btn = event.target.closest('.action-btn');
    if (!btn || btn.disabled) return;

    btn.disabled = true; // Desativa o botão para evitar cliques duplos
    const draftId = btn.dataset.draftId;
    const action = btn.classList.contains('approve') ? 'approved' : 'rejected';
    const row = btn.closest('tr');
    
    let url = `/api/draft/${draftId}/status`;
    let options = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: action })
    };

    // Se a ação for "approve", usamos a nova rota de envio
    if (action === 'approved') {
        url = `/api/draft/${draftId}/send`;
        options.body = null; // Não precisamos de corpo para este pedido
    }

    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Falha ao processar o pedido.');
        }

        // Se tudo correu bem, anima a remoção da linha e atualiza os dados
        if (row) {
            row.classList.add('fade-out');
            setTimeout(() => {
                row.remove();
                // Verifica se a tabela ficou vazia
                if (draftsTableBody.children.length === 0) {
                    draftsTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary p-4">Nenhum rascunho pendente.</td></tr>';
                }
                fetchDashboardData(); // Atualiza os contadores KPI e o gráfico
            }, 500);
        }
    } catch (error) {
        console.error(`Erro ao ${action} rascunho:`, error);
        alert(`Não foi possível processar o rascunho: ${error.message}`);
        btn.disabled = false; // Reativa o botão se houver erro
    }
}

// EM APP.JS, pode adicionar esta função perto da openMemoryManagementModal
function openBaseMemoryManagementModal() {
    memoryPersonaNameEl.textContent = "Base (Partilhada por todas as Personas)";
    
    // Usamos o mesmo input escondido para guardar o 'contexto', mas com um valor especial
    currentMemoryPersonaKeyInput.value = 'base_knowledge'; 
    
    clearMemoryForm();
    memoryManagementModalInstance.show();
    
    // Chamamos a função de renderização, que agora saberá o que fazer
    fetchAndRenderMemories('base_knowledge'); 
}