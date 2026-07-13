import { AlertTriangle } from "lucide-react";

export default function ErrorState({ title, description }: { title: string; description: string }) {
  return <div className="flex gap-3 rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-destructive" role="alert">
    <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /><div><p className="font-semibold">{title}</p><p className="mt-1 text-sm">{description}</p></div>
  </div>;
}
