// extract-challenge.js
//
// Run this in your browser console on https://grok.com after you've
// logged in. It captures the x-statsig-id header values and prints them
// in the .env-ready form.
//
// Usage:
//   1. Log into https://grok.com
//   2. Open DevTools (F12) -> Console
//   3. Paste this entire script, press Enter
//   4. Copy the three output lines into your .env file
//
// The script monkey-patches crypto.subtle.digest briefly so we can read
// what the web client is hashing, then restores everything. Safe to run.

(async () => {
    let capturedSuffix;
    const origDigest = crypto.subtle.digest.bind(crypto.subtle);
    const origRandom = Math.random;
    const origNow = Date.now;
    // Pin the time and randomness so the hash is deterministic.
    Math.random = () => 0;
    Date.now = () => 1e12;
    crypto.subtle.digest = async (algo, data) => {
        const s = new TextDecoder().decode(data);
        capturedSuffix = s;
        return origDigest(algo, data);
    };

    try {
        // Trigger one POST by calling the same internal endpoint.
        const r = await fetch('https://grok.com/rest/app-chat/x', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({}),
        });
        const statsigID = r.headers.get('x-statsig-id') || '';
        if (!statsigID) {
            console.error('Could not extract x-statsig-id - Grok may have changed the wire format.');
            return;
        }
        const bytes = Uint8Array.from(atob(statsigID), c => c.charCodeAt(0));
        const headerHex = Array.from(bytes.slice(0, 49))
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
        const suffix = (capturedSuffix || '').split('!').slice(2).join('!').replace(/^-?\d+/, '');
        const trailer = bytes[69];

        console.log('--- paste these into your .env ---');
        console.log(`CHALLENGE_HEADER_HEX=${headerHex}`);
        console.log(`CHALLENGE_SUFFIX=${suffix}`);
        console.log(`CHALLENGE_TRAILER=${trailer}`);
        console.log('--- end ---');
    } finally {
        Math.random = origRandom;
        Date.now = origNow;
        crypto.subtle.digest = origDigest;
    }
})();
