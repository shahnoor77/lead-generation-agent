"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { getUserId, clearCredentials, isLoggedIn } from "@/lib/auth";

const nav = [
  { href: "/runs",     label: "Runs" },
  { href: "/runs/new", label: "New Run" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();

  const userLabel = useMemo(() => {
    if (path.startsWith("/login")) return null;
    if (!isLoggedIn()) return null;
    const uid = getUserId();
    if (!uid) return null;
    return uid.length > 12 ? `${uid.slice(0, 8)}…${uid.slice(-4)}` : uid;
  }, [path]);

  useEffect(() => {
    if (path.startsWith("/login")) return;

    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
  }, [path, router]);

  function logout() {
    clearCredentials();
    router.push("/login");
  }

  if (path.startsWith("/login")) {
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
          <span suppressHydrationWarning className="text-xs text-gray-400 font-mono">{userLabel ?? ""}</span>
          <button onClick={logout} className="text-xs text-gray-500 hover:text-red-600">
            Sign out
          </button>
        </div>
      </header>
      <main className="px-6 py-6 max-w-7xl mx-auto">{children}</main>
    </div>
  );
}
