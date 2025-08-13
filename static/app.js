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
const feedbackTypeSelectEl = document.getElementById('feedbackTypeSelect');
const feedbackUserExplanationEl = document.getElementById('feedbackUserExplanation');
const submitFeedbackBtn = document.getElementById('submitFeedbackBtn');
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

// --- Estado da Aplicação ---
let currentStep = 1; // 1: Selecionar Email, 2: Analisar, 3: Compor
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
    }
    if (sendEmailConfirmModalEl) {
        sendEmailConfirmModalInstance = new bootstrap.Modal(sendEmailConfirmModalEl);
    }
    populateFeedbackTypes();

    // Adiciona todos os event listeners da aplicação principal
    analyzeBtn.addEventListener('click', handleAnalysisAndAdvance); // Handler para o botão 'Processar & Próximo Passo'
    draftBtn.addEventListener('click', handleDrafting);
    copyDraftBtn.addEventListener('click', handleCopy);
    userInputsSection.addEventListener('click', handleGuidanceSuggestion);
    generatedDraftEl.addEventListener('select', handleTextSelection);
    generatedDraftEl.addEventListener('mouseup', handleTextSelection);
    generatedDraftEl.addEventListener('keyup', handleTextSelection);
    document.addEventListener('click', handleDeselection);
    refinementControlsEl.addEventListener('click', handleRefinement);
    feedbackBtn.addEventListener('click', openFeedbackModal);
    submitFeedbackBtn.addEventListener('click', submitFeedback);
    fetchEmailsBtn.addEventListener('click', fetchAndRenderEmails);
    emailListEl.addEventListener('click', handleEmailClick);
    sendEmailBtn.addEventListener('click', handleSendEmail);

    // Event listeners para navegação entre passos
    backToSelectBtn.addEventListener('click', () => showStep(1));
    backToAnalysisBtn.addEventListener('click', () => showStep(2));

    // Event listener para habilitar/desabilitar o botão de análise do Passo 1
    originalEmailEl.addEventListener('input', () => {
        analyzeBtn.disabled = originalEmailEl.value.trim() === '';
    });

    // Event listeners para o novo modal de confirmação de envio
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

    // Inicia a aplicação no primeiro passo
    showStep(1);
    fetchAndRenderEmails();
}

/**
 * Controla a exibição dos passos do assistente e atualiza o indicador de progresso.
 * @param {number} stepNumber O número do passo a ser exibido (1, 2 ou 3).
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
        const requiredAttr = '';
        const requiredFeedback = !isGeneral ? '<div class="invalid-feedback">Por favor, forneça uma diretriz para este ponto.</div>' : '';
        const directionRadiosHTML = !isGeneral ? `<div class="mb-2 guidance-direction-group"><span class="form-label-sm d-block mb-1">Vetor de Resposta Rápida:</span><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-sim" value="sim"><label class="form-check-label" for="direction-${index}-sim">Afirmativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-nao" value="nao"><label class="form-check-label" for="direction-${index}-nao">Negativo</label></div><div class="form-check form-check-inline"><input class="form-check-input" type="radio" name="direction-${index}" id="direction-${index}-outro" value="outro" checked><label class="form-check-label" for="direction-${index}-outro">Neutro/Detalhado</label></div></div>` : '';
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
            if(data.context_analysis && data.context_analysis.error) { errorMsg += ` (Erro na pré-análise de contexto: ${escapeHtml(data.context_analysis.error)})`; }
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

function populateFeedbackTypes() {
    const feedbackTypes = [
        { value: "", text: "Selecione o tipo de feedback..." },
        { value: "ERRO_FACTUAL", text: "Erro Factual na Resposta" },
        { value: "TOM_ESTILO_INADEQUADO", text: "Tom/Estilo Inadequado para o Contexto" },
        { value: "INFORMACAO_IMPORTANTE_OMITIDA", text: "Informação Importante Foi Omitida" },
        { value: "INFORMACAO_EXCESSIVA_IRRELEVANTE", text: "Informação Excessiva ou Irrelevante" },
        { value: "MA_INTERPRETACAO_PEDIDO_ORIGINAL", text: "Má Interpretação do Pedido do Remetente" },
        { value: "PREFERENCIA_FORMATO_RESPOSTA", text: "Preferência de Formato da Resposta" },
        { value: "FALHA_NA_APLICACAO_DIRETRIZ", text: "Não Seguiu Bem Minhas Diretrizes" },
        { value: "COMPORTAMENTO_IA_INESPERADO", text: "Comportamento da IA Inesperado/Não Ideal" },
        { value: "SUGESTAO_MELHORIA_PROCESSO_IA", text: "Sugestão para Melhorar Processo Geral da IA" },
        { value: "OUTRO", text: "Outro (detalhar na explicação)" }
    ];
    if (feedbackTypeSelectEl) {
        feedbackTypeSelectEl.innerHTML = '';
        feedbackTypes.forEach(type => {
            const option = document.createElement('option');
            option.value = type.value;
            option.textContent = type.text;
            feedbackTypeSelectEl.appendChild(option);
        });
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

    feedbackOriginalResponseEl.value = lastGeneratedDraftForFeedback;
    feedbackUserCorrectionEl.value = '';
    feedbackTypeSelectEl.value = '';
    feedbackUserExplanationEl.value = '';

    if (feedbackModalInstance) {
        feedbackModalInstance.show();
    }
}

async function submitFeedback() {
    const selectedPersona = personaSelect.value;
    const userCorrection = feedbackUserCorrectionEl.value.trim();
    const feedbackCategory = feedbackTypeSelectEl.value;

    if (!selectedPersona) { showError(feedbackErrorModalEl, "Nenhuma persona selecionada. Não é possível submeter feedback."); return; }
    if (!userCorrection) { showError(feedbackErrorModalEl, "Por favor, forneça a sua versão correta ou o que esperava."); feedbackUserCorrectionEl.focus(); return; }
    if (!feedbackCategory) { showError(feedbackErrorModalEl, "Por favor, selecione um tipo de feedback."); feedbackTypeSelectEl.focus(); return; }
    hideError(feedbackErrorModalEl);
    showSpinner(feedbackSubmitSpinner);
    submitFeedbackBtn.disabled = true;

    const payload = {
        persona_name: selectedPersona,
        ai_original_response: feedbackOriginalResponseEl.value,
        user_corrected_output: userCorrection,
        feedback_category: feedbackCategory,
        user_explanation: feedbackUserExplanationEl.value.trim(),
        interaction_context: currentDraftContext
    };

    try {
        const response = await fetch('/submit_feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            throw new Error(data.error || `Erro HTTP ${response.status}`);
        }

        if(feedbackModalInstance) feedbackModalInstance.hide();
        showSuccessMessage(feedbackSuccessMessageEl, "Feedback submetido com sucesso! A IA agradece a sua ajuda para aprender.");

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
