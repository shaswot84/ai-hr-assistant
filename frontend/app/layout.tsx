import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

/** Geist Sans applied as a CSS variable for the whole app. */
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

/** Geist Mono applied as a CSS variable for the whole app. */
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** Global metadata used by the browser tab and social previews. */
export const metadata: Metadata = {
  title: "AI HR Assistant",
  description: "Recruitment, leave and HR policy at your fingertips.",
};

/**
 * Root layout: sets up fonts and the base page shell. The app is light-mode
 * only; colors are declared once in globals.css and never switch at runtime.
 *
 * @param props.children Page content rendered inside the shell.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}