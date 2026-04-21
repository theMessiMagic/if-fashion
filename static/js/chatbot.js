const toggle = document.getElementById("chatbot-toggle");
const box = document.getElementById("chatbot-box");
const input = document.getElementById("chatbot-input");
const messages = document.getElementById("chatbot-messages");
const resetBtn = document.getElementById("chatbot-reset");

let initialized = false;
let awaitingSupportMessage = false;
let activeCategory = "";
let activeTicketId = "";
let lastSeenMessageId = 0;
const ticketPollers = new Map();

function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
}

function clearActionRows() {
    if (!messages) return;
    messages.querySelectorAll(".chat-menu-actions").forEach((el) => el.remove());
}

function createRow(sender, text, cls = "") {
    const row = document.createElement("div");
    row.className = `chat-row ${cls}`.trim();

    const senderEl = document.createElement("b");
    senderEl.textContent = `${sender}: `;
    row.appendChild(senderEl);

    const textEl = document.createElement("span");
    textEl.textContent = text;
    row.appendChild(textEl);
    return row;
}

function addMessage(sender, text, cls = "") {
    const row = createRow(sender, text, cls);
    messages.appendChild(row);
    scrollToBottom();
}

function addBot(text) {
    addMessage("Assistant", text, "bot");
}

function addUser(text) {
    addMessage("You", text, "user");
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function typeBot(text, delay = 450) {
    const typing = document.createElement("div");
    typing.className = "chat-typing";
    typing.textContent = "Concierge is preparing your response...";
    messages.appendChild(typing);
    scrollToBottom();

    await sleep(delay);
    typing.remove();
    addBot(text);
}

function addActionButtons(actions) {
    const wrap = document.createElement("div");
    wrap.className = "chat-actions chat-menu-actions";

    actions.forEach((action) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chat-option-btn";
        btn.textContent = action.label;
        btn.onclick = () => handleAction(action.key, action.label);
        wrap.appendChild(btn);
    });

    messages.appendChild(wrap);
    scrollToBottom();
}

function addLinkButtons(links) {
    const wrap = document.createElement("div");
    wrap.className = "chat-actions chat-link-actions";

    links.forEach((item) => {
        const link = document.createElement("a");
        link.className = "chat-option-btn chat-link-btn";
        link.href = item.href;
        link.textContent = item.label;
        wrap.appendChild(link);
    });

    messages.appendChild(wrap);
    scrollToBottom();
}

function showMiniMenu() {
    clearActionRows();
    addActionButtons([
        { key: "menu", label: "Menu" },
        { key: "track", label: "Track" },
        { key: "support", label: "Support" },
    ]);
}

function showMainMenu() {
    clearActionRows();
    addActionButtons([
        { key: "track", label: "Track My Request" },
        { key: "new_order", label: "Start A New Design Brief" },
        { key: "careers", label: "Career Application Support" },
        { key: "process", label: "Services & Workflow" },
        { key: "faq", label: "FAQs" },
        { key: "support", label: "Connect With Human Support" },
    ]);
}

function showFaqMenu() {
    clearActionRows();
    addActionButtons([
        { key: "faq_timeline", label: "Delivery Timeline" },
        { key: "faq_pricing", label: "Pricing Policy" },
        { key: "faq_status", label: "Status Guide" },
        { key: "faq_docs", label: "Required Documents" },
        { key: "faq_contact", label: "Contact Channels" },
        { key: "menu", label: "Back to Main Menu" },
    ]);
}

function buildSupportPrefill(issueText) {
    return `[${activeCategory || "general"}] ${issueText}`;
}

async function createSupportTicket(issueText) {
    try {
        const res = await fetch("/chat/ticket", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: issueText, category: activeCategory || "general" }),
        });

        const data = await res.json();
        if (!res.ok) {
            await typeBot(data.error || "I could not open a support ticket right now. Please retry in a moment.");
            return;
        }

        await typeBot(`${data.reply} Your ticket reference is ${data.ticket_id}.`, 350);
        await typeBot("You can keep chatting here. I will instantly display every new support response.", 350);
        activeTicketId = data.ticket_id;
        lastSeenMessageId = 0;
        startTicketPolling(data.ticket_id);
        await typeBot("Tip: type 'menu' anytime if you want quick options.", 250);
        showMiniMenu();
    } catch (_err) {
        await typeBot("There seems to be a network issue while opening your ticket. Please try again.", 300);
    }
}

function startTicketPolling(ticketId) {
    if (!ticketId || ticketPollers.has(ticketId)) return;

    const poller = setInterval(async () => {
        try {
            const res = await fetch(`/chat/ticket/${ticketId}/messages?after_id=${lastSeenMessageId}`);
            const data = await res.json();
            if (!res.ok) return;

            if (Array.isArray(data.messages) && data.messages.length > 0) {
                data.messages.forEach((msg) => {
                    lastSeenMessageId = Math.max(lastSeenMessageId, Number(msg.id) || 0);
                    if (msg.sender === "admin") {
                        addBot(`Support Team (${ticketId}): ${msg.message}`);
                    }
                });
            }

            if (data.status === "closed") {
                addBot(`Ticket ${ticketId} has been closed. If you need more help, choose support again to open a fresh conversation.`);
                clearInterval(poller);
                ticketPollers.delete(ticketId);
                if (activeTicketId === ticketId) {
                    activeTicketId = "";
                }
            }
        } catch (_err) {
            // Silent retry.
        }
    }, 10000);

    ticketPollers.set(ticketId, poller);
}

async function sendMessageToTicket(ticketId, message) {
    try {
        const res = await fetch("/chat/ticket/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticket_id: ticketId, message }),
        });
        const data = await res.json();
        if (!res.ok) {
            await typeBot(data.error || "I could not send this message to support.");
            return;
        }
        await typeBot("Perfect. Your message has been delivered to the support team.", 250);
    } catch (_err) {
        await typeBot("Network issue detected. Your message could not be delivered.");
    }
}

async function handleAction(key, label = "") {
    if (label) addUser(label);
    awaitingSupportMessage = false;

    switch (key) {
        case "track":
            activeCategory = "tracking";
            await typeBot("You can view real-time progress using your request ID.");
            addLinkButtons([{ label: "Open Tracking Page", href: "/track" }]);
            await typeBot("Pro tip: keep your IF- or EMP- code handy for faster lookup.");
            showMiniMenu();
            break;

        case "new_order":
            activeCategory = "design_order";
            await typeBot("Great choice. Start your custom design brief from our client request form.");
            addLinkButtons([{ label: "Open Customer Contact", href: "/customer_contact" }]);
            await typeBot("Upload a clear reference and concise notes for the fastest review cycle.");
            showMiniMenu();
            break;

        case "careers":
            activeCategory = "careers";
            await typeBot("Please apply through our careers form using valid phone and Aadhaar details.");
            addLinkButtons([{ label: "Open Careers Page", href: "/careers" }]);
            await typeBot("After submission, track your hiring progress using the EMP request ID.");
            showMiniMenu();
            break;

        case "process":
            activeCategory = "process";
            await typeBot("Workflow: Design brief submitted -> Expert review -> Approval or decline -> Production updates.");
            await typeBot("Need personalized help on any step? Choose human support.");
            showMiniMenu();
            break;

        case "faq":
            activeCategory = "faq";
            await typeBot("Choose a topic below and I will guide you instantly.");
            showFaqMenu();
            break;

        case "faq_timeline":
            await typeBot("Delivery timeline depends on design complexity and active queue. The tracker always shows your latest status.");
            showFaqMenu();
            break;

        case "faq_pricing":
            await typeBot("Pricing is finalized only after technical review and design approval.");
            showFaqMenu();
            break;

        case "faq_status":
            await typeBot("Status guide: In Review = under evaluation, Approved = accepted for next phase, Declined = not approved.");
            showFaqMenu();
            break;

        case "faq_docs":
            await typeBot("For careers, please provide valid phone and Aadhaar details. Optional supporting documents are accepted.");
            showFaqMenu();
            break;

        case "faq_contact":
            await typeBot("Support channels: Phone/WhatsApp 9474588857");
            showFaqMenu();
            break;

        case "support":
            activeCategory = activeCategory || "support";
            if (activeTicketId) {
                await typeBot(`Active support ticket: ${activeTicketId}. Send your follow-up and I will forward it immediately.`);
            } else {
                awaitingSupportMessage = true;
                await typeBot("Please share your issue in one detailed message. I will open a support conversation right away.");
            }
            break;

        case "menu":
            await typeBot("Here are the main options.");
            showMainMenu();
            break;

        default:
            await typeBot("I could not map that request clearly. Type 'menu' for options, or tell me what you need in one line.");
            showMiniMenu();
    }
}

function clearConversation() {
    messages.innerHTML = "";
    awaitingSupportMessage = false;
    activeCategory = "";
    activeTicketId = "";
    lastSeenMessageId = 0;
    typeBot("Conversation reset. Tell me what you need, or type 'menu' for options.", 250).then(showMiniMenu);
}

async function handleTextInput(text) {
    const normalized = text.toLowerCase().trim();

    if (awaitingSupportMessage) {
        awaitingSupportMessage = false;
        await createSupportTicket(text);
        return;
    }

    if (activeTicketId && normalized !== "menu" && normalized !== "options" && normalized !== "reset" && normalized !== "clear") {
        await sendMessageToTicket(activeTicketId, text);
        return;
    }

    if (normalized === "menu" || normalized === "options") {
        await handleAction("menu");
        return;
    }

    if (normalized === "reset" || normalized === "clear") {
        clearConversation();
        return;
    }

    if (normalized.includes("track")) {
        await handleAction("track");
        return;
    }
    if (normalized.includes("order") || normalized.includes("upload") || normalized.includes("design")) {
        await handleAction("new_order");
        return;
    }
    if (normalized.includes("career") || normalized.includes("job")) {
        await handleAction("careers");
        return;
    }
    if (normalized.includes("support") || normalized.includes("human") || normalized.includes("agent")) {
        await handleAction("support");
        return;
    }
    if (normalized.includes("faq") || normalized.includes("price") || normalized.includes("cost")) {
        await handleAction("faq");
        return;
    }

    await typeBot("For the quickest support experience, choose one of the guided options.");
    await typeBot("Type 'menu' if you want the full list of options.", 250);
    showMiniMenu();
}

if (toggle) {
    toggle.onclick = () => {
        const isOpen = box.style.display === "block";
        box.style.display = isOpen ? "none" : "block";

        if (!initialized && !isOpen) {
            initialized = true;
            typeBot("Welcome to I.F Fashion Concierge Desk.", 250)
                .then(() => typeBot("I can assist with design requests, tracking, careers, FAQs, and live support tickets.", 350))
                .then(() => typeBot("Ask your question, or type 'menu' for quick options.", 250))
                .then(showMiniMenu);
        }
    };
}

if (resetBtn) {
    resetBtn.addEventListener("click", clearConversation);
}

if (input) {
    input.addEventListener("keypress", async (e) => {
        if (e.key !== "Enter") return;
        const text = input.value.trim();
        if (!text) return;

        addUser(text);
        input.value = "";
        await handleTextInput(text);
    });
}
