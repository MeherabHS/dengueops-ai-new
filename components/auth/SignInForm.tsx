"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

export default function SignInForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const response = await fetch("/api/auth/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
      }),
    });
    if (!response.ok) {
      setError(response.status === 503 ? "Authentication is unavailable." : "Invalid username or password.");
      setPending(false);
      return;
    }
    router.replace("/forecast");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="mt-6 space-y-4">
      <div>
        <label htmlFor="username" className="text-sm font-medium text-primary">Username</label>
        <input id="username" name="username" autoComplete="username" required maxLength={128} className="mt-2 w-full rounded-lg border border-border bg-surface-muted px-3 py-2 text-primary outline-none focus:ring-2 focus:ring-focus" />
      </div>
      <div>
        <label htmlFor="password" className="text-sm font-medium text-primary">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required maxLength={1024} className="mt-2 w-full rounded-lg border border-border bg-surface-muted px-3 py-2 text-primary outline-none focus:ring-2 focus:ring-focus" />
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      <button type="submit" disabled={pending} className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-60">
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
