const toggle = document.getElementById("chatbot-toggle");
const box = document.getElementById("chatbot-box");
const input = document.getElementById("chatbot-input");
const messages = document.getElementById("chatbot-messages");

if (toggle) {
    toggle.onclick = () => {
        box.style.display = box.style.display === "block" ? "none" : "block";
    };
}

function addMsg(sender, text) {
    messages.innerHTML += `<div><b>${sender}:</b> ${text}</div>`;
    messages.scrollTop = messages.scrollHeight;
}

if (input) {
    input.addEventListener("keypress", async function (e) {
        if (e.key === "Enter") {
            const text = input.value.trim();
            if (!text) return;

            addMsg("You", text);
            input.value = "";

            const res = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });

            const data = await res.json();
            addMsg("Bot", data.reply);
        }
    });
}
