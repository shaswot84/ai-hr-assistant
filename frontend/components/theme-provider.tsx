"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * Thin wrapper around next-themes' ThemeProvider so the app can control
 * theme persistence via `attribute="class"` without repeating props on every
 * layout. Forwards all props to the underlying provider.
 *
 * @param props.children Child tree that should have access to the theme.
 * @param props.props Remaining next-themes provider options passed through.
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}