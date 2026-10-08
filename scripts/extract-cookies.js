// extract-cookies.js
//
// Paste in DevTools Console on https://grok.com AFTER signing in.
//
// What it does:
//   1. Tries to read sso + sso-rw from document.cookie
//   2. If found, copies them to your clipboard via navigator.clipboard
//   3. If HttpOnly (browser blocks JS from reading them), it falls
//      back to grabbing them from the Network tab of any XHR the page
//      has already made — see the helper below.

(async function () {
    function getCookie(name) {
        const all = document.cookie.split("; ");
        for (const c of all) {
            const i = c.indexOf("=");
            const k = i === -1 ? c : c.slice(0, i);
            if (k === name) return decodeURIComponent(c.slice(i + 1));
        }
        return null;
    }

    async function copy(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // Fallback: select+copy via a hidden textarea.
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand("copy"); } catch (_) { return false; }
            finally { ta.remove(); }
            return true;
        }
    }

    let sso = getCookie("sso");
    let ssorw = getCookie("sso-rw");

    if (sso && ssorw) {
        const env = `GROK_SSO_COOKIE=${sso}\nGROK_SSO_RW_COOKIE=${ssorw}`;
        const ok = await copy(env);
        if (ok) {
            console.log("✅ Copied to clipboard:\n" + env);
        } else {
            console.log("⚠️ Clipboard blocked. Here are the values:\n" + env);
        }
        return;
    }

    // ---- HttpOnly fallback ----
    // document.cookie can't see HttpOnly cookies. Trick: read them
    // out of the Cookie request header on any in-flight request the
    // page made. We override fetch + XHR briefly to log the next one.
    console.warn("⚠️  sso / sso-rw are HttpOnly — JavaScript can't read them.");
    console.warn("Two ways to get them on your clipboard:");
    console.warn("");
    console.warn("A) Easiest: in Application > Cookies > https://grok.com,");
    console.warn("   double-click the Value of sso and sso-rw, Ctrl+C each.");
    console.warn("");
    console.warn("B) Use the helper below — click around on grok.com and");
    console.warn("   the next time a request fires, the helper grabs the");
    console.warn("   cookie from its headers and copies to clipboard.");

    window.captureNextCookie = async function () {
        return new Promise((resolve) => {
            const origFetch = window.fetch;
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;

            let captured = null;
            const grab = async (cookieHeader) => {
                if (!cookieHeader || captured) return;
                const m = cookieHeader.match(/(?:^|;\s*)(sso-rw|sso)=([^;]+)/g);
                if (!m) return;
                const obj = {};
                for (const part of m) {
                    const [k, v] = part.split("=");
                    obj[k.trim()] = v;
                }
                if (obj.sso && obj["sso-rw"]) {
                    captured = obj;
                    const env = `GROK_SSO_COOKIE=${obj.sso}\nGROK_SSO_RW_COOKIE=${obj["sso-rw"]}`;
                    const ok = await copy(env);
                    console.log(ok ? "✅ Copied to clipboard:\n" + env : "⚠️ " + env);
                    window.fetch = origFetch;
                    XMLHttpRequest.prototype.open = origOpen;
                    XMLHttpRequest.prototype.send = origSend;
                    resolve(obj);
                }
            };

            window.fetch = function (...args) {
                const init = args[1] || {};
                const headers = new Headers(init.headers || {});
                grab(headers.get("cookie") || "").then(() => {
                    if (captured) return;
                });
                return origFetch.apply(this, args);
            };

            XMLHttpRequest.prototype.open = function (method, url) {
                this._url = url;
                return origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function () {
                const xhr = this;
                const interval = setInterval(() => {
                    try {
                        const h = xhr.getRequestHeader("Cookie") || xhr.getResponseHeader("Set-Cookie");
                        if (h) grab(h);
                    } catch (_) {}
                }, 50);
                xhr.addEventListener("readystatechange", () => {
                    if (xhr.readyState === 4) clearInterval(interval);
                });
                return origSend.apply(this, arguments);
            };

            setTimeout(() => {
                if (!captured) {
                    console.log("⌛ Waiting for the next request... click anywhere on grok.com to trigger one.");
                }
            }, 100);
        });
    };

    console.warn("→ Type:  captureNextCookie()    then click around the page");
})();
