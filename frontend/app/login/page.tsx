"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveCredentials } from "@/lib/auth";
import { ErrorMsg } from "@/components/ui/ErrorMsg";

function newUserUuid(): string {
  return crypto.randomUUID();
}

export default function LoginPage() {
  const router = useRouter();
  const [userId, setUserId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.login(userId, apiKey);
      saveCredentials(res.user_id, apiKey.trim());
      router.push("/runs");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white border border-gray-200 rounded-xl p-8 w-full max-w-sm shadow-sm">
        <h1 className="text-lg font-semibold text-gray-900 mb-2">Sign in to Lead Ops</h1>
        <p className="text-xs text-gray-500 mb-6">
          Use a <strong>full UUID</strong> (not a username) and <strong>OPERATOR_API_KEY</strong> from the server{" "}
          <code className="text-[10px]">.env</code> file. First sign-in with a new UUID creates your account.
        </p>
        {error && <div className="mb-4"><ErrorMsg message={error} /></div>}
        <form onSubmit={submit} className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">User UUID</label>
              <button
                type="button"
                className="text-xs text-blue-600 hover:underline"
                onClick={() => setUserId(newUserUuid())}
              >
                Generate UUID
              </button>
            </div>
            <input
              required
              className={inp}
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
            <input
              type="password"
              required
              className={inp}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Your secret API key"
              autoComplete="current-password"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-md"
          >
            {loading ? "Verifying…" : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}

const inp = "w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono text-xs";
