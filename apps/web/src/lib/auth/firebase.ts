import { getApps, initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { env } from "@/lib/env";

export const firebaseApp =
  getApps()[0] ??
  initializeApp({
    apiKey: env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    appId: env.NEXT_PUBLIC_FIREBASE_APP_ID,
  });

export const auth = getAuth(firebaseApp);
