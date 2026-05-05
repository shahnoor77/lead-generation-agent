"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken, clearToken, isLoggedIn } from "@/lib/auth";

const nav = [
  { href: "/runs",     label: "Runs" },
  { href: "/runs/new", label: "New Run" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    // Skip auth check on login/signup pages
    if (path.startsWith("/login") || path.startsWith("/signup")) return;

    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }

    // Decode email from token payload (no network call needed)
    try {
      const token = getToken()!;
      const payload = JSON.parse(atob(token.split(".")[1]));
      setEmail(payload.email ?? null);
    } catch {
      setEmail(null);
    }
  }, [path]);

  function logout() {
    clearToken();
    router.push("/login");
  }

  // Don't render shell on auth pages
  if (path.startsWith("/login") || path.startsWith("/signup")) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-8">
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
        </div>
        <div className="flex items-center gap-3">
          {email && <span className="text-xs text-gray-400">{email}</span>}
          <button onClick={logout} className="text-xs text-gray-500 hover:text-red-600">
            Sign out
          </button>
        </div>
      </header>
      <main className="px-6 py-6 max-w-7xl mx-auto">{children}</main>
    </div>
  );
}
