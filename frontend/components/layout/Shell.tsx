"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { href: "/runs",     label: "Runs" },
  { href: "/runs/new", label: "New Run" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-8">
        <span className="font-semibold text-gray-900 text-sm tracking-tight">Lead Ops</span>
        <nav className="flex gap-4">
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`text-sm ${path.startsWith(n.href) ? "text-blue-600 font-medium" : "text-gray-500 hover:text-gray-800"}`}
            >
              {n.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="px-6 py-6 max-w-7xl mx-auto">{children}</main>
    </div>
  );
}
