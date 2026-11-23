import { useState, type FormEvent } from "react";
import { api } from "../api";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/auth/login", { method: "POST", json: { username: "admin", password } });
      onLogin();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form className="card login" onSubmit={submit}>
      <h1>AI Dev Environment</h1>
      <p className="muted">Log in as admin. On first boot the one-time password is shown on the VM console and SSH banner.</p>
      <label>
        Password
        <input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit">Log in</button>
    </form>
  );
}
