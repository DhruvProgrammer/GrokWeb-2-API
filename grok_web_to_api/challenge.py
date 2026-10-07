"""x-statsig-id challenge signer.

Reverse-engineered from the grok.com web client. The header is a 70-byte
binary blob that the browser computes by:

  1. Take a 49-byte static fingerprint (extracted once from the bundle)
  2. Append 20 random bytes
  3. Append a single constant trailer byte
  4. XOR the last 21 bytes against SHA-256(counter || nonce)
  5. base64-encode the result

The counter is "seconds since 2023-05-01 00:00:00 UTC" - the epoch the
obfuscated clock in the browser client uses. Using any other epoch makes
the upstream reject the request with HTTP 403.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

# Grok's obfuscated clock epoch.
_EPOCH = datetime(2023, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


@dataclass
class ChallengeSigner:
    """Builds per-request x-statsig-id headers.

    Cheap to construct; safe to call .sign() concurrently from many
    async tasks - it does not share mutable state.
    """

    header: bytes  # 49 bytes
    trailer: int   # 0..255

    @classmethod
    def from_hex(cls, header_hex: str, trailer: int) -> "ChallengeSigner":
        """Parse the env-var form of the challenge constants."""
        try:
            raw = bytes.fromhex(header_hex)
        except ValueError as e:
            raise ValueError(f"invalid CHALLENGE_HEADER_HEX: {e}") from e
        if len(raw) != 49:
            raise ValueError(
                f"CHALLENGE_HEADER_HEX must be 49 bytes ({98} hex chars), got {len(raw)}"
            )
        if not 0 <= trailer <= 255:
            raise ValueError(f"CHALLENGE_TRAILER must be 0..255, got {trailer}")
        return cls(header=raw, trailer=trailer)

    def sign(self) -> str:
        """Return a fresh x-statsig-id header value."""
        counter = int((datetime.now(timezone.utc) - _EPOCH).total_seconds())

        # 20 random bytes per request - the browser does the same.
        nonce = os.urandom(20)

        # 70 bytes: header(49) || nonce(20) || trailer(1).
        out = bytearray(self.header)
        out.extend(nonce)
        out.append(self.trailer)

        # XOR-pad: hash(counter || nonce) gives 32 bytes; we XOR the last
        # 21 bytes of `out` with the first 21 bytes of the hash.
        h = hashlib.sha256(counter.to_bytes(8, "big") + nonce).digest()
        for i in range(21):
            out[49 + i] ^= h[i]

        return base64.b64encode(bytes(out)).decode("ascii")

    def summary(self) -> str:
        """One-line diagnostic for startup logs (no secret bytes leaked)."""
        return f"header={len(self.header)} bytes, trailer={self.trailer}"