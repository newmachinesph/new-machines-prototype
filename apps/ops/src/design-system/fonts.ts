import { Geist, Geist_Mono, Michroma, Noto_Sans_JP } from "next/font/google";

// To switch the UI typeface: change the loader here and keep the variable name.
export const geistSans = Geist({ subsets: ["latin"], variable: "--font-geist-sans", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
export const notoJp = Noto_Sans_JP({ subsets: ["latin"], variable: "--font-noto-jp", display: "swap", preload: false });
export const michroma = Michroma({ weight: "400", subsets: ["latin"], variable: "--font-michroma", display: "swap" });

export const fontClassNames = [geistSans.variable, geistMono.variable, notoJp.variable, michroma.variable].join(" ");
