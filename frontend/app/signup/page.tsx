"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Signup removed — first login with a new UUID + API key creates your account. */
export default function SignupPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/login");
  }, [router]);
  return null;
}
