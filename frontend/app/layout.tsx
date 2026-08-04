import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
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
 * Root layout: sets up fonts, the global theme provider, and the base page
 * shell. `suppressHydrationWarning` avoids hydration mismatches caused by the
 * theme class being applied by next-themes after mount.
 *
 * @param props.children Page content rendered inside the theme provider.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}