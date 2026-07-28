import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import SignInForm from "@/components/auth/SignInForm";
import { sessionCookieName, verifySessionToken } from "@/lib/auth/session";

export default async function SignInPage() {
  const store = await cookies();
  const session = await verifySessionToken(store.get(sessionCookieName())?.value);
  if (session) redirect("/forecast");
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-md items-center px-4 py-12">
      <section className="w-full rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wider text-accent">Super User</p>
        <h1 className="mt-2 text-2xl font-bold text-primary">Sign in to DengueOps</h1>
        <p className="mt-2 text-sm text-secondary">Authority-changing workflows require an authenticated Super User session.</p>
        <SignInForm />
      </section>
    </main>
  );
}
