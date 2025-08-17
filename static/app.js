// --- Seletores de Elementos DOM ---
const bodyEl = document.body;
const themeToggle = document.getElementById('theme-checkbox');
const apiStatusIndicatorEl = document.getElementById('apiStatusIndicator');
const isLoggedIn = bodyEl.dataset.isLoggedIn === 'true';

// --- Seletores da App Principal (só existem se estiver logado) ---
const mainAppWrapper = document.getElementById('mainAppWrapper');
const wizardSteps = document.querySelectorAll('.wizard-step');
const originalEmailEl = document.getElementById('originalEmail');
const analyzeBtn = document.getElementById('analyzeBtn'); // Botão de Analisar do Passo 1
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

// --- Seletores para Gmail ---
const fetchEmailsBtn = document.getElementById('fetchEmailsBtn');
const emailListEl = document.getElementById('emailList');
const gmailSpinnerEl = document.getElementById('gmailSpinner');
const gmailErrorEl = document.getElementById('gmailError');

// --- Seletores para Elementos de Feedback ---
const feedbackModalEl = document.getElementById('feedbackModal');
const feedbackOriginalResponseEl = document.getElementById('feedbackOriginalResponse');
const feedbackUserCorrectionEl = document.getElementById('feedbackUserCorrection');
const feedbackErrorModalEl = document.getElementById('feedbackErrorModal');
const feedbackSubmitSpinner = document.getElementById('feedbackSubmitSpinner');
let feedbackModalInstance = null;

// --- Seletores para Envio de Email ---
const sendEmailBtn = document.getElementById('sendEmailBtn');
const sendEmailSpinner = document.getElementById('sendEmailSpinner');
const sendEmailSuccessMessageEl = document.getElementById('sendEmailSuccessMessage');
const sendEmailErrorEl = document.getElementById('sendEmailError');

// --- Seletores para o Modal de Confirmação de Envio ---
const sendEmailConfirmModalEl = document.getElementById('sendEmailConfirmModal');
const confirmRecipientEl = document.getElementById('confirmRecipient');
const confirmSubjectEl = document.getElementById('confirmSubject');
const confirmBodyPreviewEl = document.getElementById('confirmBodyPreview');
const confirmSendBtn = document.getElementById('confirmSendBtn');
const cancelSendBtn = document.getElementById('cancelSendBtn');
let sendEmailConfirmModalInstance = null;

// --- Seletores para navegação entre passos e indicador de progresso ---
const backToAnalysisBtn = document.getElementById('backToAnalysisBtn');
const backToSelectBtn = document.getElementById('backToSelectBtn');
const progressSteps = document.querySelectorAll('.progress-step');

// --- NOVOS Seletores para Gestão de Personas ---
const createPersonaBtn = document.getElementById('createPersonaBtn');
const personasTableBody = document.getElementById('personasTableBody');
const personaFormModalEl = document.getElementById('personaFormModal');
const personaFormModalLabel = document.getElementById('personaFormModalLabel');
const personaForm = document.getElementById('personaForm');
const personaKeyInput = document.getElementById('personaKeyInput');
const personaLabelPtInput = document.getElementById('personaLabelPtInput');
const personaDescriptionPtInput = document.getElementById('personaDescriptionPtInput');
const personaRoleTemplateInput = document.getElementById('personaRoleTemplateInput');
const commLanguageInput = document.getElementById('commLanguageInput');
const commVerbosityInput = document.getElementById('commVerbosityInput');
const commSentenceStructureInput = document.getElementById('commSentenceStructureInput');
const commVocabularyPreferenceInput = document.getElementById('commVocabularyPreferenceInput');
const commEmojiUsageInput = document.getElementById('commEmojiUsageInput');
const styleToneLabelInput = document.getElementById('styleToneLabelInput');
const styleToneKeywordsInput = document.getElementById('styleToneKeywordsInput');
const styleFormalityLabelInput = document.getElementById('styleFormalityLabelInput');
const styleFormalityNumericInput = document.getElementById('styleFormalityNumericInput');
const styleFormalityGuidanceInput = document.getElementById('styleFormalityGuidanceInput');
const generalDosInput = document.getElementById('generalDosInput');
const generalDontsInput = document.getElementById('generalDontsInput');
const fewShotExamplesContainer = document.getElementById('fewShotExamplesContainer');
const addFewShotExampleBtn = document.getElementById('addFewShotExampleBtn');
const savePersonaBtn = document.getElementById('savePersonaBtn');
const savePersonaSpinner = document.getElementById('savePersonaSpinner');
const personaFormError = document.getElementById('personaFormError');
const personaListError = document.getElementById('personaListError');
const deletePersonaConfirmModalEl = document.getElementById('deletePersonaConfirmModal');
const personaToDeleteNameEl = document.getElementById('personaToDeleteName');
const confirmDeletePersonaBtn = document.getElementById('confirmDeletePersonaBtn');
const deletePersonaSpinner = document.getElementById('deletePersonaSpinner');
const currentPersonaKeyInput = document.getElementById('currentPersonaKey'); // Hidden input for editing

let personaFormModalInstance = null;
let deletePersonaConfirmModalInstance = null;
let personaToDeleteKey = null; // Armazena a chave da persona a ser eliminada

// --- Estado da Aplicação ---
let currentStep = 1; // 1: Selecionar Email, 2: Analisar, 3: Compor, 4: Gerir Personas
let currentAnalysisPoints = [];
let isRefining = false;
let currentDraftContext = {};
let lastGeneratedDraftForFeedback = "";
let currentOriginalSenderEmail = "";
let currentOriginalSubject = "";
let currentThreadId = "";
let resolveSendConfirmation;

// --- Funções Auxiliares ---
function showSpinner(spinner) { if(spinner) spinner.style.display = 'inline-block'; }
function hideSpinner(spinner) { if(spinner) spinner.style.display = 'none'; }
function showError(element, message) {
    if (!element) return;
    const iconHTML = element.querySelector('i') ? '' : '<i class="fas fa-exclamation-circle me-2"></i>';
    element.innerHTML = `${iconHTML} ${message}`;
    element.style.display = 'block';
}
function hideError(element) { if (element) { element.textContent = ''; element.style.display = 'none';} }
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
    if (theme === 'light') {
        bodyEl.classList.add('light-mode');
        bodyEl.classList.remove('dark-mode');
        if (themeToggle) themeToggle.checked = false;
    } else {
        bodyEl.classList.add('dark-mode');
        bodyEl.classList.remove('light-mode');
        if (themeToggle) themeToggle.checked = true;
    }
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
    }
});

function initializeMainApp() {
    if (feedbackModalEl) {
        feedbackModalInstance = new bootstrap.Modal(feedbackModalEl);
        // NOVO: Adiciona o listener para o botão de submissão aqui
        const submitFeedbackBtn = document.getElementById('submitFeedbackBtn');
        if (submitFeedbackBtn) {
            submitFeedbackBtn.addEventListener('click', submitFeedback);
        }
    }
    if (sendEmailConfirmModalEl) {
        sendEmailConfirmModalInstance = new bootstrap.Modal(sendEmailConfirmModalEl);
    }
    // NOVOS MODAIS
    if (personaFormModalEl) {
        personaFormModalInstance = new bootstrap.Modal(personaFormModalEl);
    }
    if (deletePersonaConfirmModalEl) {
        deletePersonaConfirmModalInstance = new bootstrap.Modal(deletePersonaConfirmModalEl);
    }

    // A chamada para populateFeedbackTypes() foi REMOVIDA daqui.

    // Adiciona todos os event listeners da aplicação principal
    analyzeBtn.addEventListener('click', handleAnalysisAndAdvance);
    draftBtn.addEventListener('click', handleDrafting);
    copyDraftBtn.addEventListener('click', handleCopy);
    userInputsSection.addEventListener('click', handleGuidanceSuggestion);
    generatedDraftEl.addEventListener('select', handleTextSelection);
    generatedDraftEl.addEventListener('mouseup', handleTextSelection);
    generatedDraftEl.addEventListener('keyup', handleTextSelection);
    document.addEventListener('click', handleDeselection);
    refinementControlsEl.addEventListener('click', handleRefinement);
    feedbackBtn.addEventListener('click', openFeedbackModal);
    // O listener de submitFeedbackBtn foi movido para cima
    fetchEmailsBtn.addEventListener('click', fetchAndRenderEmails);
    emailListEl.addEventListener('click', handleEmailClick);
    sendEmailBtn.addEventListener('click', handleSendEmail);

    // Event listeners para navegação entre passos
    backToSelectBtn.addEventListener('click', () => showStep(1));
    backToAnalysisBtn.addEventListener('click', () => showStep(2));
    document.getElementById('progress-step-4').addEventListener('click', () => showStep(4));
    document.getElementById('backToMainFlowBtn').addEventListener('click', () => showStep(1));

    originalEmailEl.addEventListener('input', () => {
        analyzeBtn.disabled = originalEmailEl.value.trim() === '';
    });

    confirmSendBtn.addEventListener('click', () => {
        if (resolveSendConfirmation) {
            resolveSendConfirmation(true);
            sendEmailConfirmModalInstance.hide();
        }
    });
    cancelSendBtn.addEventListener('click', () => {
        if (resolveSendConfirmation) {
            resolveSendConfirmation(false);
            sendEmailConfirmModalInstance.hide();
        }
    });

    // --- NOVOS Event Listeners para Gestão de Personas ---
    createPersonaBtn.addEventListener('click', openCreatePersonaModal);
    personaForm.addEventListener('submit', submitPersonaForm);
    addFewShotExampleBtn.addEventListener('click', () => addFewShotExampleField('', ''));
    fewShotExamplesContainer.addEventListener('click', (event) => {
        if (event.target.classList.contains('remove-few-shot-example')) {
            event.target.closest('.few-shot-example-group').remove();
            updateFewShotExampleLabels();
        }
    });

    personasTableBody.addEventListener('click', handlePersonaTableClick);
    confirmDeletePersonaBtn.addEventListener('click', deletePersona);

    showStep(1);
    fetchAndRenderEmails();
    fetchAndRenderPersonas(); 
    populatePersonaSelect();
}

/**
 * Controla a exibição dos passos do assistente e atualiza o indicador de progresso.
 * @param {number} stepNumber O número do passo a ser exibido (1, 2, 3 ou 4).
 */
function showStep(stepNumber) {
    currentStep = stepNumber;
    wizardSteps.forEach(step => {
        step.classList.remove('active-step');
    });
    document.getElementById(`step-${stepNumber}`).classList.add('active-step');

    // Atualiza o indicador de progresso
    progressSteps.forEach((step, index) => {
        if (index + 1 < stepNumber) {
            step.classList.add('completed');
            step.classList.remove('active');
        } else if (index + 1 === stepNumber) {
            step.classList.add('active');
            step.classList.remove('completed');
        } else {
            step.classList.remove('active', 'completed');
        }
    });

    // Ajusta a altura do wrapper para a altura do passo ativo, criando um efeito mais limpo
    const activeStepElement = document.getElementById(`step-${stepNumber}`);
    if (activeStepElement) {
        // Usa requestAnimationFrame para garantir que a altura é calculada após o layout ser atualizado
        requestAnimationFrame(() => {
            mainAppWrapper.style.height = `${activeStepElement.scrollHeight + 80}px`; // Adiciona um pouco de padding
            setTimeout(() => {
                mainAppWrapper.style.height = 'auto'; // Remove a altura fixa após a transição
            }, 500); // tempo da transição em CSS
        });
    }
}


// --- Lógica de Funções de UI ---
async function fetchAndRenderEmails() {
    showSpinner(gmailSpinnerEl);
    hideError(gmailErrorEl);
    fetchEmailsBtn.disabled = true;
    emailListEl.innerHTML = '<li class="list-group-item text-secondary">A carregar emails...</li>';

    try {
        const response = await fetch('/api/emails');
        if (!response.ok) {
            if (response.status === 401) {
                throw new Error("Sessão expirada. Por favor, <a href='/login'>faça login novamente</a>.");
            }
            throw new Error(`Erro ao buscar emails: ${response.statusText}`);
        }
        const emails = await response.json();
        emailListEl.innerHTML = '';
        if (emails.error) {
            throw new Error(emails.error);
        }
        if (emails.length === 0) {
            emailListEl.innerHTML = '<li class="list-group-item text-secondary">Nenhum email encontrado na sua caixa de entrada.</li>';
            return;
        }
        emails.forEach(email => {
            const li = document.createElement('li');
            li.className = 'list-group-item email-list-item';
            li.dataset.threadId = email.threadId;
            li.dataset.emailId = email.id;
            li.innerHTML = `
                <span class="email-sender">${escapeHtml(email.sender.replace(/<.*?>/g, ''))}</span>
                <span class="email-subject">${escapeHtml(email.subject)}</span>
                <span class="email-snippet">${escapeHtml(email.snippet)}</span>
            `;
            emailListEl.appendChild(li);
        });
    } catch (error) {
        console.error("Erro ao carregar emails:", error);
        showError(gmailErrorEl, error.message);
        emailListEl.innerHTML = '';
    } finally {
        hideSpinner(gmailSpinnerEl);
        fetchEmailsBtn.disabled = false;
    }
}

async function handleEmailClick(event) {
    const listItem = event.target.closest('.email-list-item');
    if (listItem && listItem.dataset.threadId) {
        // Remove a classe 'active' de todos os itens e adiciona ao clicado
        document.querySelectorAll('.email-list-item').forEach(item => {
            item.classList.remove('active');
        });
        listItem.classList.add('active');

        const threadId = listItem.dataset.threadId;
        originalEmailEl.value = `A carregar a conversa (Thread ID: ${threadId})...`;
        sendEmailBtn.disabled = true;
        hideError(sendEmailErrorEl);
        showSuccessMessage(sendEmailSuccessMessageEl, '', 0);
        analyzeBtn.disabled = true; // Desabilita o botão enquanto carrega

        try {
            const response = await fetch(`/api/thread/${threadId}`);
            if (!response.ok) {
                throw new Error(`Falha ao carregar a thread. Status: ${response.status}`);
            }
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            originalEmailEl.value = data.thread_text;
            currentOriginalSenderEmail = data.original_sender_email;
            currentOriginalSubject = data.original_subject;
            currentThreadId = threadId;

            analyzeBtn.disabled = false; // Habilita o botão após carregar
            // O usuário agora clica em "Processar & Próximo Passo" para avançar
        } catch (error) {
            console.error("Erro ao carregar thread:", error);
            showError(analyzeErrorEl, error.message);
            originalEmailEl.value = '';
            currentOriginalSenderEmail = "";
            currentOriginalSubject = "";
            currentThreadId = "";
        } finally {
            // Se o email for carregado, o analyzeBtn é habilitado, caso contrário permanece desabilitado.
            analyzeBtn.disabled = originalEmailEl.value.trim() === '';
        }
    }
}

/**
 * Lida com a análise do email e avança para o passo 2.
 */
async function handleAnalysisAndAdvance() {
    const emailText = originalEmailEl.value.trim();
    if (!emailText) {
        showError(analyzeErrorEl, "Por favor, insira o texto do email recebido ou selecione um email.");
        originalEmailEl.focus(); originalEmailEl.classList.add('is-invalid');
        return;
    } else {
        originalEmailEl.classList.remove('is-invalid');
    }

    showSpinner(analyzeSpinner);
    hideError(analyzeErrorEl); hideError(draftErrorEl); hideError(feedbackErrorModalEl); hideError(sendEmailErrorEl);
    if(feedbackSuccessMessageEl) feedbackSuccessMessageEl.style.display = 'none';
    if(sendEmailSuccessMessageEl) sendEmailSuccessMessageEl.style.display = 'none';
    refinementControlsEl.style.display = 'none'; analysisResultEl.innerHTML = '';
    userInputsSection.innerHTML = ''; generatedDraftEl.value = '';
    contextInfoEl.style.display = 'none';
    analyzeBtn.disabled = true; // Desabilitar enquanto processa
    draftBtn.disabled = true; // Desabilitar draft button
    if(feedbackBtn) feedbackBtn.disabled = true;
    if(sendEmailBtn) sendEmailBtn.disabled = true;
    currentDraftContext = {};
    lastGeneratedDraftForFeedback = "";

    try {
        const response = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email_text: emailText })
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            let errorMsg = data.error || `Erro HTTP ${response.status}: ${response.statusText}`;
            if (data.raw_analysis) { errorMsg += ` | Resposta LLM (RAW): ${escapeHtml(data.raw_analysis.substring(0, 100))}...`; }
            throw new Error(errorMsg);
        }
        currentAnalysisPoints = data.points || [];
        displayAnalysisResults(data);
        createUserInputFields(currentAnalysisPoints);

        // Move para o Passo 2 após análise bem-sucedida
        showStep(2);

    } catch (error) {
        console.error("Erro durante a análise:", error);
        showError(analyzeErrorEl, `Erro na análise: ${error.message}`);
    } finally {
        hideSpinner(analyzeSpinner);
        analyzeBtn.disabled = originalEmailEl.value.trim() === ''; // Reabilita se tiver texto, mesmo em erro
        if (currentStep === 2 && personaSelect.value && !personaSelect.disabled) { // Apenas reabilita o draftBtn se estiver no passo correto e persona selecionada
            draftBtn.disabled = false;
        }
    }
}


function displayAnalysisResults(data) {
    let html = '<h4>Pontos de Ação Identificados:</h4>';
    const hasRealPoints = data.points && data.points.length > 0 && !(data.points.length === 1 && data.points[0].toLowerCase().includes("nenhum ponto"));
    if (hasRealPoints) {
        html += '<ol class="list-group list-group-numbered list-group-flush mb-3">';
        data.points.forEach(point => { html += `<li class="list-group-item">${escapeHtml(point)}</li>`; });
        html += '</ol>';
    } else {
        html += '<p class="text-secondary fst-italic">Nenhum ponto específico identificado para resposta direta.</p>';
    }
    if (data.actions && data.actions.length > 0) {
        html += '<h4 class="mt-4">Ações Sugeridas:</h4>';
        html += '<ul class="list-group list-group-flush">';
        data.actions.forEach(action => { html += `<li class="list-group-item">${escapeHtml(action)}</li>`; });
        html += '</ul>';
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
        const requiredAttr = ''; // Removido 'required' para permitir campos vazios
        const requiredFeedback = !isGeneral ? '<div class="invalid-feedback">Por favor, forneça uma diretriz para este ponto.</div>' : '';
        const directionRadiosHTML = !isGeneral ? `<div class="mb-2 guidance-direction-group"><span class="form-label-sm d-block mb-1">Vetor de Resposta Rápida:</span><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-sim" value="sim"><label class="form-check-label" for="direction-${index}-sim">Afirmativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-nao" value="nao"><label class="form-check-label" for="direction-${index}-nao">Negativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-outro" value="outro" checked><label class="form-check-label" for="direction-${index}-outro">Detalhado</label></div></div>` : '';
        const suggestButtonHTML = !isGeneral ? `<button class="btn btn-sm btn-outline-secondary suggest-btn" data-target-textarea="${inputId}" data-point-index="${index}" type="button" title="Gerar sugestão de diretriz via IA, usando o Vetor de Resposta">Sugerir Diretriz<div class="spinner-border spinner-border-sm loading-spinner" role="status" style="display: none;"></div></button>` : '';
        div.innerHTML = `<div class="d-flex justify-content-between align-items-start mb-1 flex-wrap"><label for="${inputId}" class="form-label mb-0 me-2">${labelText}</label>${suggestButtonHTML}</div>${pointDisplay}${directionRadiosHTML}<textarea class="form-control user-guidance" id="${inputId}" data-point="${escapeHtml(pointIdentifier)}" rows="3" ${requiredAttr} placeholder="Insira a sua diretriz para este ponto..."></textarea>${requiredFeedback}`;
        userInputsSection.appendChild(div);
    };
    const hasRealPoints = points && points.length > 0 && !(points.length === 1 && points[0].toLowerCase().includes("nenhum ponto"));
    if (hasRealPoints) { points.forEach((point, index) => { createGroup(point, index, false); }); }
    createGroup(null, 'general', true);
}

async function handleDrafting() {
    const originalEmail = originalEmailEl.value.trim();
    const selectedPersona = personaSelect.value;
    const guidanceInputs = userInputsSection.querySelectorAll('.user-guidance');
    let userInputsData = [];
    hideError(draftErrorEl); hideError(feedbackErrorModalEl); hideError(sendEmailErrorEl);
    if(feedbackSuccessMessageEl) feedbackSuccessMessageEl.style.display = 'none';
    if(sendEmailSuccessMessageEl) sendEmailSuccessMessageEl.style.display = 'none';
    contextInfoEl.style.display = 'none'; refinementControlsEl.style.display = 'none';
    if(feedbackBtn) feedbackBtn.disabled = true;
    if(sendEmailBtn) sendEmailBtn.disabled = true;
    currentDraftContext = {};
    lastGeneratedDraftForFeedback = "";

    guidanceInputs.forEach(input => {
        const pointText = input.getAttribute('data-point');
        const guidanceText = input.value.trim();
        if (guidanceText || input.id === 'userInput-general') {
            userInputsData.push({ point: pointText, guidance: guidanceText });
        }
    });

    if (!selectedPersona) { showError(draftErrorEl, "Por favor, selecione um protocolo de persona."); personaSelect.focus(); return; }

    showSpinner(draftSpinner);
    generatedDraftEl.value = '';
    draftBtn.disabled = true;
    analyzeBtn.disabled = true; // Desabilita o botão de análise do Passo 1 durante a composição

    try {
        const response = await fetch('/draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ original_email: originalEmail, persona_name: selectedPersona, user_inputs: userInputsData })
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            let errorMsg = data.error || `Erro HTTP ${response.status}: ${response.statusText}`;
            if (data.context_analysis) { 
                // Apenas adiciona o erro da pré-análise se existir e for diferente do erro principal
                if (data.context_analysis.error && data.context_analysis.error !== errorMsg) {
                    errorMsg += ` (Erro na pré-análise de contexto: ${escapeHtml(data.context_analysis.error)})`; 
                }
            }
            throw new Error(errorMsg);
        }
        generatedDraftEl.value = data.draft || "";
        lastGeneratedDraftForFeedback = data.draft || "";

        // Move para o Passo 3 após a composição bem-sucedida
        showStep(3);

        if(feedbackBtn) feedbackBtn.disabled = !lastGeneratedDraftForFeedback.trim();
        if (lastGeneratedDraftForFeedback.trim() && currentOriginalSenderEmail && currentOriginalSubject) {
            sendEmailBtn.disabled = false;
        }

        if (data.context_analysis) {
            contextDetailsEl.textContent = `Cat: ${data.context_analysis.recipient_category || 'N/D'}, Tom Rx: ${data.context_analysis.incoming_tone || 'N/D'}, Remet: ${data.context_analysis.sender_name_guess || 'N/D'}`;
            contextInfoEl.style.display = 'block';
            currentDraftContext = {
                original_email_text: originalEmail,
                user_guidance_inputs_snapshot: userInputsData,
                llm_pre_analysis_snapshot: data.context_analysis,
                persona_used: selectedPersona,
                ia_action_type: '/draft'
            };
        } else {
            currentDraftContext = {
                original_email_text: originalEmail,
                user_guidance_inputs_snapshot: userInputsData,
                llm_pre_analysis_snapshot: { error: "Pré-análise não disponível ou falhou."},
                persona_used: selectedPersona,
                ia_action_type: '/draft'
            };
        }
    } catch (error) {
        console.error("Erro durante a geração da composição:", error);
        showError(draftErrorEl, `Erro na geração da composição: ${error.message}`);
    } finally {
        hideSpinner(draftSpinner);
        if (personaSelect.value && !personaSelect.disabled) { draftBtn.disabled = false; }
        // analyzeBtn reabilita quando volta para o Passo 1 ou ao recarregar a página
        // Deixa ele desabilitado aqui enquanto não está no Passo 1
    }
}

function handleCopy() {
    if (!generatedDraftEl.value) return;
    const textToCopy = generatedDraftEl.value;
    navigator.clipboard.writeText(textToCopy).then(() => {
        // Usa a classe btn-success e então volta para btn-secondary
        copyDraftBtn.innerHTML = '<i class="fas fa-check"></i> Copiado!';
        copyDraftBtn.classList.remove('btn-secondary', 'btn-warning');
        copyDraftBtn.classList.add('btn-success');
        setTimeout(() => {
            copyDraftBtn.innerHTML = '<i class="fas fa-copy"></i> Copiar';
            copyDraftBtn.classList.remove('btn-success');
            copyDraftBtn.classList.add('btn-secondary');
        }, 2000);
    }).catch(err => {
        console.warn('Falha ao copiar com navigator.clipboard, tentando fallback:', err);
        try {
            generatedDraftEl.select(); // Seleciona o texto na textarea
            document.execCommand('copy'); // Tenta o comando de cópia legado
            // Usa a classe btn-warning para indicar fallback
            copyDraftBtn.innerHTML = '<i class="fas fa-check"></i> Copiado (Ctrl+C)!';
            copyDraftBtn.classList.remove('btn-secondary', 'btn-success');
            copyDraftBtn.classList.add('btn-warning');
            setTimeout(() => {
                copyDraftBtn.innerHTML = '<i class="fas fa-copy"></i> Copiar';
                copyDraftBtn.classList.remove('btn-warning');
                copyDraftBtn.classList.add('btn-secondary');
            }, 2000);
        } catch (execErr) {
            console.error('Fallback execCommand também falhou:', execErr);
            showError(draftErrorEl, 'Falha ao copiar automaticamente. Use Ctrl+C.');
        }
    });
}

async function handleGuidanceSuggestion(event) {
    const button = event.target.closest('.suggest-btn');
    if (button && !button.disabled) {
        const spinner = button.querySelector('.loading-spinner'); const targetTextareaId = button.dataset.targetTextarea; const pointIndex = parseInt(button.dataset.pointIndex, 10); const targetTextarea = document.getElementById(targetTextareaId); const originalEmail = originalEmailEl.value.trim(); const selectedPersonaName = personaSelect.value;
        const radioGroupName = `direction-${pointIndex}`; const checkedRadio = userInputsSection.querySelector(`input[name="${radioGroupName}"]:checked`); const selectedDirection = checkedRadio ? checkedRadio.value : "outro";
        const pointToAddress = (currentAnalysisPoints && pointIndex >= 0 && pointIndex < currentAnalysisPoints.length) ? currentAnalysisPoints[pointIndex] : null;
        if (!targetTextarea || !originalEmail || !pointToAddress || !selectedPersonaName || pointToAddress === 'N/A') { console.error("Dados em falta para sugestão de diretriz. Ponto:", pointToAddress); showError(draftErrorEl, "Erro interno: Dados insuficientes para sugestão."); return; }
        if (!selectedPersonaName) { showError(draftErrorEl, "Por favor, selecione um protocolo de persona."); personaSelect.focus(); return; }
        if (spinner) showSpinner(spinner); button.disabled = true; hideError(draftErrorEl); hideError(sendEmailErrorEl);
        try {
            const response = await fetch('/suggest_guidance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ original_email: originalEmail, point_to_address: pointToAddress, persona_name: selectedPersonaName, direction: selectedDirection }) });
            const data = await response.json();
            if (!response.ok || data.error) { throw new Error(data.error || `Erro HTTP ${response.status}: ${response.statusText}`); }
            targetTextarea.value = data.suggestion || ''; targetTextarea.dispatchEvent(new Event('input', { bubbles: true })); targetTextarea.classList.remove('is-invalid');
        } catch (error) { console.error("Erro ao obter sugestão de diretriz:", error); showError(draftErrorEl, `Erro na sugestão: ${error.message}`); }
        finally { if (spinner) hideSpinner(spinner); button.disabled = false; }
    }
}

function handleTextSelection() {
    setTimeout(() => {
        // Apenas mostra os controles se estiver no passo 3 e houver seleção
        const hasSelection = currentStep === 3 && generatedDraftEl.selectionStart !== generatedDraftEl.selectionEnd;
        refinementControlsEl.style.display = hasSelection ? 'flex' : 'none';
    }, 0);
}

function handleDeselection(event) {
    // Esconde os controles de refinamento se o clique for fora da textarea e dos controles, e não estiver refinando
    if (!generatedDraftEl.contains(event.target) && !refinementControlsEl.contains(event.target) && !isRefining) {
        refinementControlsEl.style.display = 'none';
    }
}

async function handleRefinement(event) {
    const button = event.target.closest('.refine-btn');
    if (button && !isRefining) {
        const action = button.dataset.action; const spinner = button.querySelector('.loading-spinner');
        const selectedText = generatedDraftEl.value.substring(generatedDraftEl.selectionStart, generatedDraftEl.selectionEnd);
        const fullContext = generatedDraftEl.value;
        const selectedPersonaName = personaSelect.value;
        const start = generatedDraftEl.selectionStart;
        const end = generatedDraftEl.selectionEnd;
        if (!selectedText) { refinementControlsEl.style.display = 'none'; return; }
        if (!selectedPersonaName) { showError(draftErrorEl, "Selecione um protocolo de persona para otimização."); personaSelect.focus(); return; }
        isRefining = true; if(spinner) showSpinner(spinner);
        refinementControlsEl.querySelectorAll('.refine-btn').forEach(btn => btn.disabled = true);
        hideError(draftErrorEl); hideError(sendEmailErrorEl);
        try {
            const response = await fetch('/refine_text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ selected_text: selectedText, full_context: fullContext, action: action, persona_name: selectedPersonaName })
            });
            const data = await response.json();
            if (!response.ok || data.error) { throw new Error(data.error || `Erro HTTP ${response.status}: ${response.statusText}`); }
            const before = fullContext.substring(0, start);
            const after = fullContext.substring(end);
            const refinedText = data.refined_text || "";
            generatedDraftEl.value = before + refinedText + after;
            lastGeneratedDraftForFeedback = generatedDraftEl.value;
            generatedDraftEl.focus();
            const newCursorPos = start + refinedText.length;
            generatedDraftEl.setSelectionRange(newCursorPos, newCursorPos);
        } catch (error) {
            console.error(`Erro ao otimizar texto (Ação: ${action}):`, error);
            showError(draftErrorEl, `Erro na otimização (${action}): ${error.message}`);
        }
        finally {
            if(spinner) hideSpinner(spinner);
            refinementControlsEl.querySelectorAll('.refine-btn').forEach(btn => btn.disabled = false);
            isRefining = false;
            // refinementControlsEl.style.display = 'none'; // Não esconder imediatamente, permite nova seleção
        }
    }
}

function openFeedbackModal() {
    if (!lastGeneratedDraftForFeedback.trim()) {
        showError(draftErrorEl, "Não há rascunho gerado para fornecer feedback.");
        return;
    }
    hideError(feedbackErrorModalEl);
    if(feedbackSuccessMessageEl) feedbackSuccessMessageEl.style.display = 'none';
    if(sendEmailSuccessMessageEl) sendEmailSuccessMessageEl.style.display = 'none';

    // Apenas os campos que ainda existem são preenchidos
    feedbackOriginalResponseEl.value = lastGeneratedDraftForFeedback;
    feedbackUserCorrectionEl.value = ''; // Limpa a caixa de texto para o utilizador

    if (feedbackModalInstance) {
        feedbackModalInstance.show();
    }
}

async function submitFeedback() {
    const selectedPersona = personaSelect.value;
    const userCorrection = feedbackUserCorrectionEl.value.trim();

    // Validação Simplificada
    if (!selectedPersona) { showError(feedbackErrorModalEl, "Nenhuma persona selecionada. Não é possível submeter feedback."); return; }
    if (!userCorrection) { showError(feedbackErrorModalEl, "Por favor, forneça a sua versão correta para que a IA possa aprender."); feedbackUserCorrectionEl.focus(); return; }
    
    hideError(feedbackErrorModalEl);
    showSpinner(feedbackSubmitSpinner);
    submitFeedbackBtn.disabled = true;

    // Payload simplificado, apenas com o essencial
    const payload = {
        persona_name: selectedPersona,
        ai_original_response: feedbackOriginalResponseEl.value,
        user_corrected_output: userCorrection,
        // O contexto da interação é a parte mais importante para a IA aprender
        interaction_context: currentDraftContext 
    };

    try {
        const response = await fetch('/submit_feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        // Verificação robusta da resposta do servidor
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `Erro HTTP ${response.status}` }));
            throw new Error(errorData.error || "O servidor respondeu com um erro.");
        }
        
        const data = await response.json();

        if (data.error) { // Verifica se o JSON de resposta contém um erro
             throw new Error(data.error);
        }

        if(feedbackModalInstance) feedbackModalInstance.hide();
        // Mensagem de sucesso mais informativa
        const successMsg = `Feedback submetido! Nova regra aprendida: "${data.inferred_rule || 'Regra geral'}"`;
        showSuccessMessage(feedbackSuccessMessageEl, successMsg, 6000); // Mostra por 6 segundos

    } catch (error) {
        console.error("Erro ao submeter feedback:", error);
        showError(feedbackErrorModalEl, `Erro ao submeter feedback: ${error.message}`);
    } finally {
        hideSpinner(feedbackSubmitSpinner);
        submitFeedbackBtn.disabled = false;
    }
}

/**
 * Exibe um modal de confirmação para o envio de email.
 * @param {string} recipient O email do destinatário.
 * @param {string} subject O assunto do email.
 * @param {string} bodyPreview Uma pré-visualização do corpo do email.
 * @returns {Promise<boolean>} Uma promessa que resolve para `true` se confirmado, `false` se cancelado.
 */
function showSendEmailConfirmation(recipient, subject, bodyPreview) {
    return new Promise((resolve) => {
        resolveSendConfirmation = resolve;

        confirmRecipientEl.textContent = recipient;
        confirmSubjectEl.textContent = subject;
        confirmBodyPreviewEl.textContent = bodyPreview;

        sendEmailConfirmModalInstance.show();
    });
}

async function handleSendEmail() {
    const generatedDraft = generatedDraftEl.value.trim();

    if (!generatedDraft) {
        showError(sendEmailErrorEl, "Não há composição para enviar.");
        return;
    }
    if (!currentOriginalSenderEmail) {
        showError(sendEmailErrorEl, "Não foi possível identificar o remetente original para enviar.");
        return;
    }
    if (!currentOriginalSubject) {
        showError(sendEmailErrorEl, "Não foi possível identificar o assunto original do email.");
        return;
    }
    if (!currentThreadId) {
        showError(sendEmailErrorEl, "Não foi possível identificar o ID da conversa (thread) para responder.");
        return;
    }

    const confirmation = await showSendEmailConfirmation(
        currentOriginalSenderEmail,
        currentOriginalSubject,
        generatedDraft.substring(0, 150) + "..."
    );

    if (!confirmation) {
        showError(sendEmailErrorEl, "Envio de email cancelado pelo utilizador.");
        return;
    }

    showSpinner(sendEmailSpinner);
    sendEmailBtn.disabled = true;
    hideError(sendEmailErrorEl);
    showSuccessMessage(sendEmailSuccessMessageEl, '', 0);

    try {
        const response = await fetch('/api/send_email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                recipient: currentOriginalSenderEmail,
                subject: `Re: ${currentOriginalSubject}`,
                body: generatedDraft,
                thread_id: currentThreadId
            })
        });
        const data = await response.json();

        if (!response.ok || data.error) {
            throw new Error(data.error || `Erro HTTP ${response.status}`);
        }

        showSuccessMessage(sendEmailSuccessMessageEl, "Email enviado com sucesso!");
        generatedDraftEl.value = '';
        lastGeneratedDraftForFeedback = "";
        feedbackBtn.disabled = true;
        sendEmailBtn.disabled = true;

    } catch (error) {
        console.error("Erro ao enviar email:", error);
        showError(sendEmailErrorEl, `Erro ao enviar email: ${error.message}`);
    } finally {
        hideSpinner(sendEmailSpinner);
        if (generatedDraftEl.value.trim() && currentOriginalSenderEmail && currentOriginalSubject) {
            sendEmailBtn.disabled = false;
        }
    }
}

// --- NOVAS Funções para Gestão de Personas ---

/**
 * Adiciona um novo campo de exemplo few-shot ao formulário.
 * @param {string} inputData O texto do email de input para preencher o campo.
 * @param {string} outputData O texto da resposta de output para preencher o campo.
 */
function addFewShotExampleField(inputData = '', outputData = '') {
    const exampleCount = fewShotExamplesContainer.children.length + 1;
    const div = document.createElement('div');
    div.className = 'few-shot-example-group mb-3 p-3 border rounded';
    div.style.backgroundColor = 'var(--point-group-bg)'; // Reutiliza a variável CSS
    div.innerHTML = `
        <label class="form-label">Exemplo ${exampleCount}:</label>
        <textarea class="form-control mb-2 few-shot-input" rows="2" placeholder="Email de Input">${escapeHtml(inputData)}</textarea>
        <textarea class="form-control few-shot-output" rows="2" placeholder="Resposta de Output">${escapeHtml(outputData)}</textarea>
        <button type="button" class="btn btn-danger btn-sm mt-2 remove-few-shot-example"><i class="fas fa-trash-alt"></i> Remover</button>
    `;
    fewShotExamplesContainer.appendChild(div);

    // O event listener para remover é delegado no container pai (fewShotExamplesContainer)
}

/**
 * Atualiza os rótulos dos exemplos few-shot após adicionar/remover.
 */
function updateFewShotExampleLabels() {
    const exampleGroups = fewShotExamplesContainer.querySelectorAll('.few-shot-example-group');
    exampleGroups.forEach((group, index) => {
        group.querySelector('label').textContent = `Exemplo ${index + 1}:`;
    });
}

/**
 * Abre o modal para criar uma nova persona, limpando o formulário.
 */
function openCreatePersonaModal() {
    clearPersonaForm();
    personaFormModalLabel.textContent = 'Criar Nova Persona';
    personaKeyInput.disabled = false; // A chave pode ser editada ao criar
    personaFormModalInstance.show();
}

/**
 * Abre o modal para editar uma persona existente, preenchendo o formulário.
 * @param {string} personaKey A chave da persona a ser editada.
 */
async function openEditPersonaModal(personaKey) {
    clearPersonaForm();
    hideError(personaFormError);
    personaFormModalLabel.textContent = 'Editar Persona';
    personaKeyInput.disabled = true; // A chave não pode ser editada ao editar
    currentPersonaKeyInput.value = personaKey; // Armazena a chave atual no campo hidden

    try {
        const response = await fetch(`/api/personas/${personaKey}`);
        if (!response.ok) {
            throw new Error(`Erro ao carregar persona: ${response.statusText}`);
        }
        const personaData = await response.json();
        // A chave da persona vem como parte dos dados, mas já temos ela no parâmetro
        populatePersonaForm(personaData, personaKey); 
        personaFormModalInstance.show();
    } catch (error) {
        console.error("Erro ao carregar persona para edição:", error);
        showError(personaListError, `Falha ao carregar persona para edição: ${error.message}`);
    }
}

/**
 * Preenche o formulário de persona com os dados de uma persona existente.
 * @param {object} personaData Os dados da persona.
 * @param {string} personaKey A chave da persona (usada para preencher o input oculto).
 */
function populatePersonaForm(personaData, personaKey) {
    currentPersonaKeyInput.value = personaKey; // Garante que a chave está no campo hidden
    personaKeyInput.value = personaKey; // Preenche o campo visível (desabilitado)
    personaLabelPtInput.value = personaData.label_pt || '';
    personaDescriptionPtInput.value = personaData.description_pt || '';
    personaRoleTemplateInput.value = personaData.role_template || '';

    // Atributos de Comunicação
    const comm = personaData.communication_attributes || {};
    commLanguageInput.value = comm.language || '';
    commVerbosityInput.value = comm.base_verbosity_pt || '';
    commSentenceStructureInput.value = comm.base_sentence_structure_pt || '';
    commVocabularyPreferenceInput.value = comm.base_vocabulary_preference_pt || '';
    commEmojiUsageInput.value = comm.emoji_usage_pt || '';

    // Perfil de Estilo Base
    const styleProfile = personaData.base_style_profile || {};
    // Assume que tone_elements é um array e pega o primeiro objeto
    const tone = styleProfile.tone_elements && styleProfile.tone_elements.length > 0 ? styleProfile.tone_elements[0] : {};
    const formality = styleProfile.formality_element || {};
    styleToneLabelInput.value = tone.label_pt || '';
    styleToneKeywordsInput.value = (tone.keywords_pt || []).join(', ');
    styleFormalityLabelInput.value = formality.label_pt || '';
    styleFormalityNumericInput.value = formality.level_numeric || '';
    styleFormalityGuidanceInput.value = formality.guidance_notes_pt || '';

    // Regras Gerais
    generalDosInput.value = (personaData.general_dos_pt || []).join('\n');
    generalDontsInput.value = (personaData.general_donts_pt || []).join('\n');

    // Few-shot Examples
    fewShotExamplesContainer.innerHTML = ''; // Limpa os existentes
    if (personaData.few_shot_examples && personaData.few_shot_examples.length > 0) {
        personaData.few_shot_examples.forEach(example => {
            addFewShotExampleField(example.input_email, example.output_email);
        });
    } else {
        addFewShotExampleField(); // Adiciona um campo vazio se não houver exemplos
    }
}

/**
 * Limpa o formulário de persona.
 */
function clearPersonaForm() {
    personaForm.reset();
    currentPersonaKeyInput.value = ''; // Limpa a chave oculta
    personaKeyInput.disabled = false; // Habilita para criação
    hideError(personaFormError);
    fewShotExamplesContainer.innerHTML = ''; // Limpa todos os exemplos
    addFewShotExampleField(); // Adiciona um campo vazio por padrão
}

/**
 * Lida com o envio do formulário de persona (criação ou edição).
 */
async function submitPersonaForm(event) {
    event.preventDefault();
    hideError(personaFormError);
    showSpinner(savePersonaSpinner);
    savePersonaBtn.disabled = true;

    const isEditing = !!currentPersonaKeyInput.value;
    const personaKey = isEditing ? currentPersonaKeyInput.value : personaKeyInput.value.trim();

    if (!personaKey) {
        showError(personaFormError, "A chave da persona é obrigatória.");
        hideSpinner(savePersonaSpinner);
        savePersonaBtn.disabled = false;
        return;
    }
    // Validação do formato da chave para novas personas
    if (!isEditing && !/^[a-z0-9_]+$/.test(personaKey)) {
        showError(personaFormError, "A chave da persona deve conter apenas letras minúsculas, números e sublinhados.");
        hideSpinner(savePersonaSpinner);
        savePersonaBtn.disabled = false;
        return;
    }

    // Coleta os dados do formulário
    const fewShotExamples = [];
    fewShotExamplesContainer.querySelectorAll('.few-shot-example-group').forEach(group => {
        const input = group.querySelector('.few-shot-input').value.trim();
        const output = group.querySelector('.few-shot-output').value.trim();
        if (input && output) { // Apenas adiciona se ambos os campos estiverem preenchidos
            fewShotExamples.push({ input_email: input, output_email: output });
        }
    });

    const personaData = {
        label_pt: personaLabelPtInput.value.trim(),
        description_pt: personaDescriptionPtInput.value.trim(),
        role_template: personaRoleTemplateInput.value.trim(),
        communication_attributes: {
            language: commLanguageInput.value.trim(),
            base_verbosity_pt: commVerbosityInput.value.trim(),
            base_sentence_structure_pt: commSentenceStructureInput.value.trim(),
            base_vocabulary_preference_pt: commVocabularyPreferenceInput.value.trim(),
            emoji_usage_pt: commEmojiUsageInput.value.trim()
        },
        base_style_profile: {
            profile_label_pt: styleToneLabelInput.value.trim(), 
            tone_elements: [{
                label_pt: styleToneLabelInput.value.trim(),
                keywords_pt: styleToneKeywordsInput.value.split(',').map(k => k.trim()).filter(k => k)
            }],
            formality_element: {
                label_pt: styleFormalityLabelInput.value.trim(),
                level_numeric: parseInt(styleFormalityNumericInput.value, 10) || 0,
                guidance_notes_pt: styleFormalityGuidanceInput.value.trim()
            }
        },
        general_dos_pt: generalDosInput.value.split('\n').map(s => s.trim()).filter(s => s),
        general_donts_pt: generalDontsInput.value.split('\n').map(s => s.trim()).filter(s => s),
        few_shot_examples: fewShotExamples,
        // learned_knowledge_base NÃO é enviado do frontend para evitar sobrescrever
        // Ele é inicializado no backend na criação ou mantido na edição.
    };

    const url = isEditing ? `/api/personas/${personaKey}` : '/api/personas';
    const method = isEditing ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            // Ao criar, o backend espera {persona_key: "...", persona_data: {...}}
            // Ao editar, o backend espera apenas os dados da persona no corpo
            body: JSON.stringify(isEditing ? personaData : { persona_key: personaKey, persona_data: personaData })
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `Erro HTTP ${response.status}`);
        }

        personaFormModalInstance.hide();
        showSuccessMessage(personaListError, data.message || "Operação realizada com sucesso!");
        fetchAndRenderPersonas(); // Recarrega a lista e o select
        populatePersonaSelect(); // Atualiza o select de personas
    } catch (error) {
        console.error("Erro ao salvar persona:", error);
        showError(personaFormError, `Erro ao salvar persona: ${error.message}`);
    } finally {
        hideSpinner(savePersonaSpinner);
        savePersonaBtn.disabled = false;
    }
}

/**
 * Lida com cliques na tabela de personas (botões de editar/eliminar).
 * @param {Event} event O evento de clique.
 */
function handlePersonaTableClick(event) {
    const editBtn = event.target.closest('.edit-persona-btn');
    const deleteBtn = event.target.closest('.delete-persona-btn');

    if (editBtn) {
        const personaKey = editBtn.dataset.personaKey;
        openEditPersonaModal(personaKey);
    } else if (deleteBtn) {
        const personaKey = deleteBtn.dataset.personaKey;
        const personaName = deleteBtn.dataset.personaName;
        confirmDeletePersona(personaKey, personaName);
    }
}

/**
 * Exibe o modal de confirmação de eliminação de persona.
 * @param {string} key A chave da persona a ser eliminada.
 * @param {string} name O nome de exibição da persona.
 */
function confirmDeletePersona(key, name) {
    personaToDeleteKey = key;
    personaToDeleteNameEl.textContent = name;
    deletePersonaConfirmModalInstance.show();
}

/**
 * Executa a eliminação da persona após a confirmação.
 */
async function deletePersona() {
    if (!personaToDeleteKey) return;

    hideError(personaListError);
    showSpinner(deletePersonaSpinner);
    confirmDeletePersonaBtn.disabled = true;

    try {
        const response = await fetch(`/api/personas/${personaToDeleteKey}`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `Erro HTTP ${response.status}`);
        }

        deletePersonaConfirmModalInstance.hide();
        showSuccessMessage(personaListError, data.message || "Persona eliminada com sucesso!");
        fetchAndRenderPersonas(); // Recarrega a lista e o select
        populatePersonaSelect(); // Atualiza o select de personas
        personaToDeleteKey = null; // Limpa a chave
    } catch (error) {
        console.error("Erro ao eliminar persona:", error);
        showError(personaListError, `Erro ao eliminar persona: ${error.message}`);
    } finally {
        hideSpinner(deletePersonaSpinner);
        confirmDeletePersonaBtn.disabled = false;
    }
}

/**
 * Busca e renderiza a lista de personas na tabela de gestão.
 */
async function fetchAndRenderPersonas() {
    personasTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary">A carregar personas...</td></tr>';
    hideError(personaListError);

    try {
        const response = await fetch('/api/personas');
        if (!response.ok) {
            throw new Error(`Erro ao carregar personas: ${response.statusText}`);
        }
        const personas = await response.json();
        personasTableBody.innerHTML = ''; // Limpa o "A carregar..."

        if (Object.keys(personas).length === 0) {
            personasTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary">Nenhuma persona encontrada.</td></tr>';
            return;
        }

        for (const key in personas) {
            if (personas.hasOwnProperty(key)) {
                const persona = personas[key];
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(key)}</td>
                    <td>${escapeHtml(persona.label_pt || 'N/A')}</td>
                    <td>${escapeHtml(persona.description_pt || 'N/A')}</td>
                    <td class="persona-actions">
                        <button class="btn btn-sm btn-info edit-persona-btn" data-persona-key="${escapeHtml(key)}" title="Editar Persona">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger delete-persona-btn" data-persona-key="${escapeHtml(key)}" data-persona-name="${escapeHtml(persona.label_pt || key)}" title="Eliminar Persona">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </td>
                `;
                personasTableBody.appendChild(tr);
            }
        }
    } catch (error) {
        console.error("Erro ao carregar personas para a tabela:", error);
        showError(personaListError, `Falha ao carregar personas: ${error.message}`);
        personasTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Erro ao carregar personas.</td></tr>';
    }
}

/**
 * Popula o dropdown de seleção de persona no Passo 2.
 * Chamada após qualquer alteração nas personas (criação, edição, eliminação).
 */
async function populatePersonaSelect() {
    personaSelect.innerHTML = ''; // Limpa opções existentes
    personaSelect.disabled = true; // Desabilita enquanto carrega

    try {
        const response = await fetch('/api/personas');
        if (!response.ok) {
            throw new Error(`Erro ao carregar personas para seleção: ${response.statusText}`);
        }
        const personas = await response.json();

        // Adiciona uma opção padrão "Selecione..."
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Selecione uma persona...';
        personaSelect.appendChild(defaultOption);

        if (Object.keys(personas).length === 0) {
            defaultOption.textContent = 'Nenhuma persona carregada';
            draftBtn.disabled = true; // Desabilita o botão de rascunho se não houver personas
            return;
        }

        let firstSelectablePersonaKey = null;
        for (const key in personas) {
            if (personas.hasOwnProperty(key)) {
                const persona = personas[key];
                const option = document.createElement('option');
                option.value = key;
                option.textContent = persona.label_pt || key;
                personaSelect.appendChild(option);
                if (!firstSelectablePersonaKey) { // Seleciona a primeira persona real por padrão
                    firstSelectablePersonaKey = key;
                }
            }
        }
        // Tenta selecionar a primeira persona real ou mantém a opção padrão
        if (firstSelectablePersonaKey) {
            personaSelect.value = firstSelectablePersonaKey;
        } else {
            personaSelect.value = '';
        }
        
        personaSelect.disabled = false;
        draftBtn.disabled = false; // Habilita o botão de rascunho
    } catch (error) {
        console.error("Erro ao popular o select de personas:", error);
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Erro ao carregar personas';
        personaSelect.appendChild(option);
        personaSelect.disabled = true;
        draftBtn.disabled = true;
    }
}