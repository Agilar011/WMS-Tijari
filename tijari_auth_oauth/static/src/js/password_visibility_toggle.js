/** @odoo-module **/

function setupPasswordToggle(button) {
    const inputId = button.dataset.passwordTarget;
    const input = inputId ? document.getElementById(inputId) : null;
    const icon = button.querySelector("i");

    if (!input || input.dataset.passwordToggleReady) {
        return;
    }
    input.dataset.passwordToggleReady = "1";

    button.addEventListener("click", () => {
        const showPassword = input.type === "password";
        input.type = showPassword ? "text" : "password";
        button.setAttribute("aria-pressed", showPassword ? "true" : "false");
        button.setAttribute("aria-label", showPassword ? "Hide password" : "Show password");
        icon?.classList.toggle("fa-eye", !showPassword);
        icon?.classList.toggle("fa-eye-slash", showPassword);
        input.focus();
    });
}

function setupPasswordToggles() {
    document.querySelectorAll(".o_tijari_toggle_password").forEach(setupPasswordToggle);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupPasswordToggles);
} else {
    setupPasswordToggles();
}
