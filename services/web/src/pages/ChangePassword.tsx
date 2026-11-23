import { useState, type FormEvent } from "react";
import { api } from "../api";

export default function ChangePassword({ onDone, firstLogin }: { onDone: () => void; firstLogin?: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/auth/password", { method: "POST", json: { current, new: next } });
      setMsg("Password changed.");
      onDone();
    } catch (err) {
      setMsg((err as Error).message);
    }
  };
  return (
    <form className={firstLogin ? "card login" : "card"} onSubmit={submit}>
      <h2>{firstLogin ? "Choose your admin password" : "Change password"}</h2>
      {firstLogin && <p className="muted">The one-time password stops working once you set your own.</p>}
      <label>
        Current password
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </label>
      <label>
        New password (10+ characters)
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      {msg && <p>{msg}</p>}
      <button type="submit">Save</button>
    </form>
  );
}
