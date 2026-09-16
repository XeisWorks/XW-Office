import { useState, type FormEvent } from "react";
import { setToken } from "../api/client";

interface TokenGateProps {
  onSaved: () => void;
}

/**
 * The Bootstrap-Token is a deliberate, documented transitional auth mechanism
 * (see docs/product_hub/), not a real login system - this is a minimal gate that
 * asks for it once and stores it in localStorage for subsequent visits/installs.
 */
export default function TokenGate({ onSaved }: TokenGateProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    setToken(trimmed);
    onSaved();
  }

  return (
    <div className="token-gate">
      <form className="token-gate-card" onSubmit={handleSubmit}>
        <h1>XW Product Hub</h1>
        <p>Zugriffstoken erforderlich (dasselbe wie für die Content-Studio-API).</p>
        <input
          type="password"
          autoFocus
          placeholder="Bearer-Token"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" disabled={!value.trim()}>
          Anmelden
        </button>
      </form>
    </div>
  );
}
