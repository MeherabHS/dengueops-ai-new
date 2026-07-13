import { GraduationCap, University } from "lucide-react";

const AUTHORS = [
  {
    name: "Meherab Hossain Shafin",
    initials: "MHS",
    department: "Department of Software Engineering",
    university: "Daffodil International University",
    role: "Author",
    color: "from-sky-500 to-[#0f172a]",
    ringColor: "ring-sky-300",
  },
  {
    name: "Jannatul Tazri Aohona",
    initials: "JTA",
    department: "Department of Software Engineering",
    university: "Daffodil International University",
    role: "Author",
    color: "from-violet-500 to-[#0f172a]",
    ringColor: "ring-violet-300",
  },
];

interface Props {
  compact?: boolean;
}

export default function AuthorsSection({ compact = false }: Props) {
  return (
    <section className={compact ? "mt-10" : "mt-14"}>
      {!compact && (
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-1">
            Made By
          </p>
          <h2 className="text-2xl font-bold text-slate-900">Authors</h2>
          <p className="text-sm text-slate-500 mt-1">
            IEEE ICADHI Project Showcase · Daffodil International University
          </p>
        </div>
      )}

      {compact && (
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-4">
          Made By
        </p>
      )}

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {AUTHORS.map((author) => (
          <div
            key={author.name}
            className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            {/* Avatar placeholder */}
            <div
              className={`
                flex-shrink-0 h-16 w-16 rounded-full bg-gradient-to-br ${author.color}
                flex items-center justify-center
                ring-2 ${author.ringColor} ring-offset-2
                shadow-md
              `}
            >
              <span className="text-lg font-extrabold text-white tracking-tight">
                {author.initials}
              </span>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-slate-900 leading-snug">{author.name}</p>
              <span className="inline-block mt-0.5 mb-2 rounded-full bg-sky-100 border border-sky-200 px-2 py-0.5 text-[10px] font-semibold text-sky-700">
                {author.role}
              </span>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <GraduationCap className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
                  <span>{author.department}</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <University className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
                  <span className="font-medium">{author.university}</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <p className="mt-3 text-[10px] text-slate-400 text-center">
        Avatar images are placeholders. · DengueOps AI · IEEE ICADHI 2025
      </p>
    </section>
  );
}
