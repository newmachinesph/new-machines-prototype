"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { setTokenSource, setUnauthorizedHandler } from "@/lib/api/client";
import { env } from "@/lib/env";

type User = { uid: string; email: string | null; name: string | null };
type Status = "loading" | "signed-in" | "signed-out";
type Session = {
  status: Status;
  user: User | null;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);
const MOCK_USER: User = { uid: "user_demo", email: "demo@newmachin.es", name: "Demo operator" };
const MOCK_KEY = "nm-mock-session";

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (env.NEXT_PUBLIC_AUTH_MOCK) {
      // Tests only: a fixed demo user, remembered for the tab.
      void Promise.resolve().then(() => {
        if (cancelled) return;
        const signedIn = sessionStorage.getItem(MOCK_KEY) === "1";
        setUser(signedIn ? MOCK_USER : null);
        setStatus(signedIn ? "signed-in" : "signed-out");
      });
      return () => {
        cancelled = true;
      };
    }
    let unsubscribe = () => {};
    const fail = (e: unknown) => {
      console.error("Sign-in service failed to start", e);
      if (cancelled) return;
      setUser(null);
      setStatus("signed-out");
    };
    void import("./firebase")
      .then(async ({ auth }) => {
        const { onIdTokenChanged } = await import("firebase/auth");
        if (cancelled) return;
        setTokenSource(async () => (auth.currentUser ? auth.currentUser.getIdToken() : null));
        unsubscribe = onIdTokenChanged(
          auth,
          (u) => {
            setUser(u ? { uid: u.uid, email: u.email, name: u.displayName } : null);
            setStatus(u ? "signed-in" : "signed-out");
          },
          fail,
        );
      })
      .catch(fail);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const value = useMemo<Session>(() => {
    const mock = env.NEXT_PUBLIC_AUTH_MOCK;
    function mockIn() {
      sessionStorage.setItem(MOCK_KEY, "1");
      setUser(MOCK_USER);
      setStatus("signed-in");
    }
    return {
      status,
      user,
      async signInWithGoogle() {
        if (mock) return mockIn();
        const [{ auth }, { GoogleAuthProvider, signInWithPopup }] = await Promise.all([
          import("./firebase"),
          import("firebase/auth"),
        ]);
        await signInWithPopup(auth, new GoogleAuthProvider());
      },
      async signInWithEmail(email, password) {
        if (mock) return mockIn();
        const [{ auth }, { signInWithEmailAndPassword }] = await Promise.all([
          import("./firebase"),
          import("firebase/auth"),
        ]);
        await signInWithEmailAndPassword(auth, email, password);
      },
      async signOut() {
        await qc.cancelQueries();
        if (mock) {
          sessionStorage.removeItem(MOCK_KEY);
          setUser(null);
          setStatus("signed-out");
        } else {
          const [{ auth }, { signOut }] = await Promise.all([import("./firebase"), import("firebase/auth")]);
          await signOut(auth);
        }
        qc.clear();
      },
    };
  }, [status, user, qc]);

  // A 401 means the backend rejected this session: sign out first, or the landing page would sign straight back in.
  const { signOut } = value;
  useEffect(() => {
    setUnauthorizedHandler(async () => {
      await signOut();
      router.replace("/");
    });
    return () => setUnauthorizedHandler(null);
  }, [signOut, router]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}
